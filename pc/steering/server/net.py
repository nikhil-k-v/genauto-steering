"""
server/net.py - how other devices find the hub on the Wi-Fi.

  * lan_ips()          the laptop's IPv4 addresses that other devices can reach
  * hub_urls()         every address worth showing (this laptop, Wi-Fi, mDNS name, Pages link)
  * Advertiser         announces the hub as <name>.local over mDNS (optional: needs `zeroconf`)
  * qr_matrix()        QR code modules for a URL (optional: needs `segno`)

The public front door is a GitHub Pages copy of the web UI (docs work there
with no hub at all).  A page served over https may not talk to a plain-http
device on the LAN (mixed content), so for other devices the Pages site hands
over to the laptop's own copy at http://<ip>:<port>/; on the laptop itself it
can talk to http://localhost:<port> directly (browsers treat localhost as
secure).  `?hub=<ip>:<port>` in the Pages URL makes that a one-tap link/QR.
"""
from __future__ import annotations

import logging
import socket
from typing import Dict, List, Optional
from urllib.parse import quote, urlsplit

log = logging.getLogger(__name__)


def lan_ips() -> List[str]:
    """IPv4 addresses of this machine that are not loopback, primary (default route) first."""
    out: List[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))           # no packet is sent; just picks the outgoing interface
        out.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in out:
                out.append(ip)
    except Exception:
        pass
    return [ip for ip in out if not ip.startswith("127.") and not ip.startswith("169.254.")]


def pages_origin(pages_url: str) -> str:
    p = urlsplit(pages_url)
    return f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else ""


def hub_urls(port: int, pages_url: str = "", mdns_name: str = "", mdns_on: bool = False) -> Dict[str, object]:
    ips = lan_ips()
    lan = [f"http://{ip}:{port}/" for ip in ips]
    d: Dict[str, object] = {"local": f"http://localhost:{port}/", "lan": lan,
                            "mdns": f"http://{mdns_name}.local:{port}/" if (mdns_name and mdns_on) else ""}
    if pages_url:
        host = f"{ips[0]}:{port}" if ips else f"localhost:{port}"
        d["pages"] = pages_url
        d["pages_link"] = f"{pages_url.rstrip('/')}/?hub={quote(host, safe=':')}"
    return d


class Advertiser:
    """mDNS: makes http://<name>.local:<port>/ resolve on the Wi-Fi (macOS, iOS, Linux, Windows 10+;
    Android Chrome may not resolve .local, so the IP link stays the fallback)."""

    def __init__(self, name: str, port: int):
        self.name, self.port = name, port
        self._zc = None
        self._info = None
        self.ok = False
        self.error = ""

    def start(self):
        try:
            from zeroconf import ServiceInfo, Zeroconf
        except ImportError:
            self.error = "zeroconf not installed (pip install 'genauto-steering[server]')"
            return
        ips = lan_ips()
        if not ips:
            self.error = "no network address"
            return
        try:
            self._info = ServiceInfo("_http._tcp.local.", "Gen Auto steering hub._http._tcp.local.",
                                     addresses=[socket.inet_aton(ip) for ip in ips], port=self.port,
                                     properties={"path": "/"}, server=f"{self.name}.local.")
            self._zc = Zeroconf()
            self._zc.register_service(self._info, allow_name_change=True)
            self.ok = True
            log.info("mDNS: http://%s.local:%d/ -> %s", self.name, self.port, ", ".join(ips))
        except Exception as e:                      # another host with the name, no multicast, ...
            self.error = str(e)
            log.warning("mDNS advertise failed: %s", e)

    def stop(self):
        try:
            if self._zc and self._info:
                self._zc.unregister_service(self._info)
            if self._zc:
                self._zc.close()
        except Exception:
            pass
        self._zc = self._info = None
        self.ok = False


def qr_matrix(text: str) -> Optional[List[List[bool]]]:
    """QR modules (True = dark), quiet zone not included; None if segno is missing."""
    try:
        import segno
    except ImportError:
        return None
    q = segno.make(text, error="m")
    return [[bool(c) for c in row] for row in q.matrix]


def qr_svg(text: str, scale: int = 4) -> Optional[str]:
    try:
        import segno
    except ImportError:
        return None
    import io
    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="svg", scale=scale, border=2, dark="#1b2129", light="#ffffff",
                                     xmldecl=False)
    return buf.getvalue().decode()
