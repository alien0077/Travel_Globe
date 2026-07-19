#!/usr/bin/env python3
"""Israel eAIP Parser - standalone script."""
from __future__ import annotations
import json, re, sqlite3, sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from math import asin, atan2, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any

EARTH_RADIUS_NM = 3440.065

class CoordError(ValueError): pass

def _split_coords(s):
    '''Split '321952N0180749W' into ('321952N', '0180749W')'''
    m = re.match(r"(\d+(?:\.\d+)?[NS])\s*(\d+(?:\.\d+)?[EW])", s, re.I)
    return (m.group(1), m.group(2)) if m else (None, None)

def parse_coord(text: str) -> float:
    v = text.strip().upper().replace(" ", "")
    m = re.fullmatch(r"([NSEW])?(\d+(?:\.\d+)?)([NSEW])?", v)
    if not m: raise CoordError(f"Cannot parse: {text}")
    h = m.group(1) or m.group(3)
    if h is None: raise CoordError(f"Missing hemisphere: {text}")
    d = m.group(2); is_lon = h in {"E","W"}
    nd = 3 if is_lon else 2
    if len(d.split(".")[0]) < nd+4: raise CoordError(f"Too short: {text}")
    deg = int(d[:nd]); mi = int(d[nd:nd+2]); sec = float(d[nd+2:])
    dec = deg + mi/60 + sec/3600
    if h in {"S","W"}: dec *= -1
    return dec

_COORD_RE = re.compile(r"\d{6}(?:\.\d+)?[NS]\s*\d{7}(?:\.\d+)?[EW]", re.I)

def haversine(lat1,lon1,lat2,lon2):
    lat1,lon1,lat2,lon2 = map(radians,[lat1,lon1,lat2,lon2])
    d=lon2-lon1; a=sin((lat2-lat1)/2)**2+cos(lat1)*cos(lat2)*sin(d/2)**2
    return 2*EARTH_RADIUS_NM*asin(sqrt(a))

def bearing(lat1,lon1,lat2,lon2):
    lat1,lon1,lat2,lon2 = map(radians,[lat1,lon1,lat2,lon2])
    y=sin(lon2-lon1)*cos(lat2); x=cos(lat1)*sin(lat2)-sin(lat1)*cos(lat2)*cos(lon2-lon1)
    return (atan2(y,x)*180/3.141592653589793+360)%360

def nid(v: str) -> str: return " ".join(v.strip().upper().split())

def _suid(prefix: str, *p: object) -> str:
    from hashlib import sha256
    return f"{prefix}-{sha256('|'.join('' if x is None else str(x) for x in p).encode()).hexdigest()[:16]}"

FIR = "TEL_AVIV"; COUNTRY = "IL"; REGION = "middle-east"

@dataclass(frozen=True)
class NP: uid:str; ident:str; lat:float; lon:float; pt:str; sid:str
@dataclass(frozen=True)
class AW: uid:str; desig:str; rt:str|None; cc:str; fir:str; sid:str
@dataclass(frozen=True)
class AS: uid:str; awuid:str; seq:int; fuid:str; tuid:str; dnm:float|None; icd:float|None; rcd:float|None; sid:str
@dataclass
class DS: points:list=field(default_factory=list); airways:list=field(default_factory=list); segments:list=field(default_factory=list); issues:list=field(default_factory=list)

def _xt(html):
    """Extract tables handling nested tables properly."""
    class P(HTMLParser):
        def __init__(s):
            super().__init__(); s.tbl=[]; s._t=None; s._r=None; s._c=None; s._depth=0
        def handle_starttag(s,t,a):
            if t=="table":
                s._depth += 1
                if s._depth == 1: s._t = []
            elif t=="tr" and s._depth == 1 and s._t is not None: s._r = []
            elif t in {"td","th"} and s._depth == 1 and s._r is not None: s._c = []
        def handle_data(s,d):
            if s._c is not None: s._c.append(d)
        def handle_endtag(s,t):
            if t in {"td","th"} and s._depth == 1 and s._r is not None and s._c is not None:
                s._r.append(" ".join("".join(s._c).split())); s._c = None
            elif t=="tr" and s._depth == 1 and s._t is not None and s._r is not None:
                if any(c.strip() for c in s._r): s._t.append(s._r)
                s._r = None
            elif t=="table":
                if s._depth == 1 and s._t is not None: s.tbl.append(s._t); s._t = None
                s._depth -= 1
    p=P(); p.feed(html); return p.tbl

