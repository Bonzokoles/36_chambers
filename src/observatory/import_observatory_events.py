"""Import agent/retrieval JSONL events into Knowledge Observatory.
Expected event_type: agent_event or retrieval_event. Unknown event types are skipped.
"""
from __future__ import annotations
import argparse,json,sqlite3,uuid
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import path as env_path

from knowledge_inventory_scan import connect

def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--log",type=Path,required=True); ap.add_argument("--db",type=Path,default=env_path("CHAMBERS_OBSERVATORY_SQLITE")); args=ap.parse_args(); con=connect(args.db); ok=skip=0
 with args.log.open(encoding="utf-8") as f:
  for line in f:
   if not line.strip(): continue
   try:
    e=json.loads(line); typ=e.get("event_type"); eid=e.get("event_id",str(uuid.uuid4()))
    if typ=="agent_event":
     con.execute("INSERT OR IGNORE INTO agent_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(eid,e["event_time"],e["request_id"],e["agent_name"],e.get("app_name"),e.get("chamber_id"),e.get("resource_id"),e["action"],e.get("status","success"),e.get("latency_ms"),e.get("error_class"),e.get("model"),e.get("task_type"))); ok+=1
    elif typ=="retrieval_event":
     con.execute("INSERT OR IGNORE INTO retrieval_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(eid,e["event_time"],e["request_id"],e["agent_name"],e["chamber_id"],e.get("resource_id"),e.get("asset_id"),e.get("document_id"),e.get("chunk_id"),e.get("retrieval_method"),e.get("rank"),e.get("score"),int(e.get("included_in_prompt",False)),int(e.get("cited_in_answer",False)),e.get("source_modified_at"),e.get("indexed_at"),e.get("embedding_model"),e.get("token_count"))); ok+=1
    else: skip+=1
   except Exception as ex: print(f"WARN import: {ex}"); skip+=1
 con.commit(); con.close(); print(f"Imported={ok}, skipped={skip}")
if __name__=="__main__": main()
