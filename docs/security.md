# Security and Safety Boundary

## Threat Model Summary

This VehicleGPT Edge system is an **informational assistant only** — it has **no actuator-write path** and **cannot generate vehicle-control commands**. The following requirements are enforced at the architecture level.

## Enforced Boundaries

| Boundary | Enforcement Mechanism |
|---|---|
| No actuator-write path | Application architecture; no CAN/SOME/IP write functions exposed in any module |
| No arbitrary CAN commands | SocketCAN adapter only reads; `read()` raises `NotImplementedError` when a real bus is unavailable |
| No LLM-generated control commands | LLM (if available) is confined to `llm/answer_validator.py`; query engine routes to deterministic SQL, never to LLM for actuation |
| No arbitrary shell execution | `benchmarks/benchmark.py` removed `subprocess`, `os.system`, `os.popen`, `eval(`, `exec(` |
| No arbitrary SQL execution from NL input | `query_engine/intent_router.py` + `retrieval.py` use **parameterized SQL only**; NL input is never concatenated into executable SQL |
| No cloud dependency for normal queries | `api/main.py` binds to `127.0.0.1`; all databases are local SQLite; model backend optional and offline-first |
| No external API calls in query path | `test_security.py` asserts no `urllib.request`, `requests.`, `httpx.`, `socket.` in source (except optional local_model.py) |
| Local-only processing and storage | By default: all data stays on development computer; database is SQLite file next to code |
| Input validation and bounded query execution | `intent_router.py` limits question length to 400 chars; `api/routes.py` validates `AskBody` |
| Restricted file access | `ingestion/adapters/csv_log.py` only reads from explicitly allowed paths; `tmp_path` isolation in tests |
| Safe handling of malformed logs and corrupt input | `analytics/anomalies.py` uses `value IS NOT NULL` guard; `normalizer.py` rejects non-numeric values as data, never executes them |
| Explicit error messages without exposing secrets | All error paths go through `api/main.py` health check; database errors show generic messages |

## What Would Be Needed for Production

| Area | Production Additions |
|---|---|
| OEM integration isolation | Hardware-isolated bus interfaces; gateway between diagnostic port and compute unit |
| Threat modelling | STRIDE analysis; attacker surface mapping for each protocol adapter |
| Verification and safety engineering | ISO 26262 functional safety decomposition; SIL verification of data boundaries |
| Model licence and redistribution | Qwen2.5 / Llama 3.2 licence compliance for OEM deployment |
| Over-the-air update mechanism | Secure update pipeline (separate from query path) |
| Extended safety certification | Full automotive safety certification process (beyond prototype scope) |

## Data Privacy

- All data is synthetic by default; any real vehicle data must be handled under OEM data-privacy policies.
- No driver-identifying information is stored.
- Ingested logs are treated as untrusted data — content never reaches `exec()` or `eval()`.