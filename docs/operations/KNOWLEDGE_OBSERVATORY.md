# 36 Chambers — Knowledge Observatory

## Cel

Pakiet monitoruje przyrost wiedzy, aktywność agentów w komnatach, użycie dokumentów oraz kandydatów do archiwizacji. Działa na osobnej bazie analitycznej; nie modyfikuje Chroma, sist2, grafu ani baz biznesowych.

## Pliki

```text
knowledge_observatory_schema.sql       Schemat oddzielnej bazy observability
knowledge_inventory_scan.py            Skan metadanych baz/plików z registry
import_observatory_events.py           Import trace JSONL agentów i retrievalu
knowledge_observatory_dashboard.py     Ciemny dashboard HTML + cold_assets.csv
run_knowledge_observatory.ps1          Instalacja, snapshot, import i dashboard
```

## Instalacja

W katalogu z plikami uruchom PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\run_knowledge_observatory.ps1 -OpenDashboard
```

Launcher instaluje `pandas` i `plotly`, wykonuje metadata-only snapshot registry i generuje dashboard.

## Pierwsze uruchomienie

```powershell
.\run_knowledge_observatory.ps1 `
  -Registry "$CHAMBERS_REGISTRY" `
  -Db "$CHAMBERS_OBSERVATORY_SQLITE" `
  -OutDir "$CHAMBERS_OBSERVATORY_DASHBOARD" `
  -OpenDashboard
```

Wyniki:

```text
<observatory directory>\
  knowledge_observatory.sqlite
  dashboard\
    knowledge_assets.html
    agent_visits.html
    activity_frequency.html
    top_retrieved.html
    cold_assets.html
    cold_assets.csv
    summary.md
```

## Telemetria agentów

Dodaj do orchestratora zapis JSONL. Każda linia to jeden event.

### Agent visit

```json
{"event_type":"agent_event","event_time":"2026-09-20T05:45:00+02:00","request_id":"uuid","agent_name":"shaolin_orchestrator","app_name":"The_Buch","chamber_id":3,"resource_id":"devz_chroma_v2","action":"semantic_retrieval","status":"success","latency_ms":184,"model":"deepseek/deepseek-v3.1","task_type":"technical_knowledge"}
```

### Retrieval document/chunk

```json
{"event_type":"retrieval_event","event_time":"2026-09-20T05:45:00+02:00","request_id":"uuid","agent_name":"shaolin_orchestrator","chamber_id":3,"resource_id":"devz_chroma_v2","document_id":"doc_123","chunk_id":"chunk_123_04","retrieval_method":"semantic","rank":1,"score":0.824,"included_in_prompt":true,"cited_in_answer":true,"source_modified_at":"2026-09-18T12:00:00+02:00","indexed_at":"2026-09-19T02:30:00+02:00","embedding_model":"your_embedding_model","token_count":510}
```

Import:

```powershell
.\run_knowledge_observatory.ps1 `
  -EventLog "<events directory>\retrieval_YYYY-MM-DD.jsonl" `
  -OpenDashboard
```

## Interpretacja

- `knowledge_assets.html`: ile baz/plików jest w każdej Chamber oraz jaki zajmują rozmiar.
- `agent_visits.html`: gdzie agenci bywają najczęściej.
- `activity_frequency.html`: liczba działań agentów per dzień.
- `top_retrieved.html`: dokumenty najczęściej pobierane, włączane do promptu i cytowane.
- `cold_assets.csv`: metadane kandydatów bez eventów użycia. To lista do review, nie lista do kasowania.

## Bezpieczeństwo i retencja

1. Przed archiwizacją twórz backup i manifest SHA-256.
2. Nigdy nie usuwaj automatycznie `chroma.sqlite3`, katalogów HNSW, baz biznesowych ani pamięci agentów.
3. Nadaj zasobom w registry `resource_id`, `owner`, `sensitivity` oraz `retention_class`.
4. Zasoby z `PROTECTED`/`DO_NOT_DELETE` wyklucz z automatycznych rekomendacji.
5. Najpierw zbieraj telemetry przez 30–90 dni; dopiero potem klasyfikuj jako `COLD`/`CANDIDATE_ARCHIVE`.

## Harmonogram

- snapshot inventory: raz w tygodniu;
- import telemetry: codziennie lub po każdym batchu;
- dashboard: po imporcie telemetry;
- review cold assets: co 30 dni;
- archiwizacja: po review ownera, backupie i okresie karencji.
