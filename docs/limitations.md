# Limitations

## Hardware & Performance

- **Benchmark measured on x86 development PC, not ARM target**. Reported latencies and memory numbers are estimates for the 2 GB / 2 A5x constraint; actual embedded performance may vary.
- **No automotive-grade hardware tested**. Verification on target hardware (`VERIFIED ON TARGET HARDWARE`) is `NO` — this is a development-prototype environment.
- **SQLite at 60 days / 2M+ rows fits ~681 MB**. On embedded eMMC with slower I/O, query latencies may be higher than measured. Exact event lookup is already sub-millisecond in this prototype, but range/trend queries are more sensitive to I/O.
- **Optional LLM (Qwen2.5 0.5B GGUF q4_k_m) requires ~500 MB peak**. On 2 GB RAM systems this leaves ~1.5 GB for OS + SQLite + API + UI; model is off by default.

## Model & Causal Claims

- **No causal model implemented**. Correlation vs. causation: the system reports ranked correlations and uses language such as "associated with" or "may have contributed to" unless a validated causal method establishes proof. Never fabricate causal claims.
- **Model-assisted explanation is optional**. If the local model is unavailable, the deterministic engine answers all supported questions without the LLM.
- **Confidence scores are not displayed**. The answer format uses a deterministic validity check instead of a confidence number.

## Data and Scenarios

- **Synthetic data only**. All vehicle data is generated with a fixed random seed; it does not represent real vehicle measurements. This is clearly labelled in the UI, reports, and charts.
- **60-day window is a demonstration limit**. Longer retention is possible but not tested; see `storage/retention.py` for retention logic.
- **Scenario coverage is representative, not exhaustive**. Scenarios A-F cover the official case-study questions but do not encode every possible driving pattern.

## Protocol Integration Maturity

| Adapter | Status | Notes |
|---|---|---|
| Synthetic data generator | IMPLEMENTED | 60 days with scenarios A-F, ground truth |
| CSV/JSON log import | IMPLEMENTED | `ingestion/adapters/csv_log.py`; requires valid format |
| SocketCAN | NOT IMPLEMENTED in this environment | Requires Linux + `python-can`; adapter interface documented |
| SOME/IP | Documented only | Adapter interface with normalized outputs; no test environment |
| Android Vehicle HAL | Documented only | Normalized output schema defined; no real device |
| QNX logs/services | Documented only | Normalized output schema defined; no real QNX system |
| ADAS events | PARTIAL | Disengagement events generated in simulator; real ADAS integration future work |
| Camera metadata | NOT IMPLEMENTED | Schema defined; no camera pipeline in prototype |
| Diagnostic logs | IMPLEMENTED (DTC events) | `diagnostic_trouble_code` events in simulator |

## Offline Operation

- **Network disabled during test**: `test_security.py::test_query_path_is_offline_even_with_model_enabled` passes — deterministic answers returned even with `llm.enabled=True`.
- **One-time model download**: If the user enables the optional local model, the `.gguf` file is downloaded once during setup; the app does not require that connection during normal use.
- **All query path dependencies are local**: SQLite file, Python process, optional GGUF model binary. No cloud APIs, embedding services, or hosted databases are required for common queries.

## Storage Calculation Assumptions

- **Raw data size**: 60 signals × 10 Hz × 86,400 s/day × 60 days = 311,040,000 samples.
- **Per-sample representation** (SQLite row): ~200 bytes (timestamp 16 + signal_name 12 + value 8 + unit 4 + quality_flag 1 + ingestion_timestamp 12 + overhead).
- **Raw estimate**: 311M × 200 B ≈ 62.2 GB on-disk before compression.
- **SQLite measured**: 681.7 MB for 2M+ signal rows (60 days). Measured CSV gzip compression on a sampled export is ~14.94×; the larger ~90× reduction versus a naïve per-sample representation is an assumption, not an empirically measured ratio for this dataset.
- **Compression ratio**: The project does not report a single measured overall path compression ratio for the warm-tier SQLite store. The only measured compression figure is a sampled CSV gzip ratio of ~14.94× from `benchmarks/results/storage_audit.md`.
- **30-day estimate**: ~340 MB in SQLite (validated by measured 60-day size).
- **60-day estimate**: ~681 MB in SQLite (measured).## Unresolved personal fields

These are required by the submission criteria but were not provided in the workspace.
Do not invent them here.

- Team name: *[awaiting input]*
- Member names: *[awaiting input]*
- Roll numbers: *[awaiting input]*
- College: *[awaiting input]*
- Contact details: *[awaiting input]*
