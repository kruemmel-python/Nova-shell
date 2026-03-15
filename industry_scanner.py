"""
Generic industry/news scanner for Nova-shell + Atheria.

Supported inputs:
- INDUSTRY_SCAN_FILE=/path/to/local.json|.rss|.xml|.txt for local testing
- INDUSTRY_FEEDS=https://feed1,... for RSS/Atom feeds
- NEWSAPI_KEY plus optional INDUSTRY_NEWS_QUERY for NewsAPI.org
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


KEYWORDS = {
    "hyperbolic": ("hyperbolic", "poincare", "riemannian", "curvature"),
    "zero_copy": ("zero-copy", "zero copy", "shared memory", "arrow", "plasma"),
    "resonance": ("resonance", "invariant", "field", "harmonic", "coupling"),
    "mesh": ("mesh", "distributed worker", "cluster", "orchestrator", "scheduler"),
    "agent": ("agent", "planner", "tool graph", "workflow", "reviewer"),
    "runtime": ("runtime", "execution engine", "command graph", "pipeline"),
}


def _http_json(url: str, headers: dict[str, str] | None = None) -> Any:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_text(url: str, headers: dict[str, str] | None = None) -> str:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=20) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _load_local_scan_file(path: Path) -> list[dict[str, str]]:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".json":
        payload = json.loads(text)
        if isinstance(payload, list):
            return [
                {
                    "title": str(item.get("title") or ""),
                    "summary": str(item.get("summary") or item.get("description") or ""),
                    "source": str(item.get("source") or path.name),
                    "url": str(item.get("url") or ""),
                }
                for item in payload
                if isinstance(item, dict)
            ]
    if suffix in {".rss", ".xml"}:
        root = ET.fromstring(text)
        items: list[dict[str, str]] = []
        for item in root.findall(".//item")[:20] + root.findall(".//entry")[:20]:
            title = item.findtext("title") or ""
            summary = item.findtext("description") or item.findtext("summary") or ""
            link = item.findtext("link") or ""
            items.append({"title": title.strip(), "summary": summary.strip(), "source": path.name, "url": link.strip()})
        return items
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return [{"title": line, "summary": line, "source": path.name, "url": ""} for line in lines[:20]]


def _load_rss_feeds(feeds: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for feed in feeds[:10]:
        try:
            text = _http_text(feed)
            root = ET.fromstring(text)
        except Exception:
            continue
        for item in root.findall(".//item")[:10] + root.findall(".//entry")[:10]:
            title = item.findtext("title") or ""
            summary = item.findtext("description") or item.findtext("summary") or ""
            link = item.findtext("link") or ""
            rows.append({"title": title.strip(), "summary": summary.strip(), "source": feed, "url": link.strip()})
    return rows[:30]


def _load_newsapi_rows() -> list[dict[str, str]]:
    api_key = os.environ.get("NEWSAPI_KEY", "").strip()
    if not api_key:
        return []
    query = os.environ.get("INDUSTRY_NEWS_QUERY", "AI orchestration OR agent runtime OR distributed agents")
    url = "https://newsapi.org/v2/everything?" + urllib.parse.urlencode(
        {"q": query, "pageSize": 20, "sortBy": "publishedAt", "language": "en"}
    )
    try:
        payload = _http_json(url, headers={"X-Api-Key": api_key})
    except Exception:
        return []
    rows: list[dict[str, str]] = []
    for item in payload.get("articles", []):
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "title": str(item.get("title") or ""),
                "summary": str(item.get("description") or ""),
                "source": str((item.get("source") or {}).get("name") if isinstance(item.get("source"), dict) else ""),
                "url": str(item.get("url") or ""),
            }
        )
    return rows


def _collect_rows() -> list[dict[str, str]]:
    local_file = os.environ.get("INDUSTRY_SCAN_FILE", "").strip()
    if local_file:
        path = Path(os.path.expanduser(local_file))
        if path.exists():
            return _load_local_scan_file(path)
    feeds = [item.strip() for item in os.environ.get("INDUSTRY_FEEDS", "").split(",") if item.strip()]
    if feeds:
        rows = _load_rss_feeds(feeds)
        if rows:
            return rows
    rows = _load_newsapi_rows()
    if rows:
        return rows
    return []


def _score_keywords(text: str) -> dict[str, float]:
    lowered = text.lower()
    tokens = re.findall(r"[a-z0-9_\-]+", lowered)
    token_count = max(1, len(tokens))
    result: dict[str, float] = {}
    for key, values in KEYWORDS.items():
        matches = sum(lowered.count(item) for item in values)
        result[key] = round(min(1.0, matches / max(1.0, token_count * 0.08)), 6)
    return result


def analyze(_payload: Any) -> dict[str, Any]:
    rows = _collect_rows()
    joined = "\n".join(
        f"- {row['title']} :: {row['summary']}".strip()
        for row in rows[:12]
        if row.get("title") or row.get("summary")
    )
    keyword_scores = _score_keywords(joined)
    strongest = sorted(keyword_scores.items(), key=lambda item: item[1], reverse=True)[:3]
    summary = (
        "No industry updates found."
        if not rows
        else f"Scanned {len(rows)} industry items. Strongest resonance signals: "
        + ", ".join(f"{name}={value:.2f}" for name, value in strongest)
    )
    return {
        "summary": summary,
        "features": {
            "trauma_pressure": keyword_scores["hyperbolic"],
            "signal_strength": keyword_scores["resonance"],
            "system_temperature": min(1.0, len(rows) / 20.0),
            "resource_pressure": keyword_scores["mesh"],
            "entropic_index": keyword_scores["agent"],
            "structural_tension": keyword_scores["runtime"],
            "guardian_score": keyword_scores["zero_copy"],
            "holographic_energy": max(keyword_scores.values()) if keyword_scores else 0.0,
            "cpu_usage": keyword_scores["agent"],
            "memory_usage": keyword_scores["zero_copy"],
            "network_latency": keyword_scores["mesh"],
            "error_rate": 0.0,
            "queue_depth": min(1.0, len(rows) / 30.0),
            "anomaly_score": max(keyword_scores.values()) if keyword_scores else 0.0,
        },
        "metadata": {
            "items": rows[:12],
            "scanned_at": time.time(),
        },
    }
