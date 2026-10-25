"""Deterministic retrieval: each intent category has a predefined query plan.

Every plan returns evidence records that the answer validator can re-check.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from analytics import anomalies, temporal, trends
from query_engine import sql_templates
from storage.database import fmt, parse

SQL_DESC = {
    "signal_range_q": "SELECT ... FROM vehicle_signals WHERE signal_name=? AND timestamp range",
    "signal_aggregate_q": "AVG/MIN/MAX/COUNT over vehicle_signals (quality filtered)",
    "events_in_window": "SELECT ... FROM vehicle_events WHERE timestamp range AND event_type",
    "events_any_window": "SELECT ... FROM vehicle_events WHERE timestamp range",
    "trips_in_window": "SELECT ... FROM trips WHERE start_time range",
    "quality_counts": "GROUP BY quality_status over vehicle_signals in window",
}


class _Ev:
    n = 0

    @classmethod
    def make(cls, kind, reference, produced_by, *, value=None, unit=None, text=None,
             ts=None, start=None, end=None, source="sqlite/vehicle_signals",
             quality="good", maturity="simulated"):
        cls.n += 1
        return {
            "evidence_id": f"E{cls.n}", "kind": kind, "reference": reference,
            "time_start": start, "time_end": end, "timestamp": ts, "value": value,
            "unit": unit, "text": text, "source": source, "quality_status": quality,
            "data_maturity": maturity, "produced_by": produced_by,
        }


def reset_ids() -> None:
    _Ev.n = 0


def _agg(conn, signal, start, end, evidence_out, label=None):
    rows = sql_templates.run(conn, "signal_aggregate_q",
                             {"name": signal, "start": start, "end": end})
    r = rows[0]
    if not r or not r["n"]:
        return None
    out = {"n": r["n"], "mean": r["avg_v"], "min": r["min_v"], "max": r["max_v"],
           "unit": r["unit"]}
    for key in ("mean", "min", "max"):
        evidence_out.append(_Ev.make(
            "aggregate", f"{label or signal}:{key}", SQL_DESC["signal_aggregate_q"],
            value=round(out[key], 3), unit=out["unit"], start=start, end=end))
    evidence_out.append(_Ev.make(
        "aggregate", f"{label or signal}:n", SQL_DESC["signal_aggregate_q"],
        value=float(out["n"]), unit="samples", start=start, end=end))
    return out


def _pct(a, b):
    return (b - a) / abs(a) * 100.0 if a else 0.0


def _num(x, dp=1):
    if x is None:
        return "n/a"
    return f"{x:.{dp}f}" if abs(x - round(x)) > 1e-9 else f"{int(round(x))}"


# ---------------------------------------------------------------- categories
def trend_range(conn, intent, settings) -> dict:
    ents = intent.entities
    start, end = parse(ents["start"]), parse(ents["end"])
    days = ents.get("lookback_days", 14)
    prev_end, prev_start = start, start - (end - start)
    ev = []

    rng_w = _agg(conn, "range_estimate", ents["start"], ents["end"], ev, "range:window")
    rng_p = _agg(conn, "range_estimate", fmt(prev_start), fmt(prev_end), ev, "range:previous")
    con_w = _agg(conn, "consumption_running", ents["start"], ents["end"], ev, "consumption:window")
    con_p = _agg(conn, "consumption_running", fmt(prev_start), fmt(prev_end), ev, "consumption:previous")
    soc_w = _agg(conn, "soc", ents["start"], ents["end"], ev, "soc:window")
    soc_p = _agg(conn, "soc", fmt(prev_start), fmt(prev_end), ev, "soc:previous")

    ev.append(_Ev.make("parameter", "window_days", "intent_router.lookback",
                       value=float(days), unit="days", start=ents["start"], end=ents["end"]))
    ev.append(_Ev.make("parameter", "previous_window_days", "intent_router.lookback",
                       value=float(days), unit="days", start=fmt(prev_start), end=fmt(prev_end)))

    if not (rng_w and rng_p and con_w and con_p):
        return {"status": "empty", "evidence": ev, "answer": None,
                "limitations": ["Insufficient samples in the requested window to compute a trend."]}

    # usable capacity estimate = mean range / (mean soc as fraction)
    cap_w = rng_w["mean"] / (soc_w["mean"] / 100.0) if soc_w and soc_w["mean"] else None
    cap_p = rng_p["mean"] / (soc_p["mean"] / 100.0) if soc_p and soc_p["mean"] else None
    for name, val in (("usable_capacity:window", cap_w), ("usable_capacity:previous", cap_p)):
        if val:
            ev.append(_Ev.make("aggregate", name,
                               "calculation: AVG(range_estimate) / (AVG(soc)/100)",
                               value=round(val, 2), unit="kWh", start=ents["start"], end=ents["end"]))

    d_rng = _pct(rng_p["mean"], rng_w["mean"])
    d_con = _pct(con_p["mean"], con_w["mean"])
    d_cap = _pct(cap_p, cap_w) if (cap_w and cap_p) else None
    for name, val in (("range_change_pct", d_rng), ("consumption_change_pct", d_con),
                      ("capacity_change_pct", d_cap)):
        if val is not None:
            ev.append(_Ev.make("aggregate", name, "calculation: (window - previous)/|previous|*100",
                               value=round(val, 2), unit="%", start=ents["start"], end=ents["end"]))

    facts = [f"mean estimated range {_num(rng_p['mean'])} → {_num(rng_w['mean'])} km ({d_rng:+.1f}%)",
             f"mean consumption {_num(con_p['mean'], 0)} → {_num(con_w['mean'], 0)} Wh/km ({d_con:+.1f}%)"]
    if d_cap is not None:
        facts.append(f"estimated usable capacity {_num(cap_p, 1)} → {_num(cap_w, 1)} kWh ({d_cap:+.1f}%)")
    verb = "decreased" if d_rng < -0.05 else ("increased" if d_rng > 0.05 else "was flat")
    answer = ("Over the last {d} days the vehicle's estimated range {verb}: {f}. "
              "These measurements are associated with the range change "
              "(association, not a proven single cause). Data source: synthetic/simulated vehicle data."
              ).format(d=days, verb=verb, f="; ".join(facts))

    gaps = anomalies.missing_windows(conn, "vehicle_speed", start, end, 300)
    limits = ["All data in this answer is synthetic (simulated), not a real vehicle measurement."]
    if gaps:
        limits.append(f"Data gaps detected in the window: {len(gaps)} gap(s) totalling "
                      f"{sum(g['seconds'] for g in gaps)} s; trend computed on available samples only.")
    return {"status": "ok", "evidence": ev, "answer": answer, "limitations": limits,
            "context": {"signal": "range_estimate", "start": ents["start"], "end": ents["end"]}}


def anomaly_explanation(conn, intent, settings) -> dict:
    ents = intent.entities
    start, end = parse(ents["start"]), parse(ents["end"])
    ev = []
    series = trends.daily_efficiency(conn, start, end)
    if len(series) < 3:
        return {"status": "empty", "evidence": ev, "answer": None,
                "limitations": ["Not enough trips in the window to compare efficiency."]}
    worst = trends.largest_daily_efficiency_drop(series)
    for s in (worst["from_date"], worst["to_date"]):
        row = next(x for x in series if x["date"] == s)
        ev.append(_Ev.make("aggregate", f"efficiency:{s}", "AVG(energy_used*1000/distance) per day",
                           value=round(row["whkm"], 2), unit="Wh/km",
                           start=f"{s} 00:00:00", end=f"{s} 23:59:59"))
        ev.append(_Ev.make("aggregate", f"trips:{s}", "COUNT(*) trips that day",
                           value=float(row["trips"]), unit="trips",
                           start=f"{s} 00:00:00", end=f"{s} 23:59:59"))
    ev.append(_Ev.make("aggregate", "efficiency_drop_pct", "(to-from)/from*100",
                       value=round(worst["pct"], 2), unit="%",
                       start=f"{worst['from_date']} 00:00:00",
                       end=f"{worst['to_date']} 23:59:59"))
    answer = ("The largest day-over-day efficiency drop in this window was on {to}: "
              "{a} → {b} Wh/km ({p:+.1f}%, {n} trips that day), up from {c} Wh/km on {from_d}. "
              "Data source: synthetic/simulated."
              ).format(to=worst["to_date"], a=_num(worst["from_whkm"], 0),
                       b=_num(worst["to_whkm"], 0), p=worst["pct"],
                       n=int(next(x for x in series if x['date'] == worst['to_date'])["trips"]),
                       c=_num(worst["from_whkm"], 0), from_d=worst["from_date"])
    return {"status": "ok", "evidence": ev, "answer": answer,
            "limitations": ["Synthetic data; efficiency is computed from trip distance and energy, not measured at the wheel."],
            "context": {"metric": "efficiency", "start": ents["start"], "end": ents["end"]}}


def event_history(conn, intent, settings) -> dict:
    ents = intent.entities
    q = intent.question.lower()
    etype = ("adas_disengagement" if ("adas" in q or "disengag" in q) else
             "battery_overtemp_warning" if ("battery" in q or "overheat" in q) else
             "diagnostic_trouble_code" if ("dtc" in q or "diagnostic" in q) else None)
    params = {"start": ents["start"], "end": ents["end"]}
    sql_name = "events_in_window" if etype else "events_any_window"
    if etype:
        params["etype"] = etype
    rows = sql_templates.run(conn, sql_name, params)
    ev = []
    for r in rows:
        ev.append(_Ev.make("event", f"event:{r['id']}", SQL_DESC[sql_name],
                           text=f"{r['event_type']} ({r['severity']}) - {r['description']}",
                           ts=r["timestamp"], source=f"vehicle_events#{r['id']}",
                           maturity=r["data_maturity"]))
    ev.append(_Ev.make("parameter", "matching_event_count", "COUNT(*) over events_in_window",
                       value=float(len(rows)), unit="events",
                       start=ents["start"], end=ents["end"]))
    label = etype or "all"
    if not rows:
        return {"status": "empty", "evidence": ev, "answer": None,
                "limitations": [f"No {label} events found between {ents['start']} and {ents['end']} "
                                f"(searched the full requested window; nothing is invented)."]}
    lines = "\n".join(f"- {r['timestamp']}  {r['event_type']} ({r['severity']}): {r['description']}"
                      for r in rows)
    answer = (f"Found {len(rows)} {label} event(s) between {ents['start']} and {ents['end']}:\n{lines}\n"
              f"Source: synthetic/simulated event log.")
    return {"status": "ok", "evidence": ev, "answer": answer,
            "limitations": ["Synthetic data (simulated maturity)."],
            "context": {"event_type": etype or "any", "start": ents["start"], "end": ents["end"]}}


def temporal_reconstruction(conn, intent, settings) -> dict:
    ents = intent.entities
    q = intent.question.lower()
    etype = "battery_overtemp_warning" if "battery" in q or "overheat" in q or "thermal" in q \
        else ("adas_disengagement" if "adas" in q else "battery_overtemp_warning")
    window_min = int(settings["query"]["prewarning_window_minutes"])
    end_ref = parse(ents["end"])
    ev = []
    target = temporal.first_event(conn, etype, parse(ents["start"]), end_ref)
    if not target:
        target = temporal.first_event(conn, etype)
    if not target:
        return {"status": "empty", "evidence": ev, "answer": None,
                "limitations": [f"No {etype} event exists in the dataset; nothing to reconstruct."]}
    when = parse(target["timestamp"])
    ev.append(_Ev.make("event", f"event:{target['id']}", "SELECT ... FROM vehicle_events ORDER BY timestamp LIMIT 1",
                       text=f"{target['event_type']} ({target['severity']})",
                       ts=target["timestamp"], source=f"vehicle_events#{target['id']}",
                       maturity="simulated"))
    ctx_start = when - timedelta(minutes=window_min)
    ev.append(_Ev.make("parameter", "context_window_minutes", "settings.query.prewarning_window_minutes",
                       value=float(window_min), unit="minutes",
                       start=fmt(ctx_start), end=target["timestamp"]))

    bt = temporal.signal_before(conn, "battery_temp", when, window_min)
    cp = temporal.signal_before(conn, "charging_power", when, window_min)
    at = temporal.signal_before(conn, "ambient_temp", when, window_min)
    for name, res in (("battery_temp", bt), ("charging_power", cp), ("ambient_temp", at)):
        if res["n"]:
            ev.append(_Ev.make("aggregate", f"{name}:max", "MAX(value) in pre-window",
                               value=round(res["max"], 2), unit=res["unit"],
                               start=res["start"], end=res["end"]))
            ev.append(_Ev.make("aggregate", f"{name}:first", "first sample in pre-window",
                               value=round(res["first"], 2), unit=res["unit"],
                               start=res["start"], end=res["end"]))
            ev.append(_Ev.make("aggregate", f"{name}:last", "last sample in pre-window",
                               value=round(res["last"], 2), unit=res["unit"],
                               start=res["start"], end=res["end"]))
    others = temporal.events_between(conn, ctx_start, when)
    ev.append(_Ev.make("parameter", "events_in_pre_window", "COUNT(events in window)",
                       value=float(len(others)), unit="events",
                       start=fmt(ctx_start), end=target["timestamp"]))

    facts = []
    if bt["n"]:
        facts.append(f"battery temperature {_num(bt['first'])} → {_num(bt['last'])} °C "
                     f"(max {_num(bt['max'])} °C)")
    if cp["n"] and cp["max"] > 0:
        facts.append(f"DC charging active up to {_num(cp['max'], 0)} kW")
    if at["n"]:
        facts.append(f"ambient temperature {_num(at['first'])} °C")
    if not facts:
        facts.append("no samples in the pre-window (see limitations)")
    answer = (f"In the {window_min} minutes before the {etype.replace('_', ' ')} at "
              f"{target['timestamp']}: {'; '.join(facts)}; {len(others)} other event(s) recorded. "
              f"These are associated preceding conditions, not a proven cause. Data: synthetic/simulated.")
    limits = ["Synthetic data.", "Correlation only: the system does not claim these conditions caused the warning."]
    if not bt["n"]:
        limits.append("battery_temp has no samples in the pre-window (missing data, not zero).")
    return {"status": "ok", "evidence": ev, "answer": answer, "limitations": limits,
            "context": {"event_type": etype, "start": fmt(ctx_start), "end": target["timestamp"]}}


def comparison(conn, intent, settings) -> dict:
    ents = intent.entities
    ev = []
    rows = sql_templates.run(conn, "trips_by_road", {"start": ents["start"], "end": ents["end"]})
    agg = {}
    for r in rows:
        if r["km"]:
            whkm = r["kwh"] * 1000.0 / r["km"]
            agg[r["road_type"]] = {"km": r["km"], "trips": r["trips"], "whkm": whkm}
            ev.append(_Ev.make("aggregate", f"{r['road_type']}:whkm",
                               "SUM(energy_used)*1000/SUM(distance) over trips",
                               value=round(whkm, 2), unit="Wh/km",
                               start=ents["start"], end=ents["end"]))
            ev.append(_Ev.make("aggregate", f"{r['road_type']}:km",
                               "SUM(distance) over trips", value=round(r["km"], 2), unit="km",
                               start=ents["start"], end=ents["end"]))
            ev.append(_Ev.make("aggregate", f"{r['road_type']}:trips",
                               "COUNT(*) trips", value=float(r["trips"]), unit="trips",
                               start=ents["start"], end=ents["end"]))
    if "city" not in agg or "highway" not in agg:
        return {"status": "empty", "evidence": ev, "answer": None,
                "limitations": [f"Need both city and highway trips in the window; found: "
                                f"{', '.join(sorted(agg)) or 'none'}."]}
    diff = agg["highway"]["whkm"] - agg["city"]["whkm"]
    pct = diff / agg["city"]["whkm"] * 100.0
    ev.append(_Ev.make("aggregate", "highway_minus_city", "whkm(highway) - whkm(city)",
                       value=round(diff, 2), unit="Wh/km", start=ents["start"], end=ents["end"]))
    ev.append(_Ev.make("aggregate", "highway_vs_city_pct", "diff/whkm(city)*100",
                       value=round(pct, 2), unit="%", start=ents["start"], end=ents["end"]))
    total_trips = int(agg["city"]["trips"] + agg["highway"]["trips"])
    ev.append(_Ev.make("aggregate", "city_plus_highway_trips",
                       "COUNT(city trips) + COUNT(highway trips)",
                       value=float(total_trips), unit="trips",
                       start=ents["start"], end=ents["end"]))
    answer = (f"Across {total_trips} trips in the window: "
              f"city driving averaged {_num(agg['city']['whkm'], 0)} Wh/km over {_num(agg['city']['km'])} km, "
              f"highway {_num(agg['highway']['whkm'], 0)} Wh/km over {_num(agg['highway']['km'])} km - "
              f"highway used {pct:.1f}% more energy per kilometre ({diff:+.0f} Wh/km). "
              f"Data: synthetic/simulated.")
    return {"status": "ok", "evidence": ev, "answer": answer,
            "limitations": ["Synthetic data.", "Mixed-road trips are excluded from both groups."],
            "context": {"metric": "road_comparison", "start": ents["start"], "end": ents["end"]}}


def missing_data_investigation(conn, intent, settings) -> dict:
    ents = intent.entities
    ev = []
    counts = sql_templates.run(conn, "quality_counts", {"start": ents["start"], "end": ents["end"]})
    total_bad = 0
    for c in counts:
        ev.append(_Ev.make("aggregate", f"quality:{c['quality_status']}", SQL_DESC["quality_counts"],
                           value=float(c["n"]), unit="samples",
                           start=ents["start"], end=ents["end"]))
        if c["quality_status"] != "good":
            total_bad += c["n"]
    gaps = anomalies.missing_windows(conn, "vehicle_speed", parse(ents["start"]),
                                     parse(ents["end"]), 300)
    ev.append(_Ev.make("parameter", "gap_count", "missing_windows(threshold=300 s)",
                       value=float(len(gaps)), unit="gaps",
                       start=ents["start"], end=ents["end"]))
    ev.append(_Ev.make("parameter", "gap_threshold_s", "settings: expected sample spacing",
                       value=300.0, unit="s",
                       start=ents["start"], end=ents["end"]))
    ev.append(_Ev.make("parameter", "non_good_sample_count", "SUM over non-good quality_status",
                       value=float(total_bad), unit="samples",
                       start=ents["start"], end=ents["end"]))
    if gaps:
        ev.append(_Ev.make("aggregate", "largest_gap_seconds", "max gap seconds",
                           value=float(max(g["seconds"] for g in gaps)), unit="s",
                           start=gaps[0]["from"], end=gaps[0]["to"]))
    answer = (f"Between {ents['start']} and {ents['end']}: {total_bad} sample(s) carry a non-good "
              f"quality flag and {len(gaps)} gap(s) were detected"
              + (f", largest {max(g['seconds'] for g in gaps)} s" if gaps else "") +
              ". Missing samples are stored as gaps/NULL, never as zero. Data: synthetic/simulated.")
    return {"status": "ok", "evidence": ev, "answer": answer,
            "limitations": ["Synthetic data.",
                            "Gap detection uses a 900 s threshold for the vehicle_speed signal."],
            "context": {"metric": "quality", "start": ents["start"], "end": ents["end"]}}


def exact_lookup(conn, intent, settings) -> dict:
    ents = intent.entities
    q = intent.question.lower()
    signal = next((s for s in ("range_estimate", "soc", "vehicle_speed", "battery_temp",
                               "ambient_temp", "consumption_running") if s in q), "vehicle_speed")
    if "range" in q:
        signal = "range_estimate"
    elif "speed" in q:
        signal = "vehicle_speed"
    elif "temperature" in q and "battery" in q:
        signal = "battery_temp"
    elif "temperature" in q:
        signal = "ambient_temp"
    row = conn.execute(
        "SELECT timestamp, value, unit, quality_status, source, data_maturity, id "
        "FROM vehicle_signals WHERE signal_name=? AND value IS NOT NULL "
        "AND timestamp<? ORDER BY timestamp DESC LIMIT 1",
        (signal, ents["end"])).fetchone()
    ev = []
    if not row:
        return {"status": "empty", "evidence": ev, "answer": None,
                "limitations": [f"No samples found for {signal} in the requested window."]}
    ev.append(_Ev.make("signal", f"{signal}@latest", "ORDER BY timestamp DESC LIMIT 1",
                       value=round(row["value"], 3), unit=row["unit"], ts=row["timestamp"],
                       source=f"vehicle_signals#{row['id']}", quality=row["quality_status"],
                       maturity=row["data_maturity"]))
    answer = (f"Latest {signal.replace('_', ' ')} = {_num(row['value'], 2)} {row['unit']} "
              f"at {row['timestamp']} (synthetic/simulated data).")
    return {"status": "ok", "evidence": ev, "answer": answer,
            "limitations": ["Synthetic data."],
            "context": {"signal": signal, "end": ents["end"]}}


def unsupported(conn, intent, settings) -> dict:
    return {"status": "unsupported", "evidence": [], "answer": None,
            "limitations": ["This question is outside the supported categories "
                            "(lookup, events, trends, comparison, temporal context, missing data). "
                            "No answer is generated rather than guessing."]}


def ambiguous(conn, intent, settings) -> dict:
    return {"status": "ambiguous", "evidence": [], "answer": None,
            "limitations": ["The question is too short or missing a time anchor. "
                            "Please add a period, e.g. 'over the last two weeks' or 'yesterday'."]}


def evidence_request(conn, intent, settings, context=None):
    """Return the evidence of the previous answer (conversation context)."""
    if not context or not context.get("evidence"):
        return {"status": "empty", "evidence": [], "answer": None,
                "limitations": ["No previous answer in this session to show evidence for."]}
    ev = context["evidence"]
    lines = "\n".join(
        f"- [{e['evidence_id']}] {e['kind']} {e['reference']}: "
        f"{e['value'] if e['value'] is not None else e['text']} {e['unit'] or ''}"
        f"{' @ ' + e['timestamp'] if e.get('timestamp') else ''}" for e in ev)
    answer = f"Evidence for the previous answer ({len(ev)} records):\n{lines}"
    limits = ["Reuses the previous answer's evidence; nothing recomputed."]
    if any(e.get("data_maturity") == "simulated" for e in ev):
        limits.append("The evidence is synthetic/simulated data, not a real vehicle measurement.")
    return {"status": "ok", "evidence": ev, "answer": answer, "limitations": limits}


def compare_previous_period(conn, intent, settings, context=None):
    if not context or not context.get("start"):
        return unsupported(conn, intent, settings)
    start, end = parse(context["start"]), parse(context["end"])
    span = end - start
    ents = dict(intent.entities, start=fmt(start - span), end=fmt(start))
    intent2 = type(intent)(category="comparison", confidence="high", entities=ents,
                           question=intent.question)
    return comparison(conn, intent2, settings)


def change_start(conn, intent, settings, context=None):
    if not context or not context.get("start"):
        return unsupported(conn, intent, settings)
    start, end = parse(context["start"]), parse(context["end"])
    signal = context.get("signal", "range_estimate")
    ev = []
    series = trends.daily_mean(conn, signal, start, end)
    if len(series) < 3:
        return {"status": "empty", "evidence": ev, "answer": None,
                "limitations": ["Not enough daily samples to locate a change point."]}
    unit = (conn.execute("SELECT unit FROM signal_dictionary WHERE signal_name=?",
                         (signal,)).fetchone() or {"unit": ""})["unit"]
    cp = anomalies.change_point(series, "mean", min_pct=3.0)
    for s in series[:4]:
        ev.append(_Ev.make("aggregate", f"{signal}:{s['date']}", "daily AVG(value)",
                           value=round(s["mean"], 3), unit=unit,
                           start=f"{s['date']} 00:00:00", end=f"{s['date']} 23:59:59"))
    ev.append(_Ev.make("parameter", "change_threshold_pct", "anomalies.change_point(min_pct)",
                       value=3.0, unit="%", start=fmt(start), end=fmt(end)))
    if not cp:
        return {"status": "ok", "evidence": ev,
                "answer": f"No persistent change point ≥3% found in {signal} for the window.",
                "limitations": ["Synthetic data."]}
    ev.append(_Ev.make("aggregate", "change_pct", "(after-before)/before*100",
                       value=round(cp["pct"], 2), unit="%",
                       start=f"{cp['from_date']} 00:00:00",
                       end=f"{cp['to_date']} 23:59:59"))
    answer = (f"The level of {signal.replace('_', ' ')} first shifted by {cp['pct']:+.1f}% between "
              f"{cp['from_date']} ({_num(cp['from'], 1)}) and {cp['to_date']} ({_num(cp['to'], 1)}). "
              f"Change-point detection: first daily mean shift ≥3%. Data: synthetic/simulated.")
    return {"status": "ok", "evidence": ev, "answer": answer,
            "limitations": ["Synthetic data.", "A change point indicates a level shift, not a cause."]}


def contribution(conn, intent, settings, context=None):
    start = parse(context["start"]) if context and context.get("start") else \
        parse(intent.entities["start"])
    end = parse(context["end"]) if context and context.get("end") else parse(intent.entities["end"])
    rows = trends.trip_efficiency(conn, start, end)
    if not rows:
        return {"status": "empty", "evidence": [], "answer": None,
                "limitations": ["No trips in the window."]}
    baseline = sorted(r["whkm"] for r in rows)[len(rows) // 2]
    extra = [dict(r, excess=(r["whkm"] - baseline) * r["distance"] / 1000.0) for r in rows]
    extra.sort(key=lambda r: -r["excess"])
    top = extra[:3]
    ev = []
    for r in top:
        ev.append(_Ev.make("trip", f"trip:{r['trip_id']}", "energy_used*1000/distance per trip",
                           value=round(r["whkm"], 2), unit="Wh/km", ts=r["start_time"],
                           source=f"trips#{r['trip_id']}", maturity="simulated"))
        ev.append(_Ev.make("parameter", f"trip:{r['trip_id']}:id", "trips.trip_id",
                           value=float(r["trip_id"]), unit="trip_id", ts=r["start_time"],
                           source=f"trips#{r['trip_id']}", maturity="simulated"))
        ev.append(_Ev.make("parameter", f"trip:{r['trip_id']}:distance", "trips.distance",
                           value=round(r["distance"], 2), unit="km", ts=r["start_time"],
                           source=f"trips#{r['trip_id']}", maturity="simulated"))
        ev.append(_Ev.make("parameter", f"trip:{r['trip_id']}:excess",
                           "(whkm - median_baseline)/1000*distance",
                           value=round(r["excess"], 3), unit="kWh", ts=r["start_time"],
                           source=f"trips#{r['trip_id']}", maturity="simulated"))
    ev.append(_Ev.make("parameter", "median_baseline", "median trip efficiency",
                       value=round(baseline, 2), unit="Wh/km", start=fmt(start), end=fmt(end)))
    lines = "\n".join(
        f"- trip {r['trip_id']} on {r['start_time']} ({r['road_type']}): "
        f"{_num(r['whkm'], 0)} Wh/km, {r['distance']} km, {_num(r['excess'], 2)} kWh above median"
        for r in top)
    answer = (f"Trips contributing most to the energy difference in the window "
              f"(median baseline {_num(baseline, 0)} Wh/km):\n{lines}\nData: synthetic/simulated.")
    return {"status": "ok", "evidence": ev, "answer": answer,
            "limitations": ["Synthetic data.", "Contribution = excess energy vs the window median."],
            "context": {"metric": "contribution", "start": fmt(start), "end": fmt(end)}}


PLANS = {
    "trend_analysis": trend_range,
    "anomaly_explanation": anomaly_explanation,
    "event_history": event_history,
    "temporal_reconstruction": temporal_reconstruction,
    "comparison": comparison,
    "missing_data_investigation": missing_data_investigation,
    "exact_lookup": exact_lookup,
    "unsupported": unsupported,
    "ambiguous": ambiguous,
    "evidence_request": evidence_request,
    "compare_previous_period": compare_previous_period,
    "change_start": change_start,
    "contribution": contribution,
}
