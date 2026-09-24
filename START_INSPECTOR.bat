@echo off
TITLE SHAOLIN DATA INSPECTOR (PUBLIC)
echo [INIT] Preparing Python environment...
python -m pip install streamlit pandas chromadb python-dotenv --quiet
echo [INIT] Launching Inspector...
python -m streamlit run src/observatory/db_inspector.py
pause
