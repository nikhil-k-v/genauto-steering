# Fonts

| file | family | licence | used for |
|---|---|---|---|
| `Barlow-Regular/Medium/SemiBold.ttf` | Barlow (Jeremy Tribby) | SIL OFL 1.1 | all UI text, buttons, headings |
| `BarlowSemiCondensed-Medium.ttf` | Barlow Semi Condensed | SIL OFL 1.1 | the large wheel-angle numeral |
| `IBMPlexMono-Regular/Medium.ttf` | IBM Plex Mono | SIL OFL 1.1 | file paths, event log, counters |
| `DejaVuSans.ttf` | DejaVu Sans | DejaVu Fonts License (Bitstream Vera derivative, free) | plot axes, ticks and legends (the app's original font: open, unambiguous digits at small sizes). `web/fonts/DejaVuSans-plot.woff2` is a Latin subset for the browser plots |

Source: github.com/google/fonts (`ofl/barlow`, `ofl/barlowsemicondensed`, `ofl/ibmplexmono`).

The Barlow files here are modified: the OpenType `tnum` alternates are baked into the default
character map so digits are fixed-width (live numbers don't jitter). Script:
`scripts/bake_tnum.py`. The same fonts are shipped as woff2 in `web/fonts/` for the browser pages.

Why Barlow: it descends from California highway signage — legible at a glance, compact, and from the
vehicle world this tool lives in.
