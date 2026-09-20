r"""OpenRouter mini-benchmark: usage statistics, request frequency and model activity.

Modes:
  1) API mode: fetches aggregated Activity API data and optional analytics query.
  2) Local mode: analyzes a normalized JSONL request log produced by your apps.

Install:
  pip install requests pandas matplotlib tabulate

API mode:
  $env:OPENROUTER_MANAGEMENT_KEY="..."
  python openrouter_mini_benchmark.py --mode api --days 30 --out-dir .\openrouter_benchmark

Local mode:
  python openrouter_mini_benchmark.py --mode local --log .\requests.jsonl --out-dir .\openrouter_benchmark

Never commit API keys. Use a management key for analytics endpoints and a normal
API key only for generation calls. The script redacts key-like values from output.
"""
from __future__ import annotations
import argparse, json, os, re, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import pandas as pd

BASE="https://openrouter.ai/api/v1"
KEY_RE=re.compile(r"(?:sk-or-v1-|sk-or-)[A-Za-z0-9_.-]+")

def redact(x: Any) -> Any:
    if isinstance(x,str): return KEY_RE.sub("<REDACTED>",x)
    if isinstance(x,dict): return {k:redact(v) for k,v in x.items()}
    if isinstance(x,list): return [redact(v) for v in x]
    return x

def api_get(path, key, params=None):
    import requests
    r=requests.get(BASE+path,headers={"Authorization":f"Bearer {key}"},params=params,timeout=30)
    r.raise_for_status(); return r.json()

def api_post(path,key,payload):
    import requests
    r=requests.post(BASE+path,headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},json=payload,timeout=30)
    r.raise_for_status(); return r.json()

def as_records(payload):
    if isinstance(payload,list): return payload
    if not isinstance(payload,dict): return []
    for k in ("data","results","activity","items"):
        if isinstance(payload.get(k),list): return payload[k]
    return [payload]

def normalize(rows, source):
    out=[]
    for x in rows:
        if not isinstance(x,dict): continue
        r={"source":source, **x}
        # Keep common aliases available for analysis; unknown fields are preserved.
        r["date"]=r.get("date") or r.get("day") or r.get("timestamp")
        r["model"]=r.get("model") or r.get("endpoint") or r.get("model_name") or "unknown"
        r["requests"]=r.get("requests",r.get("request_count",r.get("count",1)))
        r["tokens"]=r.get("tokens",r.get("total_tokens",r.get("token_count",0)))
        r["cost"]=r.get("cost",r.get("spend",r.get("total_cost",0)))
        r["latency_ms"]=r.get("latency_ms",r.get("latency",None))
        out.append(r)
    return out

def local_records(path):
    rows=[]
    with open(path,encoding="utf-8") as f:
        for line in f:
            if line.strip(): rows.append(json.loads(line))
    return normalize(rows,"local_log")

def safe_num(s):
    return pd.to_numeric(s,errors="coerce").fillna(0)

