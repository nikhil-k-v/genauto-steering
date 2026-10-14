"""Bake OpenType tnum (tabular figures) into the default cmap so DPG/SVG get fixed-width digits."""
import sys
from fontTools.ttLib import TTFont

def bake(src, dst, woff2=None):
    f = TTFont(src)
    gsub = f["GSUB"].table
    idx = [i for i, fr in enumerate(gsub.FeatureList.FeatureRecord) if fr.FeatureTag == "tnum"]
    mapping = {}
    for i in idx:
        for li in gsub.FeatureList.FeatureRecord[i].Feature.LookupListIndex:
            lk = gsub.LookupList.Lookup[li]
            for st in lk.SubTable:
                st = getattr(st, "ExtSubTable", st)
                if hasattr(st, "mapping"):
                    mapping.update(st.mapping)
    n = 0
    for table in f["cmap"].tables:
        for cp, g in list(table.cmap.items()):
            if g in mapping and chr(cp) in "0123456789":
                table.cmap[cp] = mapping[g]; n += 1
    f.save(dst)
    if woff2:
        f.flavor = "woff2"; f.save(woff2)
    print(dst, "digits remapped:", n)

bake(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