def parse_enr44(html, sid, issues):
    pts = []
    for tbl in _xt(html):
        if not tbl: continue
        h = " ".join(tbl[0]).upper().replace(" ","")
        if "NAME-CODE" not in h: continue
        for row in tbl[1:]:
            if len(row)<2: continue
            txt = " ".join(row)
            cm = _COORD_RE.search(txt)
            if not cm: continue
            before = txt[:cm.start()].strip()
            toks = before.split()
            ident = ""
            for t in reversed(toks):
                t2 = re.sub(r"[^A-Z0-9]","",t.upper())
                if t2 and len(t2)>=3 and not t2.isdigit(): ident=t2; break
            if not ident: continue
            try:
                cs = _split_coords(cm.group(0)); lat_s,lon_s = cs
                lat=parse_coord(lat_s); lon=parse_coord(lon_s)
            except: continue
            pts.append(NP(uid=_suid("pt",nid(ident),f"{lat:.6f}",f"{lon:.6f}",FIR),ident=nid(ident),lat=lat,lon=lon,pt="SIGNIFICANT_POINT",sid=sid))
    return pts

def parse_routes(html, sid, ptmap, dspts, issues):
    awys, segs = [], []
    for ti,tbl in enumerate(_xt(html),1):
        designator = None
        for row in tbl[:10]:
            if not row: continue
            c = row[0].strip()
            if c.upper().startswith(("ROUTE DESIGNATOR","1")): continue
            m = re.match(r"^([A-Z]\d{1,4}[A-Z]?)", c.upper())
            if m: designator=nid(m.group(1)); break
        if not designator: continue
        aw = AW(uid=_suid("awy",designator,sid,FIR),desig=designator,rt="ATS",cc=COUNTRY,fir=FIR,sid=sid)
        rpts, rsegs = [], []
        pd = None
        for row in tbl:
            txt = " ".join(row)
            cm = _COORD_RE.search(txt)
            if not cm:
                for cell in row:
                    mm = re.search(r"(\d+(?:\.\d+)?)\s*(?:NM|KM)", cell, re.I)
                    if mm:
                        v = float(mm.group(1))
                        if mm.group(1).upper()=="KM": v*=0.539957
                        if 0.1<=v<=9999: pd=v
                continue
            before = txt[:cm.start()].strip()
            before = re.sub(r"^[▲∆▼]\s*","",before).strip()
            toks = before.split()
            raw_id = ""
            for t in reversed(toks):
                t2 = re.sub(r"[^A-Z0-9]","",t.upper())
                if t2 and len(t2)>=3 and not t2.isdigit(): raw_id=t2; break
            if not raw_id: continue
            ident = nid(re.sub(r"[^A-Z0-9]","",raw_id.upper()))
            try:
                ls = cm.group(0).split()
                lat=parse_coord(ls[0]); lon=parse_coord(ls[1])
            except: continue
            pt = ptmap.get(ident)
            if not pt:
                pt = NP(uid=_suid("pt",ident,f"{lat:.6f}",f"{lon:.6f}",FIR),ident=ident,lat=lat,lon=lon,pt="SIGNIFICANT_POINT",sid=sid)
                ptmap[ident]=pt; dspts.append(pt)
            if rpts:
                pv=rpts[-1]; seq=len(rpts)
                d=pd or haversine(pv.lat,pv.lon,pt.lat,pt.lon)
                br=bearing(pv.lat,pv.lon,pt.lat,pt.lon)
                rsegs.append(AS(uid=_suid("seg",aw.uid,seq,pv.uid,pt.uid),awuid=aw.uid,seq=seq,fuid=pv.uid,tuid=pt.uid,dnm=round(d,2),icd=round(br,1),rcd=round((br+180)%360,1),sid=sid))
            rpts.append(pt); pd=None
        if len(rpts)>=2: awys.append(aw); segs.extend(rsegs)
    return awys, segs