def report(rows,out):
    out.mkdir(parents=True,exist_ok=True)
    raw=out/"raw_activity.json"
    raw.write_text(json.dumps(redact(rows),ensure_ascii=False,indent=2),encoding="utf-8")
    if not rows:
        (out/"summary.md").write_text("# OpenRouter mini-benchmark\n\nBrak danych.\n",encoding="utf-8"); return
    df=pd.DataFrame(rows)
    for c in ["requests","tokens","cost","latency_ms"]:
        if c not in df: df[c]=0
        df[c]=safe_num(df[c])
    df["date"]=pd.to_datetime(df.get("date"),errors="coerce",utc=True)
    df.to_csv(out/"activity_normalized.csv",index=False)
    by_model=df.groupby("model",dropna=False).agg(requests=("requests","sum"),tokens=("tokens","sum"),cost=("cost","sum"),avg_latency_ms=("latency_ms","mean")).sort_values("tokens",ascending=False)
    by_day=df.groupby(df["date"].dt.date,dropna=True).agg(requests=("requests","sum"),tokens=("tokens","sum"),cost=("cost","sum"))
    total_requests=float(df.requests.sum()); total_tokens=float(df.tokens.sum()); total_cost=float(df.cost.sum())
    summary=["# OpenRouter Mini Benchmark","",f"Rows: {len(df)}",f"Requests: {total_requests:,.0f}",f"Tokens: {total_tokens:,.0f}",f"Cost: {total_cost:,.6f}",f"Blended cost / 1M tokens: {(total_cost/total_tokens*1_000_000 if total_tokens else 0):.6f}","", "## By model", by_model.to_markdown(), "", "## By day", by_day.to_markdown()]
    (out/"summary.md").write_text("\n".join(summary),encoding="utf-8")
    try:
        import matplotlib.pyplot as plt
        plt.style.use("dark_background")
        def save(fig,name):
            fig.tight_layout(); fig.savefig(out/name,dpi=160,facecolor="#0b0f19"); plt.close(fig)
        fig,ax=plt.subplots(figsize=(12,5)); ax.bar(by_model.index.astype(str),by_model.tokens,color="#60a5fa"); ax.set_title("Token volume by model"); ax.set_ylabel("Tokens"); ax.tick_params(axis="x",rotation=35); save(fig,"tokens_by_model.png")
        fig,ax=plt.subplots(figsize=(12,5)); ax.bar(by_model.index.astype(str),by_model.requests,color="#34d399"); ax.set_title("Request volume by model"); ax.set_ylabel("Requests"); ax.tick_params(axis="x",rotation=35); save(fig,"requests_by_model.png")
        if not by_day.empty:
            fig,ax=plt.subplots(figsize=(12,5)); ax.plot(by_day.index.astype(str),by_day.requests,color="#fbbf24",marker="."); ax.set_title("Request frequency by day"); ax.set_ylabel("Requests"); ax.tick_params(axis="x",rotation=45); save(fig,"requests_by_day.png")
        if df.latency_ms.notna().any() and df.latency_ms.sum()>0:
            lat=df.groupby("model").latency_ms.agg(p50=lambda x:x.quantile(.5),p95=lambda x:x.quantile(.95))
            fig,ax=plt.subplots(figsize=(12,5)); lat.plot.bar(ax=ax,color=["#60a5fa","#f87171"]); ax.set_title("Latency p50 / p95 by model"); ax.set_ylabel("Milliseconds"); ax.tick_params(axis="x",rotation=35); save(fig,"latency_by_model.png")
    except ImportError:
        (out/"PLOTS_REQUIRES.txt").write_text("Install matplotlib to generate PNG plots: pip install matplotlib\n",encoding="utf-8")

def main():
    p=argparse.ArgumentParser(); p.add_argument("--mode",choices=["api","local"],required=True); p.add_argument("--days",type=int,default=30); p.add_argument("--log",type=Path); p.add_argument("--out-dir",type=Path,default=Path("openrouter_benchmark")); args=p.parse_args()
    if args.mode=="local":
        if not args.log: p.error("--log is required in local mode")
        rows=local_records(args.log)
    else:
        key=os.getenv("OPENROUTER_MANAGEMENT_KEY")
        if not key: p.error("Set OPENROUTER_MANAGEMENT_KEY first")
        # Activity endpoint provides daily model-endpoint aggregates for completed UTC days.
        rows=normalize(as_records(api_get("/activity",key)),"activity_api")
        # Optional: metadata/query endpoints can be enabled after inspecting supported dimensions.
        meta=None
        try: meta=api_get("/analytics/meta",key)
        except Exception as e: meta={"error":str(e)}
        (args.out_dir).mkdir(parents=True,exist_ok=True)
        (args.out_dir/"analytics_meta.json").write_text(json.dumps(redact(meta),ensure_ascii=False,indent=2),encoding="utf-8")
    report(rows,args.out_dir)
    print(f"Benchmark complete: {len(rows)} rows -> {args.out_dir}")

if __name__=="__main__": main()
