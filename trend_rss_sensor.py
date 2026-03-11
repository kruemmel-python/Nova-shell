"""
Self-learning RSS trend forecaster for Nova-shell + Atheria.

The sensor learns a rolling baseline from previous runs and predicts whether
the current information field is heating up, cooling down, or staying stable.

Inputs:
- payload as a list of {title, summary, source, url} objects
- payload as {"items": [...]} with the same structure
- INDUSTRY_SCAN_FILE for local json/rss/xml/text files
- INDUSTRY_FEEDS for live RSS/Atom feeds
- NEWSAPI_KEY plus optional INDUSTRY_NEWS_QUERY for NewsAPI.org

Persistent learning state:
- INDUSTRY_TREND_STATE=/path/to/state.json
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


KEYWORD_GROUPS = {
    "infrastructure": ("data center", "gpu", "chip", "rack", "power", "cooling", "capacity", "cluster"),
    "capital": ("funding", "investment", "capex", "billion", "valuation", "acquisition", "venture", "spend"),
    "agent_runtime": ("agent", "planner", "tool graph", "workflow", "runtime", "orchestrator", "automation"),
    "research": ("model", "benchmark", "training", "inference", "paper", "research", "weights", "reasoning"),
    "operations": ("latency", "deployment", "scale", "throughput", "uptime", "server", "network", "region"),
    "risk": ("shortage", "outage", "delay", "risk", "bottleneck", "sanction", "constraint", "export control"),
}

FEATURE_KEYS = (
    "trauma_pressure",
    "signal_strength",
    "system_temperature",
    "resource_pressure",
    "entropic_index",
    "structural_tension",
    "guardian_score",
    "holographic_energy",
    "cpu_usage",
    "memory_usage",
    "network_latency",
    "error_rate",
    "queue_depth",
    "anomaly_score",
)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _mean(values: list[float]) -> float:
    return sum(values) / max(1, len(values))


def _http_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "nova-shell-trend-sensor/0.8.3"})
    with urllib.request.urlopen(request, timeout=20) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _http_json(url: str, headers: dict[str, str] | None = None) -> Any:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _normalize_rows(payload: Any) -> list[dict[str, str]]:
    rows = payload.get("items", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "title": str(item.get("title") or ""),
                "summary": str(item.get("summary") or item.get("description") or ""),
                "source": str(item.get("source") or ""),
                "url": str(item.get("url") or ""),
            }
        )
    return normalized


def _load_local_scan_file(path: Path) -> list[dict[str, str]]:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".json":
        return _normalize_rows(json.loads(text))
    if suffix in {".rss", ".xml"}:
        root = ET.fromstring(text)
        rows: list[dict[str, str]] = []
        for item in root.findall(".//item")[:24] + root.findall(".//entry")[:24]:
            rows.append(
                {
                    "title": (item.findtext("title") or "").strip(),
                    "summary": (item.findtext("description") or item.findtext("summary") or "").strip(),
                    "source": path.name,
                    "url": (item.findtext("link") or "").strip(),
                }
            )
        return rows
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return [{"title": line, "summary": line, "source": path.name, "url": ""} for line in lines[:24]]


def _load_rss_feeds(feeds: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for feed in feeds[:10]:
        try:
            root = ET.fromstring(_http_text(feed))
        except Exception:
            continue
        for item in root.findall(".//item")[:12] + root.findall(".//entry")[:12]:
            rows.append(
                {
                    "title": (item.findtext("title") or "").strip(),
                    "summary": (item.findtext("description") or item.findtext("summary") or "").strip(),
                    "source": feed,
                    "url": (item.findtext("link") or "").strip(),
                }
            )
    return rows[:36]


def _load_newsapi_rows() -> list[dict[str, str]]:
    api_key = os.environ.get("NEWSAPI_KEY", "").strip()
    if not api_key:
        return []
    query = os.environ.get("INDUSTRY_NEWS_QUERY", "AI infrastructure OR agent runtime OR orchestration")
    url = "https://newsapi.org/v2/everything?" + urllib.parse.urlencode(
        {"q": query, "pageSize": 24, "sortBy": "publishedAt", "language": "en"}
    )
    try:
        payload = _http_json(url, headers={"X-Api-Key": api_key})
    except Exception:
        return []
    return _normalize_rows(payload.get("articles", []))


def _collect_rows(payload: Any) -> list[dict[str, str]]:
    direct_rows = _normalize_rows(payload)
    if direct_rows:
        return direct_rows
    local_file = os.environ.get("INDUSTRY_SCAN_FILE", "").strip()
    if local_file:
        candidate = Path(os.path.expanduser(local_file))
        if candidate.exists():
            return _load_local_scan_file(candidate)
    feeds = [item.strip() for item in os.environ.get("INDUSTRY_FEEDS", "").split(",") if item.strip()]
    if feeds:
        rows = _load_rss_feeds(feeds)
        if rows:
            return rows
    return _load_newsapi_rows()


def _score_groups(text: str) -> dict[str, float]:
    lowered = text.lower()
    tokens = re.findall(r"[a-z0-9_\-]+", lowered)
    token_count = max(1, len(tokens))
    scores: dict[str, float] = {}
    for name, keywords in KEYWORD_GROUPS.items():
        hits = sum(lowered.count(keyword) for keyword in keywords)
        scores[name] = _clamp(hits / max(1.0, token_count * 0.07))
    return scores


def _novelty_ratio(rows: list[dict[str, str]]) -> float:
    tokens: list[str] = []
    for row in rows[:24]:
        tokens.extend(re.findall(r"[a-z0-9_\-]+", f"{row['title']} {row['summary']}".lower()))
    if not tokens:
        return 0.0
    return _clamp(len(set(tokens)) / max(1, len(tokens)))


def _state_path() -> Path:
    env_value = os.environ.get("INDUSTRY_TREND_STATE", "").strip()
    if env_value:
        return Path(os.path.expanduser(env_value))
    return Path.home() / ".nova-shell" / "rss_trend_state.json"


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"history": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"history": []}
    if not isinstance(payload, dict) or not isinstance(payload.get("history"), list):
        return {"history": []}
    return payload


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["history"] = list(state.get("history", []))[-128:]
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def analyze(payload: Any) -> dict[str, Any]:
    rows = _collect_rows(payload)
    text = "\n".join(
        f"- {row['title']} :: {row['summary']}".strip()
        for row in rows[:24]
        if row.get("title") or row.get("summary")
    )
    group_scores = _score_groups(text)
    article_count_norm = _clamp(len(rows) / 24.0)
    source_diversity = _clamp(len({row["source"] for row in rows if row.get("source")}) / max(1, min(len(rows), 8)))
    novelty = _novelty_ratio(rows)

    current = {
        "trauma_pressure": _clamp(group_scores["capital"] * 0.5 + group_scores["risk"] * 0.5),
        "signal_strength": _clamp(article_count_norm * 0.55 + group_scores["agent_runtime"] * 0.45),
        "system_temperature": _clamp(article_count_norm * 0.4 + source_diversity * 0.25 + group_scores["research"] * 0.35),
        "resource_pressure": _clamp(group_scores["infrastructure"] * 0.7 + group_scores["operations"] * 0.3),
        "entropic_index": _clamp(novelty * 0.55 + group_scores["risk"] * 0.25 + source_diversity * 0.2),
        "structural_tension": _clamp(group_scores["agent_runtime"] * 0.5 + group_scores["infrastructure"] * 0.3 + group_scores["risk"] * 0.2),
        "guardian_score": _clamp(group_scores["operations"] * 0.5 + group_scores["risk"] * 0.5),
        "holographic_energy": 0.0,
        "cpu_usage": _clamp(group_scores["research"] * 0.4 + group_scores["agent_runtime"] * 0.6),
        "memory_usage": _clamp(group_scores["infrastructure"] * 0.4 + article_count_norm * 0.4 + group_scores["research"] * 0.2),
        "network_latency": _clamp(group_scores["operations"] * 0.6 + group_scores["risk"] * 0.4),
        "error_rate": _clamp(group_scores["risk"] * 0.7 + (1.0 - source_diversity) * 0.3),
        "queue_depth": article_count_norm,
        "anomaly_score": 0.0,
    }
    current["holographic_energy"] = max(current["signal_strength"], current["system_temperature"], current["resource_pressure"], current["structural_tension"])

    state_file = _state_path()
    state = _load_state(state_file)
    history = [item for item in state.get("history", []) if isinstance(item, dict)]
    window = history[-24:]
    baseline = {key: _mean([float(item.get(key, 0.0)) for item in window]) for key in FEATURE_KEYS} if window else {key: 0.0 for key in FEATURE_KEYS}
    deltas = {key: round(float(current[key]) - float(baseline[key]), 6) for key in FEATURE_KEYS}
    current["anomaly_score"] = _clamp(max(abs(value) for value in deltas.values()) * 1.6)

    if window:
        prev_trend = float(window[-1].get("trend_pressure", 0.0))
        trend_pressure = (
            deltas["signal_strength"] * 0.35
            + deltas["resource_pressure"] * 0.2
            + deltas["structural_tension"] * 0.2
            + deltas["entropic_index"] * 0.15
            + deltas["system_temperature"] * 0.1
        )
        acceleration = trend_pressure - prev_trend
        forecast_score = _clamp(0.5 + trend_pressure * 0.85 + acceleration * 0.45)
        if forecast_score >= 0.62:
            direction = "emerging_uptrend"
        elif forecast_score <= 0.38:
            direction = "cooling"
        else:
            direction = "stable_watch"
        confidence = _clamp(min(1.0, len(window) / 8.0) * 0.4 + abs(forecast_score - 0.5) * 1.5)
    else:
        trend_pressure = 0.0
        acceleration = 0.0
        forecast_score = 0.5
        direction = "warming_baseline"
        confidence = _clamp(0.1 + article_count_norm * 0.2, 0.0, 0.25)

    snapshot = {"timestamp": time.time(), "trend_pressure": round(trend_pressure, 6), "forecast_score": round(forecast_score, 6), **{key: round(float(current[key]), 6) for key in FEATURE_KEYS}}
    history.append(snapshot)
    state["history"] = history[-128:]
    _save_state(state_file, state)

    summary = (
        f"Trend forecast: {direction} "
        f"(forecast={forecast_score:.2f}, confidence={confidence:.2f}, "
        f"items={len(rows)}, signal_delta={deltas['signal_strength']:+.2f}, "
        f"resource_delta={deltas['resource_pressure']:+.2f})"
    )

    return {
        "summary": summary,
        "features": current,
        "metadata": {
            "items": rows[:12],
            "history_length": len(state["history"]),
            "forecast_direction": direction,
            "forecast_score": round(forecast_score, 6),
            "confidence": round(confidence, 6),
            "trend_pressure": round(trend_pressure, 6),
            "trend_acceleration": round(acceleration, 6),
            "baseline": baseline,
            "deltas": deltas,
            "state_file": str(state_file),
            "scanned_at": time.time(),
        },
    }