SCHEMA = """
CREATE TABLE IF NOT EXISTS source_metadata(source_id TEXT PRIMARY KEY,provider TEXT,country TEXT,source_url TEXT,source_type TEXT,retrieved_at TEXT,redistribution_status TEXT);
CREATE TABLE IF NOT EXISTS nav_point(uid TEXT PRIMARY KEY,ident TEXT,lat REAL,lon REAL,pt_type TEXT,source_id TEXT);
CREATE TABLE IF NOT EXISTS airway(uid TEXT PRIMARY KEY,designator TEXT,route_type TEXT,country TEXT,fir TEXT,source_id TEXT);
CREATE TABLE IF NOT EXISTS airway_segment(uid TEXT PRIMARY KEY,aw_uid TEXT,seq INT,f_uid TEXT,t_uid TEXT,dist_nm REAL,init_crs REAL,rev_crs REAL,source_id TEXT);
"""
def makedb(p):
    c=sqlite3.connect(str(p)); c.executescript(SCHEMA); c.commit(); return c

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--db", default=None)
    ap.add_argument("--source-id", default="israel")
    args = ap.parse_args()
    
    rd = Path(args.dir)
    if not rd.is_dir(): print(f"✗ {rd}"); sys.exit(1)
    pr = Path(__file__).resolve().parent.parent
    dbp = Path(args.db) if args.db else pr/"data"/"processed"/f"aviation-{args.source_id}.sqlite"
    dbp.parent.mkdir(parents=True, exist_ok=True)
    
    docs = {}
    mf = rd/"manifest.json"
    if mf.exists():
        for a in json.loads(mf.read_text()).get("artifacts",[]):
            rp = a.get("target") or a.get("path","")
            if rp: p2 = pr/rp
            elif a.get("id"): p2 = rd/(a["id"].replace("enr_","")+".html")  # fallback: guess filename
            else: continue
            if p2.exists(): docs[a["id"]] = p2.read_text("utf-8","replace")
    
    if not docs:
        doc_map = {}
        for f in rd.glob("*.html"):
            fn = f.name
            if "ENR-4.4" in fn or "ENR_4.4" in fn: doc_map["enr_4_4"] = f
            elif "ENR-3.1" in fn: doc_map["enr_3_1"] = f
            elif "ENR-3.2" in fn: doc_map["enr_3_2"] = f
            elif "ENR-3.3" in fn: doc_map["enr_3_3"] = f
            elif "ENR-3.5" in fn: doc_map["enr_3_5"] = f
        for did, f in doc_map.items():
            docs[did] = f.read_text("utf-8","replace")
    
    print(f"Parsing {args.source_id}..."); print(f"  Files: {list(docs.keys())}")
    ds = DS(); pmap = {}
    
    for did, html in docs.items():
        if did=="enr_4_4":
            for pt in parse_enr44(html, args.source_id, ds.issues):
                pmap.setdefault(pt.ident, pt); ds.points.append(pt)
            print(f"  ENR 4.4: {sum(1 for p in ds.points if p.sid==args.source_id)} pts")
        elif did in ("enr_3_1","enr_3_2","enr_3_3"):
            a,s = parse_routes(html, args.source_id, pmap, ds.points, ds.issues)
            ds.airways.extend(a); ds.segments.extend(s)
            print(f"  {did}: {len(a)} routes, {len(s)} segs")
    
    print(f"\nResults: {len(ds.points)} pts, {len(ds.airways)} awys, {len(ds.segments)} segs")
    conn = makedb(dbp)
    for pt in ds.points:
        conn.execute("INSERT OR REPLACE INTO nav_point VALUES(?,?,?,?,?,?)",(pt.uid,pt.ident,pt.lat,pt.lon,pt.pt,pt.sid))
    for aw in ds.airways:
        conn.execute("INSERT OR REPLACE INTO airway VALUES(?,?,?,?,?,?)",(aw.uid,aw.desig,aw.rt,aw.cc,aw.fir,aw.sid))
    for seg in ds.segments:
        conn.execute("INSERT OR REPLACE INTO airway_segment VALUES(?,?,?,?,?,?,?,?,?)",(seg.uid,seg.awuid,seg.seq,seg.fuid,seg.tuid,seg.dnm,seg.icd,seg.rcd,seg.sid))
    conn.commit()
    c=conn.execute("SELECT COUNT(*) FROM airway"); r=c.fetchone()[0]
    c2=conn.execute("SELECT COUNT(*) FROM airway_segment"); s=c2.fetchone()[0]
    conn.close()
    print(f"  DB: {r} airways, {s} segments")
    if ds.issues:
        for i in ds.issues[:5]: print(f"  ⚠ {i}")
    print("✓ Done")

if __name__=="__main__":
    main()
