"""Generate dark technical HTML dashboard for Knowledge Observatory.
Install: pip install pandas plotly
"""
from __future__ import annotations
import argparse,sqlite3
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import path as env_path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

BG="#0b0f19"; PANEL="#111827"; TEXT="#e5e7eb"; GRID="#1f2937"; COLORS=["#60a5fa","#34d399","#fbbf24","#f87171","#a78bfa"]
def style(fig,title):
 fig.update_layout(title=title,paper_bgcolor=BG,plot_bgcolor=PANEL,font=dict(color=TEXT,family="Consolas, monospace"),margin=dict(l=55,r=25,t=55,b=55),legend=dict(bgcolor=PANEL),xaxis=dict(gridcolor=GRID,linecolor=GRID),yaxis=dict(gridcolor=GRID,linecolor=GRID)); return fig
def save(fig,path): fig.write_html(path,include_plotlyjs="cdn",full_html=True)
def q(con,sql): return pd.read_sql_query(sql,con)
def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--db",type=Path,default=env_path("CHAMBERS_OBSERVATORY_SQLITE")); ap.add_argument("--out-dir",type=Path,default=env_path("CHAMBERS_OBSERVATORY_DASHBOARD")); args=ap.parse_args(); args.out_dir.mkdir(parents=True,exist_ok=True); con=sqlite3.connect(args.db)
 assets=q(con,"SELECT chamber_id, count(*) assets, sum(size_bytes)/1048576.0 size_mb FROM knowledge_assets GROUP BY chamber_id")
 if not assets.empty: save(style(px.bar(assets,x="chamber_id",y="assets",color="size_mb",color_continuous_scale="Blues"),"Knowledge assets by Chamber"),args.out_dir/"knowledge_assets.html")
 visits=q(con,"SELECT chamber_id,agent_name,count(*) visits FROM agent_events GROUP BY chamber_id,agent_name ORDER BY visits DESC")
 if not visits.empty: save(style(px.bar(visits,x="chamber_id",y="visits",color="agent_name",barmode="group",color_discrete_sequence=COLORS),"Agent visits by Chamber"),args.out_dir/"agent_visits.html")
 freq=q(con,"SELECT substr(event_time,1,10) day,count(*) events FROM agent_events GROUP BY day ORDER BY day")
 if not freq.empty: save(style(px.line(freq,x="day",y="events",markers=True,color_discrete_sequence=["#fbbf24"]),"Agent activity frequency"),args.out_dir/"activity_frequency.html")
 top=q(con,"SELECT chamber_id,coalesce(document_id,asset_id,'unknown') document_id,count(*) retrieved,sum(included_in_prompt) included,sum(cited_in_answer) cited,round(avg(score),3) avg_score,max(event_time) last_seen FROM retrieval_events GROUP BY chamber_id,document_id ORDER BY retrieved DESC LIMIT 50")
 if not top.empty: save(style(px.bar(top,x="document_id",y="retrieved",color="chamber_id",hover_data=["included","cited","avg_score","last_seen"],color_discrete_sequence=COLORS),"Top retrieved documents"),args.out_dir/"top_retrieved.html")
 cold=q(con,"""SELECT a.chamber_id,a.physical_path,round(a.size_bytes/1048576.0,2) size_mb,a.modified_at,max(e.event_time) last_use FROM knowledge_assets a LEFT JOIN agent_events e ON e.resource_id=a.resource_id GROUP BY a.asset_id HAVING last_use IS NULL ORDER BY a.size_bytes DESC""")
 cold.to_csv(args.out_dir/"cold_assets.csv",index=False)
 save(style(go.Figure(data=[go.Table(header=dict(values=list(cold.columns),fill_color=PANEL,font=dict(color=TEXT),line_color=GRID),cells=dict(values=[cold[c] for c in cold.columns],fill_color=BG,font=dict(color=TEXT),line_color=GRID))]),"Cold / never-used candidates"),args.out_dir/"cold_assets.html")
 summary=[f"# Knowledge Observatory\n",f"Assets: {len(q(con,'SELECT * FROM knowledge_assets'))}",f"Agent events: {len(q(con,'SELECT * FROM agent_events'))}",f"Retrieval events: {len(q(con,'SELECT * FROM retrieval_events'))}",f"Cold candidates: {len(cold)}"]
 (args.out_dir/"summary.md").write_text("\n\n".join(summary),encoding="utf-8"); con.close(); print(f"Dashboard -> {args.out_dir}")
if __name__=="__main__": main()
