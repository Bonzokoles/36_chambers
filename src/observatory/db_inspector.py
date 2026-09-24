import streamlit as st
import sqlite3
import pandas as pd
import chromadb
import os
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="36 Chambers Inspector", layout="wide", initial_sidebar_state="expanded")

# --- K.R.A.F.T. Styling ---
st.markdown("""
<style>
    .stApp { background-color: #05070a; color: #e2e8f0; font-family: 'Consolas', monospace; }
    h1, h2, h3 { color: #d4a574; font-family: 'Consolas', monospace; text-transform: uppercase; }
    .stSelectbox label, .stMarkdown p { color: #00E6A8 !important; }
    .dataframe { font-size: 12px; }
    div[data-testid="stExpander"] div[role="button"] p { color: #00e5ff; font-weight: bold; }
    .content-box { background: #11141c; border: 1px solid #1a202c; padding: 10px; margin-top: 10px; color: #e2e8f0; }
    a { color: #00e5ff !important; text-decoration: none; }
    a:hover { text-decoration: underline; color: #00E6A8 !important; }
</style>
""", unsafe_allow_html=True)

st.title("SHAOLIN // UNIVERSAL DATA INSPECTOR")

# Load base paths from env or use relative defaults
ROOT_DIR = os.getenv("CHAMBERS_ROOT", "./data")

CHAMBERS = {
    "Chamber 01 (sist2)": {"type": "sqlite", "path": os.getenv("SIST2_DB_PATH", os.path.join(ROOT_DIR, "01_sist2", "default.sist2")), "query": "SELECT id, path, size, mtime FROM document LIMIT 100"},
    "Chamber 03 (DEVz Chroma)": {"type": "chroma", "path": os.getenv("DEVZ_KB_PATH", os.path.join(ROOT_DIR, "03_chroma"))},
    "Chamber 04 (Hollow Bones)": {"type": "chroma", "path": os.getenv("HOLLOW_BONES_ROOT", os.path.join(ROOT_DIR, "04_hollow_bones"))},
    "Chamber 05 (Knowledge Graph)": {"type": "sqlite", "path": os.getenv("GRAPH_DB_PATH", os.path.join(ROOT_DIR, "05_graph", "knowledge_graph.sqlite3")), "query": "SELECT * FROM triples LIMIT 100"},
    "Chamber 10 (Bizops)": {"type": "sqlite", "path": os.getenv("BIZOPS_DB_PATH", os.path.join(ROOT_DIR, "10_bizops", "bizops.db")), "query": "SELECT * FROM products LIMIT 100"}
}

sidebar_choice = st.sidebar.selectbox("Select Module to Inspect:", list(CHAMBERS.keys()))
config = CHAMBERS[sidebar_choice]

st.subheader(f"Source: {sidebar_choice}")
st.write(f"Physical Path: {config['path']}")

def render_html_preview(title, content, meta=None):
    with st.expander(f"📖 Preview: {title}", expanded=False):
        if meta:
            st.json(meta)
        if content and ('<html' in str(content).lower() or '<div' in str(content).lower() or '<p>' in str(content).lower()):
            st.markdown(f'<div class="content-box">{content}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="content-box"><pre style="white-space: pre-wrap; color: #e2e8f0;">{content}</pre></div>', unsafe_allow_html=True)

if not os.path.exists(config['path']):
    st.warning(f"Database not found at: {config['path']}. Configure paths in .env file.")
else:
    if config["type"] == "sqlite":
        try:
            conn = sqlite3.connect(config['path'])
            # Sprawdzenie czy tabela istnieje przed odpytaniem
            df = pd.read_sql_query(config['query'], conn)
            st.markdown("### Tabular Data")
            st.dataframe(df, use_container_width=True)
            st.markdown("### Record Inspector")
            if not df.empty:
                row_idx = st.selectbox("Select row index for detailed view:", df.index)
                selected_row = df.iloc[row_idx].to_dict()
                path_str = str(selected_row.get('path', selected_row.get('id', 'N/A')))
                content_preview = selected_row.get('content', selected_row.get('text', str(selected_row)))
                if 'path' in selected_row and isinstance(selected_row['path'], str):
                    link = f"<a href='file:///{selected_row['path'].replace(chr(92), '/')}' target='_blank'>Open Local File: {selected_row['path']}</a>"
                    st.markdown(link, unsafe_allow_html=True)
                render_html_preview(path_str, content_preview, selected_row)
            conn.close()
        except Exception as e:
            st.error(f"SQLite Error: {e}")

    elif config["type"] == "chroma":
        try:
            client = chromadb.PersistentClient(path=config['path'])
            collections = [c.name for c in client.list_collections()]
            if collections:
                selected_col = st.selectbox("Select Vector Collection:", collections)
                col_obj = client.get_collection(selected_col)
                count = col_obj.count()
                st.write(f"Vector Count: **{count}**")
                if count > 0:
                    results = col_obj.get(limit=50)
                    ids = results.get('ids', [])
                    docs = results.get('documents', [])
                    metas = results.get('metadatas', [])
                    df_chroma = pd.DataFrame({"ID": ids, "Document Snippet": [str(d)[:100] + "..." for d in docs], "Metadata": [str(m) for m in metas]})
                    st.dataframe(df_chroma, use_container_width=True)
                    st.markdown("### Document Preview")
                    selected_id = st.selectbox("Select Document ID:", ids)
                    idx = ids.index(selected_id)
                    full_doc = docs[idx]
                    full_meta = metas[idx]
                    if full_meta and 'source' in full_meta:
                        src = full_meta['source']
                        if str(src).startswith('http'):
                            st.markdown(f"Source Link: <a href='{src}' target='_blank'>{src}</a>", unsafe_allow_html=True)
                        else:
                            st.markdown(f"Local File: <a href='file:///{str(src).replace(chr(92), '/')}' target='_blank'>{src}</a>", unsafe_allow_html=True)
                    render_html_preview(selected_id, full_doc, full_meta)
            else:
                st.warning("No collections found in this ChromaDB.")
        except Exception as e:
            st.error(f"ChromaDB Error: {e}")
