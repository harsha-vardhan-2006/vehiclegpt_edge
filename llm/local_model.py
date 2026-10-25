"""Optional local SLM backends with graceful fallback.

Download is NEVER automatic. If no model/server is reachable, the deterministic
engine keeps answering - the application must not crash or block on the model.
"""
from __future__ import annotations

import json
import urllib.request

from llm import prompts

_cache: dict = {}


def _summary(evidence: list) -> list[str]:
    out = []
    for e in evidence[:12]:
        ref = getattr(e, "reference", None) or ""
        if isinstance(e, dict):
            ref = e.get("reference", "")
            val, unit, ts = e.get("value"), e.get("unit"), e.get("timestamp")
        else:
            val, unit, ts = e.value, e.unit, e.timestamp
        out.append(f"{ref}={val} {unit or ''} @{ts or ''}".strip())
    return out


def explain(answer_text: str, evidence: list, settings: dict) -> str | None:
    """Return a model-rephrased answer, or None to keep the deterministic text."""
    cfg = settings.get("llm", {})
    if not cfg.get("enabled") or cfg.get("mode") == "off":
        return None
    backend = cfg.get("backend", "off")
    try:
        if backend == "llama_server":
            return _call_openai_compatible(cfg, answer_text, evidence)
        if backend == "ollama":
            return _call_ollama(cfg, answer_text, evidence)
    except Exception as exc:            # network/model issues must never break queries
        _cache["last_error"] = f"{type(exc).__name__}: {exc}"
        return None
    return None


def _call_openai_compatible(cfg: dict, answer_text: str, evidence: list) -> str | None:
    payload = {
        "model": cfg.get("model_name", "local"),
        "messages": [{"role": "system", "content": prompts.SYSTEM_PROMPT},
                     {"role": "user", "content": prompts.build_user_prompt(
                         answer_text, _summary(evidence))}],
        "max_tokens": int(cfg.get("max_new_tokens", 200)),
        "temperature": 0.1,
        "stream": False,
    }
    req = urllib.request.Request(
        cfg["endpoint"].rstrip("/") + "/v1/chat/completions",
        data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=float(cfg.get("timeout_s", 20))) as resp:
        data = json.loads(resp.read().decode())
    text = data["choices"][0]["message"]["content"].strip()
    return text or None


def _call_ollama(cfg: dict, answer_text: str, evidence: list) -> str | None:
    payload = {
        "model": cfg.get("model_name", "qwen2.5:0.5b"),
        "messages": [{"role": "system", "content": prompts.SYSTEM_PROMPT},
                     {"role": "user", "content": prompts.build_user_prompt(
                         answer_text, _summary(evidence))}],
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": int(cfg.get("max_new_tokens", 200))},
    }
    req = urllib.request.Request(
        cfg.get("endpoint", "http://127.0.0.1:11434").rstrip("/") + "/api/chat",
        data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=float(cfg.get("timeout_s", 20))) as resp:
        data = json.loads(resp.read().decode())
    text = (data.get("message", {}).get("content") or "").strip()
    return text or None


def status(settings: dict) -> dict:
    cfg = settings.get("llm", {})
    return {"enabled": bool(cfg.get("enabled")), "backend": cfg.get("backend"),
            "endpoint": cfg.get("endpoint"), "model_name": cfg.get("model_name"),
            "last_error": _cache.get("last_error"),
            "note": "deterministic mode answers without any model"}
