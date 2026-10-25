# Adapter maturity matrix

| Adapter | Input | Dependencies | Permissions | Implemented | Test status | Limitations |
|---|---|---|---|---|---|---|
| `synthetic` | in-process generator | stdlib | none | YES | TESTED (pytest) | Data is simulated |
| `csv_log` (also handles `.jsonl` replay) | CSV/JSONL file under `./data/**` | stdlib | read, path-restricted | YES | TESTED (pytest) | Malformed lines rejected & counted; maturity = *replayed* |
| `socketcan` | Linux SocketCAN `can0` + DBC | `python-can`, Linux | read-only CAN access | NO (interface only) | NOT RUN — no SocketCAN / no authorised bus | No frame write path exists in the codebase |
| `someip` | SOME/IP services (vsomeip / SD) | vsomeip, ARXML schema | network member in the SD domain | NO — interface documented only | NOT RUN — no SOME/IP ECU available | Would be a thin adapter over the same normalizer |
| `android_vehicle_hal` | Android Vehicle HAL AIDL properties | Android build, `car_property_service` | Android car permissions | NO — interface documented only | NOT RUN — no Android Automotive target | Property IDs vehicle-specific |
| `qnx_logs` | QNX slog2 / infotainment logs | QNX target, log forwarder | read access on target | NO — interface documented only | NOT RUN — no QNX target | Log formats vary by program |
| `adas_camera_meta` | ROS 2 topics / event records | ROS 2, bag files | read on topic | NO — replayable via `csv_log` if exported | NOT RUN — no ROS 2 runtime here | Camera *video* is out of scope; metadata only |
| `diagnostics` | UDS/DTC records (ISO-14229) | DoIP/DoCAN tester stack | diagnostic session | NO — events simulated in generator | NOT RUN — no vehicle | Would emit `vehicle_events` rows |

**Rule applied:** an adapter interface is never reported as an implemented integration.
All adapters feed the *same* normalizer (`ingestion/normalizer.py`), so implementing one
later requires no changes to storage, analytics, query engine or UI.
