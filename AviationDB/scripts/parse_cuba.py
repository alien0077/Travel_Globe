#!/usr/bin/env python3
"""古巴 AIP PDF Parser - standalone."""
from __future__ import annotations
import json, re, sqlite3, sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import asin, atan2, cos, radians, sin, sqrt
from pathlib import Path
from pypdf import PdfReader

EARTH_RADIUS_NM = 3440.065
_COORD_RE = re.compile(r"(\d{1,3})[°\s]+(\d{1,2})['\s]+(\d{1,2}(?:\.\d+)?)\"?\s*([NSEW])", re.I)

def parse_dms(text):
    m = _COORD_RE.search(text)
    if not m: raise ValueError(f"Cannot parse DMS: {text}")
    d,mn,s,h = int(m.group(1)),int(m.group(2)),float(m.group(3)),m.group(4).upper()
    dec = d + mn/60 + s/3600
    return -dec if h in ("S","W") else dec

def haversine(l1,ln1,l2,ln2):
    l1,ln1,l2,ln2=map(radians,[l1,ln1,l2,ln2])
    return 2*EARTH_RADIUS_NM*asin(sqrt(sin((l2-l1)/2)**2+cos(l1)*cos(l2)*sin((ln2-ln1)/2)**2))

def bearing(l1,ln1,l2,ln2):
    l1,ln1,l2,ln2=map(radians,[l1,ln1,l2,ln2])
    y=sin(ln2-ln1)*cos(l2); x=cos(l1)*sin(l2)-sin(l1)*cos(l2)*cos(ln2-ln1)
    return (atan2(y,x)*180/3.141592653589793+360)%360

def nid(v): return " ".join(v.strip().upper().split())

def _suid(p,*a):
    from hashlib import sha256
    return f"{p}-{sha256('|'.join('' if x is None else str(x) for x in a).encode()).hexdigest()[:16]}"

COUNTRY,FIR,REGION = "CU","HAVANA","central-america"

@dataclass(frozen=True)
class NP: uid:str; ident:str; lat:float; lon:float; pt:str; sid:str
@dataclass(frozen=True)
class AW: uid:str; desig:str; rt:str|None; cc:str; fir:str; sid:str
@dataclass(frozen=True)
class AS: uid:str; awuid:str; seq:int; fuid:str; tuid:str; dnm:float|None; icd:float|None; rcd:float|None; sid:str
@dataclass
class DS: points:list=field(default_factory=list); airways:list=field(default_factory=list); segments:list=field(default_factory=list); issues:list=field(default_factory=list)

def parse_cuba_enr31(text, source_id, ds):
    pmap = {}
    blocks = re.split(r'\n(?=[A-Z]\d{1,4}[A-Z]?\s*[-–])', text)
    for block in blocks:
        m = re.match(r'([A-Z]\d{1,4}[A-Z]?)\s*[-–]', block)
        if not m: continue
        designator = nid(m.group(1))
        route_type = "ATS"
        pts = []
        _idigit = re.compile(r"\d{6}(?:\.\d+)?[NS]", re.I)
        for cm in _idigit.finditer(block):
            lat_s = cm.group()
            # Find longitude on next lines
            after = block[cm.end():cm.end()+80]
            lon_m2 = re.search(r"\d{7}(?:\.\d+)?[EW]", after, re.I)
            if not lon_m2: continue
            lon_s = lon_m2.group()
            try:
                lat_f = float(lat_s[:2]) + float(lat_s[2:4])/60 + float(lat_s[4:-1])/3600
                lon_f = float(lon_s[:3]) + float(lon_s[3:5])/60 + float(lon_s[5:-1])/3600
                if lat_s[-1]=="S": lat_f*=-1
                if lon_s[-1]=="W": lon_f*=-1
            except: continue
            before = block[:cm.start()].strip().split('\n')
            id_line = before[-1] if before else ""
            raw_id = ""
            for t in reversed(id_line.split()):
                t2 = re.sub(r"[^A-Z0-9]","",t.upper())
                if t2 and len(t2)>=3 and not t2.isdigit(): raw_id=t2; break
            if not raw_id: continue
            pts.append((nid(raw_id), lat_f, lon_f))
        
        if len(pts) < 2: continue
        aw = AW(uid=_suid("awy",designator,source_id,FIR),desig=designator,rt=route_type,cc=COUNTRY,fir=FIR,sid=source_id)
        ds.airways.append(aw)
        for i in range(1,len(pts)):
            prev=pts[i-1]; curr=pts[i]
            p1=pmap.get(prev[0])
            if not p1: p1=NP(uid=_suid("pt",prev[0],f"{prev[1]:.6f}",f"{prev[2]:.6f}",FIR),ident=prev[0],lat=prev[1],lon=prev[2],pt="SP",sid=source_id); pmap[prev[0]]=p1; ds.points.append(p1)
            p2=pmap.get(curr[0])
            if not p2: p2=NP(uid=_suid("pt",curr[0],f"{curr[1]:.6f}",f"{curr[2]:.6f}",FIR),ident=curr[0],lat=curr[1],lon=curr[2],pt="SP",sid=source_id); pmap[curr[0]]=p2; ds.points.append(p2)
            d=haversine(prev[1],prev[2],curr[1],curr[2]); br=bearing(prev[1],prev[2],curr[1],curr[2])
            ds.segments.append(AS(uid=_suid("seg",aw.uid,i,p1.uid,p2.uid),awuid=aw.uid,seq=i,fuid=p1.uid,tuid=p2.uid,dnm=round(d,2),icd=round(br,1),rcd=round((br+180)%360,1),sid=source_id))

