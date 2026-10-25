# VehicleGPT Edge - benchmark results

Generated: 2026-10-25 19:15:40 (UTC)

## Environment

| item | value |
|---|---|
| CPU | Intel64 Family 6 Model 140 Stepping 1, GenuineIntel (8 logical cores) |
| OS | Windows 11 |
| Python | 3.13.2 |
| RAM total | 7926 MB |
| Database | vehiclegpt.db = 681.7 MB, 
2,096,999 signal rows, 254 events, 120 trips |
| History window | 60.42 days |
| Model | disabled (deterministic mode) |
| Measurement host | **development PC (x86) - NOT target automotive hardware** |

## Memory (measured)

| metric | value | method |
|---|---|---|
| RSS at start | 35.7 MB | GetProcessMemoryInfo.WorkingSetSize |
| RSS at end | 42.6 MB | GetProcessMemoryInfo.WorkingSetSize |
| Python allocations peak | 1.1 MB | tracemalloc |

## Latency (measured, median / p95 over repeats)

| operation | median ms | p95 ms | reps | label |
|---|---|---|---|---|
| exact_event_lookup | 0.06 | 0.09 | 20 | MEASUREMENT |
| time_range_search | 10.29 | 14.17 | 20 | MEASUREMENT |
| trend_calculation | 9.14 | 10.99 | 20 | MEASUREMENT |
| official_q1_range_reduction | 267.02 | 281.28 | 10 | MEASUREMENT |
| official_q2_efficiency_drop | 3.24 | 6.34 | 10 | MEASUREMENT |
| official_q3_adas_events | 1.32 | 1.48 | 10 | MEASUREMENT |
| official_q4_before_warning | 24.92 | 32.08 | 10 | MEASUREMENT |
| official_q5_city_vs_highway | 6.22 | 6.84 | 10 | MEASUREMENT |
| model_free_answer | 267.02 | 281.28 | 10 | MEASUREMENT |

## Answer checks for the timed queries

| query | retrieval | validation | evidence | ms |
|---|---|---|---|---|
| official_q1_range_reduction | ok | pass | 31 | 242.89 |
| official_q2_efficiency_drop | ok | pass | 5 | 0.61 |
| official_q3_adas_events | ok | pass | 4 | 0.33 |
| official_q4_before_warning | ok | pass | 12 | 7.03 |
| official_q5_city_vs_highway | ok | pass | 12 | 0.73 |

## Labels

- **OFFICIAL CONSTRAINT:** < 2 s (case brief); RAM ~2 GB, ~2 ARM cores (case brief); history several weeks (case brief)
- **ENGINEERING TARGET:** fast path 200 ms; end-to-end 2000 ms
- **MEASUREMENT:** every number in the latency and memory tables above.
- **VERIFIED ON TARGET HARDWARE:** NO - no automotive/ARM target used in this environment
