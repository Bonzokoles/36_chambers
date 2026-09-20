"""36 Chambers Knowledge Observatory — inventory scanner.

Safe by design: reads metadata only; does not modify scanned databases or files.
Creates/updates the dedicated observatory SQLite database and records a snapshot.
"""
from __future__ import annotations
import argparse, hashlib, json, os, socket, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import path as env_path

DEFAULT_REGISTRY = env_path("CHAMBERS_REGISTRY")
DEFAULT_DB = env_path("CHAMBERS_OBSERVATORY_SQLITE")
SCHEMA=Path(__file__).with_name("knowledge_observatory_schema.sql")

def iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def file_hash(path: Path, max_bytes=2_000_000):
    h=hashlib.sha256()
    with path.open("rb") as f: h.update(f.read(max_bytes))
    return h.hexdigest()
def connect(db):
    db.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(db); con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA.read_text(encoding="utf-8")); return con
def sqlite_count(path: Path):
    try:
        con=sqlite3.connect(f"file:{path.as_posix()}?mode=ro",uri=True,timeout=2)
        tables=[r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        counts={}
        for t in tables:
            if t.startswith("sqlite_"): continue
            try: counts[t]=con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            except sqlite3.Error: pass
        con.close(); return sum(counts.values()), json.dumps(counts,ensure_ascii=False)
    except Exception as e: return None, json.dumps({"error":str(e)})
def scan_chamber(con,snapshot,ch):
    cid=int(ch["id"]); resource_id=ch.get("resource_id",f"chamber_{cid}"); p=Path(ch.get("physical_path",""))
    candidates=[]
    if p.is_file(): candidates=[p]
    elif p.is_dir():
        # inventory only important DB-like artifacts; avoids recursively hashing all files
        candidates=list(p.rglob("*.sqlite"))+list(p.rglob("*.sqlite3"))+list(p.rglob("*.db"))+list(p.rglob("*.sist2"))
    for f in candidates:
        try:
            stat=f.stat(); aid=str(uuid.uuid5(uuid.NAMESPACE_URL,f"{cid}:{f}")); count,logical=sqlite_count(f) if f.suffix.lower() in {".sqlite",".sqlite3",".db",".sist2"} else (None,None)
            con.execute("""INSERT INTO knowledge_assets(asset_id,resource_id,chamber_id,asset_type,physical_path,logical_id,content_hash,size_bytes,modified_at,last_verified_at,sensitivity,retention_class,owner)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(asset_id) DO UPDATE SET size_bytes=excluded.size_bytes,modified_at=excluded.modified_at,last_verified_at=excluded.last_verified_at,content_hash=excluded.content_hash""",
            (aid,resource_id,cid,"database_file",str(f),logical,file_hash(f),stat.st_size,datetime.fromtimestamp(stat.st_mtime,timezone.utc).isoformat(),iso(),ch.get("sensitivity","internal"),ch.get("retention_class","UNCLASSIFIED"),ch.get("owner")))
            con.execute("INSERT OR REPLACE INTO asset_snapshot_stats(snapshot_id,asset_id,exists_flag,size_bytes,record_count,chunk_count,collection_name,modified_at) VALUES(?,?,?,?,?,?,?,?)",
            (snapshot,aid,1,stat.st_size,count,None,None,datetime.fromtimestamp(stat.st_mtime,timezone.utc).isoformat()))
        except Exception as e: print(f"WARN {f}: {e}")
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--registry",type=Path,default=DEFAULT_REGISTRY); ap.add_argument("--db",type=Path,default=DEFAULT_DB); args=ap.parse_args()
    reg=json.loads(args.registry.read_text(encoding="utf-8")); con=connect(args.db); sid=str(uuid.uuid4())
    con.execute("INSERT INTO inventory_snapshots VALUES(?,?,?,?,?)",(sid,iso(),"0.1",socket.gethostname(),"metadata-only scan"))
    for ch in reg.get("chambers",[]): scan_chamber(con,sid,ch)
    con.commit(); n=con.execute("SELECT count(*) FROM asset_snapshot_stats WHERE snapshot_id=?",(sid,)).fetchone()[0]; con.close(); print(f"Snapshot {sid}: {n} assets -> {args.db}")
if __name__=="__main__": main()