SCHEMA = """CREATE TABLE IF NOT EXISTS nav_point(uid TEXT PRIMARY KEY,ident TEXT,lat REAL,lon REAL,pt_type TEXT,source_id TEXT);
CREATE TABLE IF NOT EXISTS airway(uid TEXT PRIMARY KEY,designator TEXT,route_type TEXT,country TEXT,fir TEXT,source_id TEXT);
CREATE TABLE IF NOT EXISTS airway_segment(uid TEXT PRIMARY KEY,aw_uid TEXT,seq INT,f_uid TEXT,t_uid TEXT,dist_nm REAL,init_crs REAL,rev_crs REAL,source_id TEXT);"""

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True); ap.add_argument("--db", default=None)
    args = ap.parse_args()
    rd = Path(args.dir); sid = rd.name
    dbp = Path(args.db) if args.db else Path(__file__).resolve().parent.parent/"data"/"processed"/f"aviation-{sid}.sqlite"
    dbp.parent.mkdir(parents=True,exist_ok=True)
    ds = DS()
    for fn in ["ENR_3.1.pdf","ENR_3.2.pdf"]:
        fp = rd/fn
        if fp.exists():
            text = "".join(p.extract_text()+"\n" for p in PdfReader(str(fp)).pages)
            parse_cuba_enr31(text, sid, ds)
            print(f"  {fn}: {len([a for a in ds.airways if a.sid==sid])} routes so far")
    fn44 = rd/"ENR_4.4.pdf"
    if fn44.exists():
        text = "".join(p.extract_text()+"\n" for p in PdfReader(str(fn44)).pages)
        parse_cuba_enr31(text, sid, ds)
        print(f"  ENR_4.4: points from route parsing")
    print(f"\nResult: {len(ds.points)} pts, {len(ds.airways)} awys, {len(ds.segments)} segs")
    conn = sqlite3.connect(str(dbp))
    conn.executescript(SCHEMA)
    for p in ds.points: conn.execute("INSERT OR REPLACE INTO nav_point VALUES(?,?,?,?,?,?)",(p.uid,p.ident,p.lat,p.lon,p.pt,p.sid))
    for a in ds.airways: conn.execute("INSERT OR REPLACE INTO airway VALUES(?,?,?,?,?,?)",(a.uid,a.desig,a.rt,a.cc,a.fir,a.sid))
    for s in ds.segments: conn.execute("INSERT OR REPLACE INTO airway_segment VALUES(?,?,?,?,?,?,?,?,?)",(s.uid,s.awuid,s.seq,s.fuid,s.tuid,s.dnm,s.icd,s.rcd,s.sid))
    conn.commit()
    c1=conn.execute("SELECT COUNT(*) FROM airway").fetchone()[0]
    c2=conn.execute("SELECT COUNT(*) FROM airway_segment").fetchone()[0]
    conn.close()
    print(f"  DB: {c1} airways, {c2} segments")

if __name__=="__main__":
    main()
