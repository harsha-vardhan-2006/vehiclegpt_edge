# VehicleGPT Edge — Architecture

## High-Level System Architecture

```mermaid
graph TD
    UI[Browser-based UI (localhost)] -->|HTTP/JSON| API[FastAPI: api/main.py]
    API -->|SQLite queries| STORAGE[storage/database.py]
    API -->|LLM calls| LLM[llm/local_model.py (optional)]
    STORAGE -->|CAN/SOME/IP data| SIMULATOR[simulator/generate_vehicle_data.py]
    SIMULATOR -->|synthetic data| STORAGE
    API -->|answer routing| QUERY_ENGINE[query_engine/intent_router.py + retrieval.py + query_models.py]
    QUERY_ENGINE -->|SQL + analytics| STORAGE
    QUERY_ENGINE -->|evidence package| ANSWER_VALIDATOR[llm/answer_validator.py]
    ANSWER_VALIDATOR -->|validated answer| UI
```

## Data Flow

1. **Data Generation**: `simulator/generate_vehicle_data.py` generates 60 days of synthetic vehicle signals + events into SQLite.
2. **Storage**: `storage/database.py` manages normalized tables (`vehicle_signals`, `vehicle_events`, `trips`, `signal_dictionary`, `query_audit`).
3. **Query Engine**: `query_engine/intent_router.py` classifies the user's natural-language question into one of 8 categories. `retrieval.py` maps to parameterized SQL. `query_models.py` defines Pydantic structures for `Answer`, `Evidence`, `TimeRange`.
4. **Evidence & Validation**: `llm/answer_validator.py` checks that every numerical claim has evidence, units are consistent, timestamps are valid, and missing/stale data is disclosed.
5. **UI**: `ui/app.js` + `ui/style.css` provides a responsive browser dashboard.
6. **Optional LLM**: `llm/local_model.py` with `llama.cpp` GGUF for natural-language explanation only — never for numerical computation.

## Storage Design

- **vehicle_signals**: id, demo_vehicle_id, trip_id, signal_name, timestamp, value, unit, source, quality_status, data_maturity, ingestion_timestamp
- **vehicle_events**: id, demo_vehicle_id, trip_id, event_type, severity, timestamp, source, description, data_maturity, associated_signal_reference
- **trips**: trip_id, start_time, end_time, distance, road_type, energy_used, scenario_id
- **signal_dictionary**: signal_name, unit, description, valid_minimum, valid_maximum, source_mapping, conversion_rules
- **query_audit**: timestamp, query_category, retrieval_status, duration_ms, evidence_count, model_used, validation_status

Indexes on: `vehicle_signals(timestamp, signal_name)`, `vehicle_events(event_type, timestamp)`, `trips(trip_id)`.

## Edge Resource Budget (estimate for ARM A5x target)

| Component | Estimated RAM | Notes |
|---|---|---|
| OS (lightweight Linux) | ~200 MB | |
| SQLite + indexes (60 days) | ~50 MB | 2M+ rows, ~200 bytes/row |
| Signal dictionary + config | ~5 MB | |
| API + routing overhead | ~30 MB | FastAPI + Python runtime |
| Deterministic query engine | ~10 MB | Pure SQL; no LLM |
| Optional LLM (Qwen2.5 0.5B GGUF, q4_k_m) | ~500 MB | On-demand; off by default |
| UI (browser process) | ~50 MB | Chromium-based or vanilla JS |
| **Total (without model)** | **~300 MB** | Fits 2 GB budget comfortably |
| **Total (with model)** | **~800 MB** | Still within 2 GB budget |