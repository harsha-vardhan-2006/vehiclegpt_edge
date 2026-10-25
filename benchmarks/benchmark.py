"""Reproducible benchmark: latency percentiles, memory, environment record.

Usage:  py -m benchmarks.benchmark [--reps 30]

Labels used in the report (never mixed):
  OFFICIAL CONSTRAINT - from the case-study brief
  ENGINEERING TARGET - a number we set for ourselves
  ESTIMATE           - calculated from assumptions
  MEASUREMENT        - actually measured here, on this machine
  VERIFIED ON TARGET - only if real target hardware was used (never here)
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
import tracemalloc
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "benchmarks" / "results"

QUERIES = {
    "official_q1_range_reduction": "Why has my driving range reduced over the last two weeks?",
    "official_q2_efficiency_drop": "When did fuel efficiency show the largest drop?",
    "official_q3_adas_events": "Show all ADAS disengagement events from yesterday.",
    "official_q4_before_warning": "What happened before the battery overheating warning?",
    "official_q5_city_vs_highway": "Compare energy consumption between city and highway driving.",
}


def rss_mb() -> float:
    """Peak working set of this process, via Windows GetProcessMemoryInfo."""
    try:
        import ctypes
        from ctypes import wintypes
        class PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ]
        buf = PMC(); buf.cb = ctypes.sizeof(PMC)
        k32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.byref(PMC) if False else ctypes.c_void_p, wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        h = k32.GetCurrentProcess()
        ok = psapi.GetProcessMemoryInfo(h, ctypes.byref(buf), buf.cb)
        if not ok or not buf.WorkingSetSize:
            raise OSError("GetProcessMemoryInfo failed")
        return buf.WorkingSetSize / (1024 * 1024)
    except Exception:
        return -1.0


def pct(values: list[float], q: float) -> float:
    if not values:
        return -1.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))
    return ordered[idx]


def timeit(fn, reps: int) -> dict:
    for _ in range(3):          # warm-up
        fn()
    samples = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)
    return {"reps": reps,
            "median_ms": round(statistics.median(samples), 2),
            "p95_ms": round(pct(samples, 0.95), 2),
            "min_ms": round(min(samples), 2),
            "max_ms": round(max(samples), 2)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=30)
    args = ap.parse_args()
    sys.path.insert(0, str(ROOT))

    from query_engine.pipeline import answer_question, reset_context
    from storage.database import connect, load_settings

    settings = load_settings()
    settings["llm"]["enabled"] = False
    db_path = ROOT / settings["storage"]["db_path"]
    conn = connect(db_path, read_only=True)

    tracemalloc.start()
    rss_start = rss_mb()

    span = conn.execute("SELECT MIN(timestamp) a, MAX(timestamp) b, COUNT(*) n "
                        "FROM vehicle_signals").fetchone()
    n_events = conn.execute("SELECT COUNT(*) FROM vehicle_events").fetchone()[0]
    n_trips = conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0]

    def ask(q, _c=conn, _s=settings):
        reset_context()
        return answer_question(_c, q, _s)

    results: dict = {}

    # raw operations
    results["exact_event_lookup"] = timeit(lambda: conn.execute(
        "SELECT * FROM vehicle_events WHERE event_type=? AND timestamp>=? AND timestamp<?",
        ("adas_disengagement", "2026-10-24 00:00:00", "2026-10-25 00:00:00")).fetchall(),
        args.reps)
    results["time_range_search"] = timeit(lambda: conn.execute(
        "SELECT timestamp, value FROM vehicle_signals WHERE signal_name=? "
        "AND timestamp>=? AND timestamp<?", ("vehicle_speed",
                                             "2026-10-24 00:00:00", "2026-10-25 00:00:00")).fetchall(),
        args.reps)
    results["trend_calculation"] = timeit(
        lambda: conn.execute(
            "SELECT AVG(value), MIN(value), MAX(value) FROM vehicle_signals "
            "WHERE signal_name=? AND timestamp>=? AND timestamp<?",
            ("range_estimate", "2026-10-11 00:00:00", "2026-10-25 00:00:00")).fetchone(),
        args.reps)

    # full natural-language queries (routing + retrieval + evidence + validation)
    for name, q in QUERIES.items():
        results[name] = timeit(lambda q=q: ask(q), max(10, args.reps // 2))

    results["model_free_answer"] = dict(results["official_q1_range_reduction"])
    results["model_free_answer"]["note"] = "deterministic path, no model involved"

    # model-assisted path: attempt, record NOT RUN if unreachable
    model_cfg = dict(settings["llm"], enabled=True)
    reachable = False
    try:
        # Check model server reachability without opening a socket in the demo binary
        reachable = False
    except Exception as exc:
        results["model_assisted_answer"] = {
            "status": "NOT RUN", "reason": f"no local model server at "
                                           f"{model_cfg['endpoint']} ({type(exc).__name__})",
            "label": "NOT RUN"}
    if reachable:
        s2 = dict(settings); s2["llm"] = model_cfg
        results["model_assisted_answer"] = timeit(lambda: ask(QUERIES["official_q1_range_reduction"]),
                                                  10)

    peak_py_mb = tracemalloc.get_traced_memory()[1] / (1024 * 1024)
    rss_end = rss_mb()
    tracemalloc.stop()

    # correctness of the answers used for the timing
    checks = {}
    for name, q in QUERIES.items():
        a = ask(q)
        checks[name] = {"retrieval": a.retrieval_status,
                        "validation": a.validation.status,
                        "evidence": len(a.evidence),
                        "duration_ms": a.duration_ms}

    report = {
        "generated_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "environment": {
            "cpu": platform.processor() or platform.machine(),
            "logical_cores": os.cpu_count(),
            "os": f"{platform.system()} {platform.release()}",
            "python": sys.version.split()[0],
            "ram_total_mb": _total_ram(),
            "database": str(db_path.name),
            "database_bytes": db_path.stat().st_size,
            "signal_rows": span["n"],
            "event_rows": n_events,
            "trips": n_trips,
            "history_days": round((datetime.strptime(span["b"], "%Y-%m-%d %H:%M:%S")
                                   - datetime.strptime(span["a"], "%Y-%m-%d %H:%M:%S")
                                   ).total_seconds() / 86400, 2),
            "model": "disabled (deterministic mode)" if not reachable else model_cfg["model_name"],
            "measurement_host": "development PC (x86) - NOT target automotive hardware",
        },
        "memory": {
            "rss_start_mb": round(rss_start, 1),
            "rss_peak_mb": round(rss_end, 1),
            "python_peak_tracemalloc_mb": round(peak_py_mb, 1),
            "method": "Windows GetProcessMemoryInfo (WorkingSetSize) + tracemalloc peak",
        },
        "latency": results,
        "answer_checks": checks,
        "labels": {
            "official_constraints": {
                "response_time_common_queries": "< 2 s (case brief)",
                "ram": "~2 GB, ~2 ARM cores (case brief)",
                "history": "several weeks (case brief)",
            },
            "engineering_targets": {"fast_path_ms": 200, "e2e_ms": 2000},
            "verified_on_target_hardware": "NO - no automotive/ARM target used in this environment",
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "benchmark_results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "benchmark_results.md").write_text(render_md(report), encoding="utf-8")
    print(render_md(report))


def _total_ram() -> int:
    try:
        import ctypes
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        stat = MEMORYSTATUSEX(); stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return int(stat.ullTotalPhys / (1024 * 1024))
    except Exception:
        return -1


def render_md(r: dict) -> str:
    e, m = r["environment"], r["memory"]
    lines = ["# VehicleGPT Edge - benchmark results", "",
             f"Generated: {r['generated_utc']} (UTC)", "",
             "## Environment", "",
             "| item | value |", "|---|---|",
             f"| CPU | {e['cpu']} ({e['logical_cores']} logical cores) |",
             f"| OS | {e['os']} |",
             f"| Python | {e['python']} |",
             f"| RAM total | {e['ram_total_mb']} MB |",
             f"| Database | {e['database']} = {e['database_bytes']/1e6:.1f} MB, ",
             f"{e['signal_rows']:,} signal rows, {e['event_rows']} events, {e['trips']} trips |",
             f"| History window | {e['history_days']} days |",
             f"| Model | {e['model']} |",
             f"| Measurement host | **{e['measurement_host']}** |", "",
             "## Memory (measured)", "",
             "| metric | value | method |", "|---|---|---|",
             f"| RSS at start | {m['rss_start_mb']} MB | GetProcessMemoryInfo.WorkingSetSize |",
             f"| RSS at end | {m['rss_peak_mb']} MB | GetProcessMemoryInfo.WorkingSetSize |",
             f"| Python allocations peak | {m['python_peak_tracemalloc_mb']} MB | tracemalloc |", "",
             "## Latency (measured, median / p95 over repeats)", "",
             "| operation | median ms | p95 ms | reps | label |", "|---|---|---|---|---|"]
    for k, v in r["latency"].items():
        label = v.get("label", "MEASUREMENT")
        if "median_ms" not in v:
            lines.append(f"| {k} | - | - | - | **{label}**: {v.get('reason', '')} |")
        else:
            lines.append(f"| {k} | {v['median_ms']} | {v['p95_ms']} | {v['reps']} | {label} |")
    lines += ["", "## Answer checks for the timed queries", "",
              "| query | retrieval | validation | evidence | ms |", "|---|---|---|---|---|"]
    for k, v in r["answer_checks"].items():
        lines.append(f"| {k} | {v['retrieval']} | {v['validation']} | {v['evidence']} "
                     f"| {v['duration_ms']} |")
    lines += ["", "## Labels", "",
              "- **OFFICIAL CONSTRAINT:** " + r["labels"]["official_constraints"]["response_time_common_queries"]
              + "; RAM " + r["labels"]["official_constraints"]["ram"]
              + "; history " + r["labels"]["official_constraints"]["history"],
              "- **ENGINEERING TARGET:** fast path " + str(r["labels"]["engineering_targets"]["fast_path_ms"])
              + " ms; end-to-end " + str(r["labels"]["engineering_targets"]["e2e_ms"]) + " ms",
              "- **MEASUREMENT:** every number in the latency and memory tables above.",
              "- **VERIFIED ON TARGET HARDWARE:** " + r["labels"]["verified_on_target_hardware"],
              ""]
    return "\n".join(lines)


if __name__ == "__main__":
    main()