from __future__ import annotations

import contextlib
import hashlib
import hmac
import html
import json
import os
import re
import socket
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterable

from .atheria_bridge import load_aion_chronik


KEYWORD_GROUPS: dict[str, tuple[str, ...]] = {
    "infrastructure": ("data center", "gpu", "chip", "cluster", "power", "cooling", "capacity", "rack"),
    "agents": ("agent", "runtime", "workflow", "orchestrator", "planner", "automation", "tool graph"),
    "research": ("model", "benchmark", "training", "inference", "paper", "reasoning", "weights"),
    "operations": ("latency", "deployment", "scale", "throughput", "uptime", "server", "network", "region"),
    "risk": ("shortage", "outage", "delay", "risk", "bottleneck", "constraint", "exploit", "incident"),
    "economics": ("funding", "investment", "valuation", "capex", "acquisition", "market", "spend"),
}

FEATURE_KEYS: tuple[str, ...] = (
    "signal_strength",
    "system_temperature",
    "resource_pressure",
    "structural_tension",
    "entropic_index",
    "anomaly_score",
    "trend_pressure",
    "trend_acceleration",
    "forecast_score",
    "confidence",
)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, _safe_float(value)))


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _mean(values: Iterable[float]) -> float:
    data = [float(item) for item in values]
    if not data:
        return 0.0
    return sum(data) / float(len(data))


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower())
    return normalized.strip("-") or "default"


def _ensure_text(value: Any) -> str:
    return str(value or "").strip()


def _tokenize(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9_\-\u00c0-\u024f]+", text.lower()) if token]


def _chunked_tail(path: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        with contextlib.suppress(json.JSONDecodeError):
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows[-max(1, int(limit)) :]


def _normalize_rows(payload: Any, *, source_hint: str = "") -> list[dict[str, str]]:
    rows = payload.get("items", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        title = _ensure_text(item.get("title"))
        summary = _ensure_text(item.get("summary") or item.get("description"))
        source = _ensure_text(item.get("source") or source_hint)
        url = _ensure_text(item.get("url") or item.get("link"))
        published_at = _ensure_text(item.get("published_at") or item.get("published") or item.get("updated"))
        if not any([title, summary, url]):
            continue
        normalized.append(
            {
                "title": title,
                "summary": summary,
                "source": source,
                "url": url,
                "published_at": published_at,
            }
        )
    return normalized


def _http_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "nova-shell-als/0.8.23"})
    with urllib.request.urlopen(request, timeout=20) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _parse_feed_xml(text: str, source: str) -> list[dict[str, str]]:
    root = ET.fromstring(text)
    rows: list[dict[str, str]] = []
    for item in root.findall(".//item")[:16] + root.findall(".//entry")[:16]:
        link_text = ""
        link_node = item.find("link")
        if link_node is not None:
            link_text = _ensure_text(link_node.text or link_node.attrib.get("href"))
        rows.append(
            {
                "title": _ensure_text(item.findtext("title")),
                "summary": _ensure_text(item.findtext("description") or item.findtext("summary")),
                "source": source,
                "url": link_text,
                "published_at": _ensure_text(
                    item.findtext("pubDate")
                    or item.findtext("updated")
                    or item.findtext("published")
                ),
            }
        )
    return [row for row in rows if any(row.values())]


def _normalize_search_result_url(url: str) -> str:
    cleaned = html.unescape(_ensure_text(url))
    if cleaned.startswith("//"):
        cleaned = "https:" + cleaned
    parsed = urllib.parse.urlparse(cleaned)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = urllib.parse.parse_qs(parsed.query).get("uddg", [])
        if target:
            cleaned = urllib.parse.unquote(target[0])
    return cleaned


class _DuckDuckGoSearchParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._capture_title = False
        self._capture_snippet_depth = 0

    def _commit_current(self) -> None:
        if not isinstance(self._current, dict):
            return
        title = re.sub(r"\s+", " ", self._current.get("title", "")).strip()
        summary = re.sub(r"\s+", " ", self._current.get("summary", "")).strip()
        url = _normalize_search_result_url(self._current.get("url", ""))
        if title and url:
            self.results.append(
                {
                    "title": title,
                    "summary": summary,
                    "url": url,
                }
            )
        self._current = None
        self._capture_title = False
        self._capture_snippet_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: (value or "") for key, value in attrs}
        classes = set(attr_map.get("class", "").split())
        href = attr_map.get("href", "")
        if tag == "a" and href and ("result__a" in classes or "result-link" in classes):
            self._commit_current()
            self._current = {"title": "", "summary": "", "url": href}
            self._capture_title = True
            return
        if self._current and tag in {"a", "div", "span"} and ("result__snippet" in classes or "result-snippet" in classes):
            self._capture_snippet_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._capture_title and tag == "a":
            self._capture_title = False
        if self._capture_snippet_depth and tag in {"a", "div", "span"}:
            self._capture_snippet_depth = max(0, self._capture_snippet_depth - 1)

    def handle_data(self, data: str) -> None:
        if not isinstance(self._current, dict):
            return
        if self._capture_title:
            self._current["title"] += data
        elif self._capture_snippet_depth:
            self._current["summary"] += data

    def close(self) -> None:
        super().close()
        self._commit_current()


def _score_groups(text: str) -> dict[str, float]:
    lowered = text.lower()
    tokens = _tokenize(lowered)
    token_count = max(1, len(tokens))
    scores: dict[str, float] = {}
    for name, keywords in KEYWORD_GROUPS.items():
        hits = sum(lowered.count(keyword) for keyword in keywords)
        scores[name] = _clamp(hits / max(1.0, token_count * 0.07))
    return scores


def _novelty_ratio(rows: list[dict[str, str]]) -> float:
    tokens: list[str] = []
    for row in rows[:32]:
        tokens.extend(_tokenize(f"{row.get('title', '')} {row.get('summary', '')}"))
    if not tokens:
        return 0.0
    return _clamp(len(set(tokens)) / max(1, len(tokens)))


@dataclass(slots=True)
class AtheriaSpeechAct:
    act_id: str
    created_at: float
    mode: str
    utterance_text: str
    evidence_refs: list[str]
    resonance: dict[str, Any]
    prosody: dict[str, Any]
    provider: str
    model: str
    spoken: bool
    backend: str
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "act_id": self.act_id,
            "created_at": round(self.created_at, 6),
            "created_at_iso": _utc_now(),
            "mode": self.mode,
            "utterance_text": self.utterance_text,
            "evidence_refs": list(self.evidence_refs),
            "resonance": dict(self.resonance),
            "prosody": dict(self.prosody),
            "provider": self.provider,
            "model": self.model,
            "spoken": bool(self.spoken),
            "backend": self.backend,
            "error": self.error,
        }


class AtheriaVoiceRuntime:
    """Speech-act runtime for Atheria ALS with optional local Windows audio output."""

    def __init__(self, storage_dir: Path) -> None:
        self.storage_dir = Path(storage_dir).resolve(strict=False)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def prosody_profile(self, resonance: dict[str, Any], *, mode: str = "analysis") -> dict[str, Any]:
        temperature = _clamp(resonance.get("system_temperature"))
        anomaly = _clamp(resonance.get("anomaly_score"))
        confidence = _clamp(resonance.get("confidence"), 0.0, 1.0)
        acceleration = _clamp(resonance.get("trend_acceleration"), -1.0, 1.0)
        tension = _clamp(resonance.get("structural_tension"))
        urgency = _clamp(max(temperature * 0.55 + anomaly * 0.45, tension * 0.65, max(0.0, acceleration)))
        if mode in {"alert", "warning"} or anomaly >= 0.7 or acceleration >= 0.8:
            style = "warnend"
        elif urgency >= 0.62:
            style = "dringlich"
        elif confidence >= 0.72:
            style = "fokussiert"
        else:
            style = "analytisch"
        rate = max(-2, min(4, int(round(-1 + urgency * 5.0))))
        pitch_percent = max(-10, min(12, int(round((temperature - 0.45) * 24.0))))
        volume = max(45, min(100, int(round(60 + confidence * 25 + urgency * 15))))
        return {
            "style": style,
            "urgency": round(urgency, 6),
            "rate": rate,
            "pitch_percent": pitch_percent,
            "volume": volume,
        }

    def _ssml(self, text: str, prosody: dict[str, Any], *, voice_name: str = "") -> str:
        escaped = html.escape(text, quote=False)
        pitch = int(_safe_float(prosody.get("pitch_percent"), 0.0))
        rate = int(_safe_float(prosody.get("rate"), 0.0))
        volume = int(_safe_float(prosody.get("volume"), 75.0))
        prosody_tag = f"<prosody pitch='{pitch:+d}%' rate='{rate:+d}%' volume='{volume}'>{escaped}</prosody>"
        if voice_name:
            body = f'<voice name="{html.escape(voice_name, quote=True)}">{prosody_tag}</voice>'
        else:
            body = prosody_tag
        return (
            "<speak version='1.0' xml:lang='de-DE'>"
            f"{body}</speak>"
        )

    def _speak_windows(self, text: str, prosody: dict[str, Any], *, voice_name: str = "") -> tuple[bool, str, str]:
        if os.name != "nt":
            return False, "none", "audio backend is only available on Windows"
        ssml = self._ssml(text, prosody, voice_name=voice_name)
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".ssml", encoding="utf-8") as handle:
            handle.write(ssml)
            temp_path = Path(handle.name)
        temp_path_text = str(temp_path).replace("'", "''")
        command = [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "$ssml = Get-Content -Raw -Path '{0}'; "
                "Add-Type -AssemblyName System.Speech; "
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                "$s.SpeakSsml($ssml)"
            ).format(temp_path_text)
        ]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=45, check=False)
            if completed.returncode != 0:
                error = completed.stderr.strip() or completed.stdout.strip() or f"powershell exited with {completed.returncode}"
                return False, "sapi", error
            return True, "sapi", ""
        except Exception as exc:  # pragma: no cover - depends on platform audio stack
            return False, "sapi", str(exc)
        finally:
            with contextlib.suppress(Exception):
                temp_path.unlink()

    def create_speech_act(
        self,
        *,
        mode: str,
        text: str,
        evidence_refs: Iterable[str],
        resonance: dict[str, Any],
        provider: str,
        model: str,
        audio_enabled: bool,
        voice_name: str = "",
    ) -> dict[str, Any]:
        cleaned = _ensure_text(text)
        prosody = self.prosody_profile(resonance, mode=mode)
        spoken = False
        backend = "text"
        error = ""
        if audio_enabled and cleaned:
            spoken, backend, error = self._speak_windows(cleaned, prosody, voice_name=voice_name)
        act = AtheriaSpeechAct(
            act_id=f"voice_{uuid.uuid4().hex[:12]}",
            created_at=time.time(),
            mode=mode,
            utterance_text=cleaned,
            evidence_refs=[str(item) for item in evidence_refs if str(item).strip()],
            resonance={key: resonance.get(key) for key in FEATURE_KEYS if key in resonance},
            prosody=prosody,
            provider=str(provider or ""),
            model=str(model or ""),
            spoken=bool(spoken),
            backend=backend,
            error=error,
        )
        return act.to_dict()


class AtheriaALSRuntime:
    """Continuous Atheria live-stream loop with local lineage, voice and chronik output."""

    def __init__(
        self,
        storage_root: Path,
        runtime_config: dict[str, Any],
        *,
        atheria_runtime: Any | None = None,
        ai_runtime: Any | None = None,
        lens_store: Any | None = None,
        federated: Any | None = None,
        event_publisher: Callable[[str, str, bool], Any] | None = None,
        default_feed_factory: Callable[[str], str] | None = None,
    ) -> None:
        self.storage_root = Path(storage_root).resolve(strict=False)
        self.runtime_config = dict(runtime_config or {})
        self.atheria_runtime = atheria_runtime
        self.ai_runtime = ai_runtime
        self.lens_store = lens_store
        self.federated = federated
        self.event_publisher = event_publisher
        self.default_feed_factory = default_feed_factory
        self.base_dir = self.storage_root / "atheria_als"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.base_dir / "config.json"
        self.state_path = self.base_dir / "state.json"
        self.status_path = self.base_dir / "status.json"
        self.events_path = self.base_dir / "events.jsonl"
        self.dialog_path = self.base_dir / "dialog.jsonl"
        self.voice_path = self.base_dir / "voice.jsonl"
        self.pid_path = self.base_dir / "als.pid"
        self.stop_request_path = self.base_dir / "stop.request"
        self.audit_report_dir = self.base_dir / "daemon_runtime"
        self.audit_core_dir = self.audit_report_dir / "core_audit"
        self.audit_core_dir.mkdir(parents=True, exist_ok=True)
        self.audit_log_path = self.audit_report_dir / "atheria_daemon_audit.jsonl"
        self.audit_key_path = self.audit_core_dir / "nova-shell-als_audit.key"
        self.resonance_path = self.audit_core_dir / "nova-shell-als_inter_core_resonance.jsonl"
        self.chronik_html_path = self.base_dir / "aion_chronik.html"
        self.voice_runtime = AtheriaVoiceRuntime(self.base_dir / "voice_runtime")

    def _default_config(self) -> dict[str, Any]:
        topic = str(self.runtime_config.get("atheria_als_topic") or "AI infrastructure agent runtime").strip() or "AI infrastructure agent runtime"
        default_feeds = ""
        if callable(self.default_feed_factory):
            with contextlib.suppress(Exception):
                default_feeds = str(self.default_feed_factory(topic) or "")
        feeds = [item.strip() for item in default_feeds.split(",") if item.strip()]
        return {
            "topic": topic,
            "feeds": feeds,
            "interval_seconds": float(self.runtime_config.get("atheria_als_interval") or 90.0),
            "trigger_threshold": float(self.runtime_config.get("atheria_als_trigger_threshold") or 0.80),
            "anomaly_threshold": float(self.runtime_config.get("atheria_als_anomaly_threshold") or 0.72),
            "trigger_cooldown_seconds": float(self.runtime_config.get("atheria_als_trigger_cooldown") or 900.0),
            "max_items_per_cycle": int(self.runtime_config.get("atheria_als_max_items") or 48),
            "dedupe_window": int(self.runtime_config.get("atheria_als_dedupe_window") or 8192),
            "voice": {
                "enabled": True,
                "audio_enabled": False,
                "voice_name": str(self.runtime_config.get("atheria_als_voice_name") or ""),
            },
            "web_search": {
                "enabled": str(self.runtime_config.get("atheria_als_web_search_enabled") or "").strip().lower() in {"1", "true", "on", "yes"},
                "query": str(self.runtime_config.get("atheria_als_search_query") or topic).strip() or topic,
                "provider": str(self.runtime_config.get("atheria_als_search_provider") or "duckduckgo_html").strip() or "duckduckgo_html",
                "max_results": int(self.runtime_config.get("atheria_als_search_max_results") or 8),
            },
            "federated": {
                "broadcast": False,
                "namespace": "atheria",
                "project": "als",
            },
        }

    def _load_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
        return payload if isinstance(payload, type(default)) else default

    def _save_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _normalized_config(self, payload: Any) -> dict[str, Any]:
        config = self._default_config()
        if isinstance(payload, dict):
            topic = _ensure_text(payload.get("topic"))
            if topic:
                config["topic"] = topic
            feeds = payload.get("feeds")
            if isinstance(feeds, str):
                config["feeds"] = [item.strip() for item in re.split(r"[\r\n,;]+", feeds) if item.strip()]
            elif isinstance(feeds, list):
                config["feeds"] = [str(item).strip() for item in feeds if str(item).strip()]
            config["interval_seconds"] = max(3.0, _safe_float(payload.get("interval_seconds"), config["interval_seconds"]))
            config["trigger_threshold"] = _clamp(payload.get("trigger_threshold", config["trigger_threshold"]), 0.0, 1.0)
            config["anomaly_threshold"] = _clamp(payload.get("anomaly_threshold", config["anomaly_threshold"]), 0.0, 1.0)
            config["trigger_cooldown_seconds"] = max(0.0, _safe_float(payload.get("trigger_cooldown_seconds"), config["trigger_cooldown_seconds"]))
            config["max_items_per_cycle"] = max(8, _safe_int(payload.get("max_items_per_cycle"), config["max_items_per_cycle"]))
            config["dedupe_window"] = max(256, _safe_int(payload.get("dedupe_window"), config["dedupe_window"]))
            if isinstance(payload.get("voice"), dict):
                voice = dict(payload["voice"])
                config["voice"]["enabled"] = bool(voice.get("enabled", config["voice"]["enabled"]))
                config["voice"]["audio_enabled"] = bool(voice.get("audio_enabled", config["voice"]["audio_enabled"]))
                config["voice"]["voice_name"] = _ensure_text(voice.get("voice_name") or config["voice"]["voice_name"])
            if isinstance(payload.get("web_search"), dict):
                search = dict(payload["web_search"])
                config["web_search"]["enabled"] = bool(search.get("enabled", config["web_search"]["enabled"]))
                config["web_search"]["query"] = _ensure_text(search.get("query") or config["web_search"]["query"]) or config["topic"]
                config["web_search"]["provider"] = _ensure_text(search.get("provider") or config["web_search"]["provider"]) or "duckduckgo_html"
                config["web_search"]["max_results"] = max(1, _safe_int(search.get("max_results"), config["web_search"]["max_results"]))
            if isinstance(payload.get("federated"), dict):
                fed = dict(payload["federated"])
                config["federated"]["broadcast"] = bool(fed.get("broadcast", config["federated"]["broadcast"]))
                config["federated"]["namespace"] = _ensure_text(fed.get("namespace") or config["federated"]["namespace"]) or "atheria"
                config["federated"]["project"] = _ensure_text(fed.get("project") or config["federated"]["project"]) or "als"
        env_topic = _ensure_text(os.environ.get("NOVA_ALS_TOPIC"))
        if env_topic:
            config["topic"] = env_topic
        env_feeds = _ensure_text(os.environ.get("NOVA_ALS_FEEDS"))
        if env_feeds:
            config["feeds"] = [item.strip() for item in re.split(r"[\r\n,;]+", env_feeds) if item.strip()]
        if os.environ.get("NOVA_ALS_INTERVAL"):
            config["interval_seconds"] = max(3.0, _safe_float(os.environ.get("NOVA_ALS_INTERVAL"), config["interval_seconds"]))
        if os.environ.get("NOVA_ALS_TRIGGER_THRESHOLD"):
            config["trigger_threshold"] = _clamp(os.environ.get("NOVA_ALS_TRIGGER_THRESHOLD"), 0.0, 1.0)
        if os.environ.get("NOVA_ALS_ANOMALY_THRESHOLD"):
            config["anomaly_threshold"] = _clamp(os.environ.get("NOVA_ALS_ANOMALY_THRESHOLD"), 0.0, 1.0)
        if os.environ.get("NOVA_ALS_TRIGGER_COOLDOWN"):
            config["trigger_cooldown_seconds"] = max(0.0, _safe_float(os.environ.get("NOVA_ALS_TRIGGER_COOLDOWN"), config["trigger_cooldown_seconds"]))
        if os.environ.get("NOVA_ALS_VOICE_AUDIO"):
            config["voice"]["audio_enabled"] = str(os.environ.get("NOVA_ALS_VOICE_AUDIO")).strip().lower() in {"1", "true", "on", "yes"}
        if os.environ.get("NOVA_ALS_VOICE_NAME"):
            config["voice"]["voice_name"] = _ensure_text(os.environ.get("NOVA_ALS_VOICE_NAME"))
        if os.environ.get("NOVA_ALS_WEB_SEARCH"):
            config["web_search"]["enabled"] = str(os.environ.get("NOVA_ALS_WEB_SEARCH")).strip().lower() in {"1", "true", "on", "yes"}
        if os.environ.get("NOVA_ALS_SEARCH_QUERY"):
            config["web_search"]["query"] = _ensure_text(os.environ.get("NOVA_ALS_SEARCH_QUERY")) or config["topic"]
        if os.environ.get("NOVA_ALS_SEARCH_PROVIDER"):
            config["web_search"]["provider"] = _ensure_text(os.environ.get("NOVA_ALS_SEARCH_PROVIDER")) or "duckduckgo_html"
        if os.environ.get("NOVA_ALS_SEARCH_LIMIT"):
            config["web_search"]["max_results"] = max(1, _safe_int(os.environ.get("NOVA_ALS_SEARCH_LIMIT"), config["web_search"]["max_results"]))
        if os.environ.get("NOVA_ALS_FEDERATED_BROADCAST"):
            config["federated"]["broadcast"] = str(os.environ.get("NOVA_ALS_FEDERATED_BROADCAST")).strip().lower() in {"1", "true", "on", "yes"}
        if not config["feeds"] and callable(self.default_feed_factory):
            default_feeds = _ensure_text(self.default_feed_factory(config["topic"]))
            config["feeds"] = [item.strip() for item in default_feeds.split(",") if item.strip()]
        config["web_search"]["query"] = _ensure_text(config.get("web_search", {}).get("query") or config["topic"]) or config["topic"]
        config["web_search"]["provider"] = _ensure_text(config.get("web_search", {}).get("provider") or "duckduckgo_html") or "duckduckgo_html"
        config["web_search"]["max_results"] = max(1, _safe_int(config.get("web_search", {}).get("max_results"), 8))
        return config

    def load_config(self) -> dict[str, Any]:
        return self._normalized_config(self._load_json(self.config_path, {}))

    def configure(self, updates: dict[str, Any] | None = None) -> dict[str, Any]:
        current = self._load_json(self.config_path, {})
        merged = dict(current) if isinstance(current, dict) else {}
        if isinstance(updates, dict):
            for key, value in updates.items():
                if key in {"voice", "web_search", "federated"} and isinstance(value, dict):
                    merged[key] = {**dict(merged.get(key) or {}), **value}
                else:
                    merged[key] = value
        config = self._normalized_config(merged)
        self._save_json(self.config_path, config)
        return config

    def _default_state(self) -> dict[str, Any]:
        return {
            "seen_hashes": [],
            "history": [],
            "vocabulary": {},
            "last_cycle_at": 0.0,
            "last_event_id": "",
            "last_trigger_id": "",
            "last_trigger_signature": "",
            "last_trigger_at": 0.0,
            "last_snapshot_id": "",
            "event_count": 0,
            "dialog_count": 0,
            "speech_count": 0,
            "current_resonance": {},
            "last_cycle": {},
        }

    def _load_state(self) -> dict[str, Any]:
        state = self._load_json(self.state_path, self._default_state())
        if not isinstance(state, dict):
            state = self._default_state()
        default = self._default_state()
        normalized = dict(default)
        normalized.update({key: value for key, value in state.items() if key in default})
        normalized["seen_hashes"] = [str(item) for item in normalized.get("seen_hashes", []) if str(item).strip()]
        normalized["history"] = [item for item in normalized.get("history", []) if isinstance(item, dict)][-256:]
        normalized["vocabulary"] = {str(key): _safe_int(value, 0) for key, value in dict(normalized.get("vocabulary", {})).items() if str(key).strip()}
        return normalized

    def _save_state(self, state: dict[str, Any]) -> None:
        payload = dict(state)
        payload["history"] = [item for item in payload.get("history", []) if isinstance(item, dict)][-256:]
        payload["seen_hashes"] = [str(item) for item in payload.get("seen_hashes", []) if str(item).strip()][-max(256, int(self.load_config().get("dedupe_window", 8192))):]
        self._save_json(self.state_path, payload)

    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _trigger_signature(
        self,
        *,
        trigger_reason: str,
        titles: list[str],
        dominant_topics: list[str],
        resonance: dict[str, Any],
    ) -> str:
        payload = {
            "trigger_reason": str(trigger_reason or ""),
            "titles": [str(item or "") for item in titles[:3]],
            "dominant_topics": [str(item or "") for item in dominant_topics[:3]],
            "anomaly_score": round(_safe_float(resonance.get("anomaly_score"), 0.0), 6),
            "trend_acceleration": round(_safe_float(resonance.get("trend_acceleration"), 0.0), 6),
            "system_temperature": round(_safe_float(resonance.get("system_temperature"), 0.0), 6),
        }
        return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()

    def _item_hash(self, item: dict[str, str]) -> str:
        basis = "|".join(
            [
                _ensure_text(item.get("url")),
                _ensure_text(item.get("title")),
                _ensure_text(item.get("summary")),
            ]
        )
        if not basis.replace("|", "").strip():
            basis = "|".join(
                [
                    _ensure_text(item.get("title")),
                    _ensure_text(item.get("summary")),
                    _ensure_text(item.get("source")),
                ]
            )
        return hashlib.sha256(basis.encode("utf-8", errors="replace")).hexdigest()

    def _collect_stream_items(self, feeds: list[str], *, max_items: int) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for feed in feeds[:12]:
            source = _ensure_text(feed)
            if not source:
                continue
            try:
                body = _http_text(source)
            except Exception:
                continue
            stripped = body.lstrip()
            if stripped.startswith("{") or stripped.startswith("["):
                with contextlib.suppress(Exception):
                    for row in _normalize_rows(json.loads(body), source_hint=source):
                        row["sensor"] = "rss"
                        rows.append(row)
                    continue
            with contextlib.suppress(Exception):
                for row in _parse_feed_xml(body, source):
                    row["sensor"] = "rss"
                    rows.append(row)
        seen: set[str] = set()
        deduped: list[dict[str, str]] = []
        for row in rows:
            digest = self._item_hash(row)
            if digest in seen:
                continue
            seen.add(digest)
            deduped.append(row)
            if len(deduped) >= max_items:
                break
        return deduped

    def _web_search_url(self, query: str, provider: str) -> str:
        normalized_provider = _ensure_text(provider).lower() or "duckduckgo_html"
        encoded_query = urllib.parse.quote_plus(_ensure_text(query))
        if normalized_provider in {"duckduckgo", "duckduckgo_html"}:
            return f"https://html.duckduckgo.com/html/?q={encoded_query}"
        if normalized_provider in {"duckduckgo_lite", "duckduckgo-lite"}:
            return f"https://lite.duckduckgo.com/lite/?q={encoded_query}"
        if normalized_provider in {"google_news", "google_news_rss", "google-news-rss"}:
            return f"https://news.google.com/rss/search?q={encoded_query}"
        raise ValueError(f"unsupported ALS search provider: {provider}")

    def _normalize_search_rows(self, rows: list[dict[str, str]], *, query: str, provider: str) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        source_label = f"web_search:{provider}"
        for row in rows:
            title = _ensure_text(row.get("title"))
            summary = _ensure_text(row.get("summary"))
            url = _normalize_search_result_url(row.get("url", ""))
            if not title or not url:
                continue
            normalized.append(
                {
                    "title": title,
                    "summary": summary,
                    "source": source_label,
                    "url": url,
                    "published_at": _ensure_text(row.get("published_at")),
                    "sensor": "web_search",
                    "search_query": _ensure_text(query),
                    "search_provider": _ensure_text(provider),
                }
            )
        return normalized

    def _search_web_rows(self, query: str, *, provider: str, limit: int) -> list[dict[str, str]]:
        normalized_provider = _ensure_text(provider).lower() or "duckduckgo_html"
        source_url = self._web_search_url(query, normalized_provider)
        body = _http_text(source_url)
        stripped = body.lstrip()
        if normalized_provider in {"google_news", "google_news_rss", "google-news-rss"}:
            rows = _parse_feed_xml(body, source_url)
            return self._normalize_search_rows(rows[: max(1, int(limit))], query=query, provider=normalized_provider)
        parser = _DuckDuckGoSearchParser()
        parser.feed(body)
        parser.close()
        return self._normalize_search_rows(parser.results[: max(1, int(limit))], query=query, provider=normalized_provider)

    def search_web(self, query: str, *, provider: str | None = None, limit: int | None = None) -> dict[str, Any]:
        config = self.load_config()
        search_config = dict(config.get("web_search") or {})
        resolved_query = _ensure_text(query) or _ensure_text(search_config.get("query")) or _ensure_text(config.get("topic"))
        if not resolved_query:
            raise ValueError("ALS search query must not be empty")
        resolved_provider = _ensure_text(provider or search_config.get("provider")) or "duckduckgo_html"
        resolved_limit = max(1, _safe_int(limit if limit is not None else search_config.get("max_results"), 8))
        results = self._search_web_rows(resolved_query, provider=resolved_provider, limit=resolved_limit)
        return {
            "query": resolved_query,
            "provider": resolved_provider,
            "limit": resolved_limit,
            "result_count": len(results),
            "results": results,
            "search_url": self._web_search_url(resolved_query, resolved_provider),
        }

    def _collect_cycle_inputs(self, config: dict[str, Any]) -> list[dict[str, str]]:
        max_items = max(8, int(config.get("max_items_per_cycle", 48)))
        search_config = dict(config.get("web_search") or {})
        web_enabled = bool(search_config.get("enabled"))
        search_limit = min(max_items, max(1, _safe_int(search_config.get("max_results"), 8))) if web_enabled else 0
        feed_budget = max_items if not web_enabled else max(8, max_items - search_limit)
        rows: list[dict[str, str]] = []
        rows.extend(self._collect_stream_items(list(config.get("feeds", [])), max_items=feed_budget))
        if web_enabled:
            with contextlib.suppress(Exception):
                rows.extend(
                    self._search_web_rows(
                        _ensure_text(search_config.get("query")) or _ensure_text(config.get("topic")),
                        provider=_ensure_text(search_config.get("provider")) or "duckduckgo_html",
                        limit=search_limit,
                    )
                )
        seen: set[str] = set()
        deduped: list[dict[str, str]] = []
        for row in rows:
            digest = self._item_hash(row)
            if digest in seen:
                continue
            seen.add(digest)
            deduped.append(row)
            if len(deduped) >= max_items:
                break
        return deduped

    def _derive_resonance(self, rows: list[dict[str, str]], history: list[dict[str, Any]]) -> dict[str, Any]:
        text = "\n".join(
            f"- {row.get('title', '')} :: {row.get('summary', '')}".strip()
            for row in rows[:32]
            if row.get("title") or row.get("summary")
        )
        group_scores = _score_groups(text)
        article_count_norm = _clamp(len(rows) / 24.0)
        source_diversity = _clamp(len({row.get('source') for row in rows if row.get('source')}) / max(1, min(len(rows), 8)))
        novelty = _novelty_ratio(rows)
        current = {
            "signal_strength": _clamp(article_count_norm * 0.55 + group_scores["agents"] * 0.45),
            "system_temperature": _clamp(article_count_norm * 0.4 + source_diversity * 0.25 + group_scores["research"] * 0.35),
            "resource_pressure": _clamp(group_scores["infrastructure"] * 0.7 + group_scores["operations"] * 0.3),
            "structural_tension": _clamp(group_scores["agents"] * 0.5 + group_scores["infrastructure"] * 0.3 + group_scores["risk"] * 0.2),
            "entropic_index": _clamp(novelty * 0.55 + group_scores["risk"] * 0.25 + source_diversity * 0.2),
            "anomaly_score": 0.0,
        }
        baseline_window = history[-24:]
        baseline = {key: _mean(float(item.get(key, 0.0)) for item in baseline_window) for key in current} if baseline_window else {key: 0.0 for key in current}
        deltas = {key: round(float(current[key]) - float(baseline[key]), 6) for key in current}
        current["anomaly_score"] = _clamp(max(abs(value) for value in deltas.values()) * 1.6 if deltas else 0.0)
        if baseline_window:
            prev_trend = float(baseline_window[-1].get("trend_pressure", 0.0))
            trend_pressure = (
                deltas["signal_strength"] * 0.35
                + deltas["resource_pressure"] * 0.2
                + deltas["structural_tension"] * 0.2
                + deltas["entropic_index"] * 0.15
                + deltas["system_temperature"] * 0.1
            )
            acceleration = trend_pressure - prev_trend
            forecast_score = _clamp(0.5 + trend_pressure * 0.85 + acceleration * 0.45)
            confidence = _clamp(min(1.0, len(baseline_window) / 8.0) * 0.4 + abs(forecast_score - 0.5) * 1.5)
        else:
            trend_pressure = 0.0
            acceleration = 0.0
            forecast_score = 0.5
            confidence = _clamp(0.12 + article_count_norm * 0.2, 0.0, 0.25)
        current["trend_pressure"] = round(trend_pressure, 6)
        current["trend_acceleration"] = round(acceleration, 6)
        current["forecast_score"] = round(forecast_score, 6)
        current["confidence"] = round(confidence, 6)
        current["item_count"] = len(rows)
        current["source_diversity"] = round(source_diversity, 6)
        current["keyword_groups"] = group_scores
        current["deltas"] = deltas
        return current

    def _dominant_topics(self, resonance: dict[str, Any]) -> list[str]:
        groups = dict(resonance.get("keyword_groups") or {})
        ranked = sorted(groups.items(), key=lambda item: float(item[1]), reverse=True)
        return [str(name) for name, value in ranked if float(value) > 0.0][:3]

    def _expand_vocabulary(self, state: dict[str, Any], rows: list[dict[str, str]]) -> list[str]:
        vocabulary = dict(state.get("vocabulary") or {})
        additions: list[str] = []
        ranked: dict[str, int] = {}
        for row in rows[:32]:
            for token in _tokenize(f"{row.get('title', '')} {row.get('summary', '')}"):
                if len(token) < 5 or token.isdigit():
                    continue
                ranked[token] = ranked.get(token, 0) + 1
        for token, _count in sorted(ranked.items(), key=lambda item: (-item[1], item[0]))[:24]:
            previous = int(vocabulary.get(token, 0))
            vocabulary[token] = previous + ranked[token]
            if previous <= 0:
                additions.append(token)
        state["vocabulary"] = vocabulary
        return additions[:12]

    def _record_lens_snapshot(self, stage: str, *, output_text: str, data_preview: str) -> str:
        if self.lens_store is None:
            return ""
        result = SimpleNamespace(output=output_text, error="", data_type=SimpleNamespace(value="object"))
        with contextlib.suppress(Exception):
            return str(self.lens_store.record(stage, result, f"als-{uuid.uuid4().hex[:10]}", data_preview))
        return ""

    def _ensure_audit_identity(self) -> tuple[bytes, str]:
        if not self.audit_key_path.exists():
            seed = f"{uuid.uuid4().hex}{uuid.uuid4().hex}"
            self.audit_key_path.write_text(seed, encoding="utf-8")
        seed = self.audit_key_path.read_text(encoding="utf-8").strip()
        derived = hashlib.sha256(seed.encode("utf-8") + b"|atheria-daemon").digest()
        fingerprint = hashlib.sha1(derived).hexdigest()[:12]
        return derived, fingerprint

    def _last_audit_signature(self) -> str:
        if not self.audit_log_path.exists():
            return ""
        lines = [line for line in self.audit_log_path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
        if not lines:
            return ""
        with contextlib.suppress(Exception):
            payload = json.loads(lines[-1])
            if isinstance(payload, dict):
                return str(payload.get("journal_signature") or "")
        return ""

    def _append_audit_entry(self, reason: str, *, market: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
        key, fingerprint = self._ensure_audit_identity()
        previous = self._last_audit_signature() or "GENESIS"
        entry = {
            "timestamp": time.time(),
            "core_id": "nova-shell-als",
            "reason": str(reason or "scheduled_integrity_audit"),
            "observer_label": "Atheria Live Stream",
            "market": market,
            "extra": dict(extra or {}),
        }
        payload = {
            "previous": previous,
            "entry": entry,
        }
        signature = hmac.new(key, _stable_json(payload).encode("utf-8"), hashlib.sha256).hexdigest()
        record = dict(entry)
        record["previous"] = previous
        record["journal_key_fingerprint"] = fingerprint
        record["journal_signature"] = signature
        self._append_jsonl(self.audit_log_path, record)
        self._refresh_chronik_html()
        return record

    def _append_resonance_invariant(self, event: dict[str, Any]) -> None:
        metrics = dict(event.get("metrics") or {})
        record = {
            "timestamp": float(event.get("timestamp") or time.time()),
            "observer_label": "Atheria Live Stream",
            "trigger_asset": "SIGNAL",
            "target_asset": "TEMPERATURE",
            "lag_minutes": 0.0,
            "invariant": {
                "statement": str(event.get("summary") or "ALS detected a significant resonance shift."),
                "confidence": _clamp(metrics.get("confidence"), 0.0, 1.0),
                "mean_effect_size": _safe_float(metrics.get("trend_acceleration"), 0.0),
                "samples": max(1, int(event.get("new_item_count") or event.get("item_count") or 1)),
                "details": {
                    "mean_effect_size": _safe_float(metrics.get("trend_acceleration"), 0.0),
                    "samples": max(1, int(event.get("new_item_count") or event.get("item_count") or 1)),
                    "observer_label": "Atheria Live Stream",
                    "trigger_asset": "SIGNAL",
                    "target_asset": "TEMPERATURE",
                    "lag_minutes": 0.0,
                },
            },
        }
        self._append_jsonl(self.resonance_path, record)

    def _refresh_chronik_html(self) -> None:
        module = load_aion_chronik()
        entries = module._load_lines(self.audit_log_path)
        if not entries:
            return
        resolver = module.SignatureResolver(self.audit_report_dir)
        records, _expected = module._analyze_entries(entries[-200:], resolver=resolver, verify=True, expected_previous=None)
        module._write_html(self.chronik_html_path, records, self.audit_report_dir)

    def _emit_event(self, name: str, payload: dict[str, Any], *, broadcast: bool = False) -> None:
        if not callable(self.event_publisher):
            return
        text = json.dumps(payload, ensure_ascii=False)
        with contextlib.suppress(Exception):
            self.event_publisher(name, text, broadcast)

    def _append_voice(self, speech_act: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        self._append_jsonl(self.voice_path, speech_act)
        state["speech_count"] = int(state.get("speech_count", 0)) + 1
        return speech_act

    def _append_dialog(self, payload: dict[str, Any], state: dict[str, Any]) -> None:
        self._append_jsonl(self.dialog_path, payload)
        state["dialog_count"] = int(state.get("dialog_count", 0)) + 1

    def _active_dialog_provider(self) -> tuple[str, str]:
        if self.ai_runtime is None:
            return "", ""
        with contextlib.suppress(Exception):
            if self.ai_runtime.is_configured("atheria"):
                return "atheria", self.ai_runtime.get_active_model("atheria") or "atheria-core"
        with contextlib.suppress(Exception):
            provider = self.ai_runtime.get_active_provider()
            model = self.ai_runtime.get_active_model(provider) if provider else ""
            if provider:
                return str(provider), str(model or "")
        return "", ""

    def last_voice(self) -> dict[str, Any]:
        rows = _chunked_tail(self.voice_path, limit=1)
        return rows[-1] if rows else {}

    def tail_events(self, *, limit: int = 10) -> list[dict[str, Any]]:
        return _chunked_tail(self.events_path, limit=limit)

    def tail_dialog(self, *, limit: int = 10) -> list[dict[str, Any]]:
        return _chunked_tail(self.dialog_path, limit=limit)

    def _pid_running(self, pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            completed = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                check=False,
            )
            return str(pid) in completed.stdout
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def is_running(self) -> bool:
        if not self.pid_path.exists():
            return False
        pid = _safe_int(self.pid_path.read_text(encoding="utf-8", errors="replace").strip(), 0)
        return self._pid_running(pid)

    def request_stop(self) -> dict[str, Any]:
        self.stop_request_path.write_text("stop\n", encoding="utf-8")
        return {"requested": True, "stop_request_path": str(self.stop_request_path)}

    def status_payload(self) -> dict[str, Any]:
        config = self.load_config()
        state = self._load_state()
        status = self._load_json(self.status_path, {})
        pid = _safe_int(_ensure_text(self.pid_path.read_text(encoding="utf-8")) if self.pid_path.exists() else 0, 0)
        search_config = dict(config.get("web_search") or {})
        return {
            "running": self._pid_running(pid),
            "pid": pid,
            "base_dir": str(self.base_dir),
            "config": config,
            "stream": {
                "topic": config.get("topic"),
                "feed_count": len(config.get("feeds", [])),
                "feeds": list(config.get("feeds", [])),
                "event_count": int(state.get("event_count", 0)),
                "dialog_count": int(state.get("dialog_count", 0)),
                "speech_count": int(state.get("speech_count", 0)),
                "history_length": len(state.get("history", [])),
                "dedupe_size": len(state.get("seen_hashes", [])),
                "web_search": {
                    "enabled": bool(search_config.get("enabled", False)),
                    "query": _ensure_text(search_config.get("query") or config.get("topic")),
                    "provider": _ensure_text(search_config.get("provider") or "duckduckgo_html"),
                    "max_results": max(1, _safe_int(search_config.get("max_results"), 8)),
                },
            },
            "current_resonance": dict(state.get("current_resonance") or {}),
            "last_cycle": dict(state.get("last_cycle") or {}),
            "last_trigger": dict(status.get("last_trigger") or {}),
            "voice": {
                "enabled": bool(config.get("voice", {}).get("enabled", True)),
                "audio_enabled": bool(config.get("voice", {}).get("audio_enabled", False)),
                "voice_name": str(config.get("voice", {}).get("voice_name") or ""),
                "last_speech_act": self.last_voice(),
            },
            "chronik": {
                "report_file": str(self.audit_log_path),
                "html": str(self.chronik_html_path),
            },
            "status": status if isinstance(status, dict) else {},
        }

    def run_cycle(self, *, rows: list[dict[str, str]] | None = None) -> dict[str, Any]:
        config = self.load_config()
        state = self._load_state()
        collected = rows if rows is not None else self._collect_cycle_inputs(config)
        seen = set(str(item) for item in state.get("seen_hashes", []))
        new_items: list[dict[str, str]] = []
        for row in collected:
            digest = self._item_hash(row)
            row["content_hash"] = digest
            if digest in seen:
                continue
            seen.add(digest)
            new_items.append(row)
        focus_items = new_items or collected
        resonance = self._derive_resonance(focus_items, list(state.get("history", [])))
        dominant_topics = self._dominant_topics(resonance)
        additions = self._expand_vocabulary(state, new_items)
        event_id = f"als_{uuid.uuid4().hex[:12]}"
        trigger_threshold = _safe_float(config.get("trigger_threshold"), 0.80)
        anomaly_threshold = _safe_float(config.get("anomaly_threshold"), 0.72)
        trigger_cooldown_seconds = max(0.0, _safe_float(config.get("trigger_cooldown_seconds"), 900.0))
        has_baseline = bool(state.get("history"))
        fresh_signal = bool(new_items)
        trigger_reason = ""
        if float(resonance.get("trend_acceleration", 0.0)) >= trigger_threshold:
            trigger_reason = "trend_acceleration"
        elif float(resonance.get("anomaly_score", 0.0)) >= anomaly_threshold:
            trigger_reason = "anomaly_score"
        trigger_candidate = has_baseline and fresh_signal and bool(trigger_reason)
        titles = [row.get("title", "") for row in focus_items[:5] if row.get("title")]
        sensor_counts: dict[str, int] = {}
        for row in collected:
            sensor = _ensure_text(row.get("sensor") or "stream")
            sensor_counts[sensor] = sensor_counts.get(sensor, 0) + 1
        trigger_signature = self._trigger_signature(
            trigger_reason=trigger_reason,
            titles=titles,
            dominant_topics=dominant_topics,
            resonance=resonance,
        )
        repeated_trigger = (
            trigger_candidate
            and trigger_signature == str(state.get("last_trigger_signature") or "")
            and (time.time() - _safe_float(state.get("last_trigger_at"), 0.0)) < trigger_cooldown_seconds
        )
        triggered = trigger_candidate and not repeated_trigger
        event_mode = "alert" if triggered else "update"
        summary_prefix = (
            "Atheria erkennt eine beschleunigte Resonanzverschiebung im Informationsfeld."
            if triggered
            else "Atheria aktualisiert ihren kontinuierlichen Resonanzzustand."
        )
        if not fresh_signal and has_baseline:
            summary_prefix = "Atheria haelt ihren letzten Resonanzzustand ohne neue Eingangssignale stabil."
        elif repeated_trigger:
            summary_prefix = "Atheria bestaetigt eine fortbestehende Anomalielage, unterdrueckt aber den Wiederholungsalarm innerhalb des Cooldown-Fensters."
        summary = summary_prefix
        if titles:
            summary += " Fokus: " + "; ".join(titles[:3]) + "."
        if additions:
            summary += " Neue Begriffe: " + ", ".join(additions[:6]) + "."
        event = {
            "event_id": event_id,
            "timestamp": time.time(),
            "timestamp_iso": _utc_now(),
            "mode": event_mode,
            "topic": str(config.get("topic") or ""),
            "summary": summary.strip(),
            "item_count": len(collected),
            "new_item_count": len(new_items),
            "items": focus_items[:12],
            "sensor_counts": sensor_counts,
            "metrics": resonance,
            "dominant_topics": dominant_topics,
            "vocabulary_additions": additions,
            "fresh_signal": bool(fresh_signal),
            "triggered": bool(triggered),
            "trigger_reason": trigger_reason if triggered else "",
            "trigger_candidate": bool(trigger_candidate),
            "trigger_suppressed": bool(repeated_trigger),
        }
        if self.atheria_runtime is not None and focus_items:
            training_rows = [
                (
                    f"ALS event {event_id}",
                    dominant_topics[0] if dominant_topics else "als_stream",
                    "\n".join(
                        [
                            event["summary"],
                            json.dumps({"metrics": resonance, "titles": titles[:8]}, ensure_ascii=False),
                        ]
                    ),
                )
            ]
            with contextlib.suppress(Exception):
                self.atheria_runtime.train_rows(training_rows)
        snapshot_id = self._record_lens_snapshot(
            "atheria.als.cycle",
            output_text=event["summary"],
            data_preview=json.dumps(event, ensure_ascii=False, indent=2),
        )
        if snapshot_id:
            event["lens_snapshot_id"] = snapshot_id
            state["last_snapshot_id"] = snapshot_id
        evidence_refs = [event_id]
        if snapshot_id:
            evidence_refs.append(snapshot_id)
        voice_enabled = bool(config.get("voice", {}).get("enabled", True))
        speech_act: dict[str, Any] | None = None
        if voice_enabled:
            speech_act = self.voice_runtime.create_speech_act(
                mode=event_mode,
                text=event["summary"],
                evidence_refs=evidence_refs,
                resonance=resonance,
                provider="atheria",
                model="als-resonance-voice",
                audio_enabled=bool(config.get("voice", {}).get("audio_enabled", False)),
                voice_name=str(config.get("voice", {}).get("voice_name") or ""),
            )
            self._append_voice(speech_act, state)
            event["speech_act"] = speech_act
        state["seen_hashes"] = list(seen)
        history_entry = {"timestamp": event["timestamp"], **{key: resonance.get(key, 0.0) for key in FEATURE_KEYS}}
        state["history"] = [*list(state.get("history", [])), history_entry][-256:]
        state["last_cycle_at"] = event["timestamp"]
        state["last_event_id"] = event_id
        if triggered:
            state["last_trigger_id"] = event_id
            state["last_trigger_signature"] = trigger_signature
            state["last_trigger_at"] = event["timestamp"]
        state["event_count"] = int(state.get("event_count", 0)) + 1
        state["current_resonance"] = resonance
        state["last_cycle"] = {
            "event_id": event_id,
            "summary": event["summary"],
            "triggered": bool(triggered),
            "timestamp": event["timestamp"],
            "item_count": len(collected),
            "new_item_count": len(new_items),
        }
        self._save_state(state)
        self._append_jsonl(self.events_path, event)
        market_payload = {
            "market_profile": "web_resonance_stream",
            "transport": "rss_stream",
            "trauma_pressure": _safe_float(resonance.get("anomaly_score"), 0.0),
            "recent_returns": {
                "SIGNAL": [float(item.get("signal_strength", 0.0)) for item in state.get("history", [])[-8:]],
                "TEMPERATURE": [float(item.get("system_temperature", 0.0)) for item in state.get("history", [])[-8:]],
            },
            "recent_volume_flux": {
                "ACCELERATION": [float(item.get("trend_acceleration", 0.0)) for item in state.get("history", [])[-8:]],
                "TENSION": [float(item.get("structural_tension", 0.0)) for item in state.get("history", [])[-8:]],
            },
            "last_market_snapshot": {
                "symbols": {
                    "SIGNAL": resonance.get("signal_strength"),
                    "TEMPERATURE": resonance.get("system_temperature"),
                    "ANOMALY": resonance.get("anomaly_score"),
                },
                "sensor_context": {
                    "als": {
                        "topic": str(config.get("topic") or ""),
                        "dominant_topics": dominant_topics,
                        "new_item_count": len(new_items),
                        "item_count": len(collected),
                        "sensor_counts": sensor_counts,
                        "source_titles": titles[:5],
                        "trigger_reason": trigger_reason,
                    }
                },
            },
        }
        reason = "market_alert" if triggered else "scheduled_integrity_audit"
        if triggered:
            if trigger_reason == "trend_acceleration":
                reason = "market_anomaly::trend_acceleration"
            elif trigger_reason == "anomaly_score":
                reason = "market_anomaly::anomaly_score"
        should_append_audit = bool(triggered or fresh_signal or not has_baseline)
        if should_append_audit:
            self._append_audit_entry(
                reason,
                market=market_payload,
                extra={
                    "event_id": event_id,
                    "summary": event["summary"],
                    "topic": str(config.get("topic") or ""),
                    "trigger_reason": trigger_reason,
                    "dominant_topics": dominant_topics,
                    "source_titles": titles[:5],
                    "sensor_counts": sensor_counts,
                    "item_count": len(collected),
                    "new_item_count": len(new_items),
                    "fresh_signal": bool(fresh_signal),
                    "metrics": {
                        "signal_strength": _safe_float(resonance.get("signal_strength"), 0.0),
                        "system_temperature": _safe_float(resonance.get("system_temperature"), 0.0),
                        "structural_tension": _safe_float(resonance.get("structural_tension"), 0.0),
                        "anomaly_score": _safe_float(resonance.get("anomaly_score"), 0.0),
                        "trend_acceleration": _safe_float(resonance.get("trend_acceleration"), 0.0),
                        "confidence": _safe_float(resonance.get("confidence"), 0.0),
                    },
                    "thresholds": {
                        "trigger_threshold": trigger_threshold,
                        "anomaly_threshold": anomaly_threshold,
                    },
                },
            )
        if triggered:
            self._append_resonance_invariant(event)
        if triggered and self.federated is not None:
            with contextlib.suppress(Exception):
                event["federated"] = self.federated.publish_update(
                    statement=event["summary"],
                    namespace=str(config.get("federated", {}).get("namespace") or "atheria"),
                    project=str(config.get("federated", {}).get("project") or _slug(str(config.get("topic") or "als"))),
                    kind="als_resonance_trigger",
                    confidence=float(resonance.get("confidence", 0.0)),
                    effect_size=float(resonance.get("trend_acceleration", 0.0)),
                    samples=max(1, len(new_items) or len(collected)),
                    summary=event["summary"],
                    metadata={"event_id": event_id, "topics": dominant_topics},
                    core_id="nova-shell-als",
                )
        self._emit_event("atheria.als.update", event, broadcast=False)
        if triggered:
            self._emit_event("atheria.als.trigger", event, broadcast=bool(config.get("federated", {}).get("broadcast", False)))
        status_payload = {
            "mode": "running",
            "pid": os.getpid(),
            "last_cycle": state.get("last_cycle", {}),
            "last_trigger": event if triggered else self._load_json(self.status_path, {}).get("last_trigger", {}),
            "updated_at": _utc_now(),
        }
        self._save_json(self.status_path, status_payload)
        event["state"] = state.get("last_cycle", {})
        return event

    def _heuristic_answer(self, question: str, evidence: list[dict[str, Any]]) -> str:
        latest = evidence[0] if evidence else {}
        metrics = dict(latest.get("metrics") or latest.get("current_resonance") or {})
        summary = _ensure_text(latest.get("summary") or latest.get("utterance_text"))
        if not summary:
            summary = "Ich beobachte derzeit keinen frischen Resonanzimpuls im Live-Stream."
        details = []
        if metrics:
            details.append(f"Signalstaerke {float(metrics.get('signal_strength', 0.0)):.2f}")
            details.append(f"Temperatur {float(metrics.get('system_temperature', 0.0)):.2f}")
            details.append(f"Anomalie {float(metrics.get('anomaly_score', 0.0)):.2f}")
        if question.strip():
            return f"{summary} Evidenz: {', '.join(details)}." if details else summary
        return summary

    def _dialog_source_titles(self, evidence: list[dict[str, Any]], *, limit: int = 3) -> list[str]:
        titles: list[str] = []
        seen: set[str] = set()
        for event in evidence:
            for item in event.get("items") or []:
                if not isinstance(item, dict):
                    continue
                title = _ensure_text(item.get("title"))
                key = title.casefold()
                if not title or key in seen:
                    continue
                seen.add(key)
                titles.append(title)
                if len(titles) >= max(1, int(limit)):
                    return titles
        return titles

    def _dialog_focus_fields(self, resonance: dict[str, Any], *, limit: int = 3) -> list[str]:
        groups = dict(resonance.get("keyword_groups") or {})
        ranked = [
            name
            for name, score in sorted(groups.items(), key=lambda item: float(item[1]), reverse=True)
            if _safe_float(score) >= 0.12
        ]
        labels = {
            "agents": "Agenten und Laufzeit",
            "operations": "Betrieb und Skalierung",
            "infrastructure": "Infrastruktur",
            "research": "Forschung",
            "risk": "Risiko und Sicherheit",
            "economics": "Investitionen und Markt",
        }
        return [labels.get(name, name) for name in ranked[: max(1, int(limit))]]

    def _dialog_risk_assessment(self, resonance: dict[str, Any]) -> dict[str, Any]:
        anomaly = _clamp(resonance.get("anomaly_score"))
        temperature = _clamp(resonance.get("system_temperature"))
        acceleration = _clamp(resonance.get("trend_acceleration"), -1.0, 1.0)
        tension = _clamp(resonance.get("structural_tension"))
        confidence = _clamp(resonance.get("confidence"))
        score = max(anomaly, temperature * 0.75 + max(0.0, acceleration) * 0.25, tension * 0.85)
        if score >= 0.8:
            level = "hoch"
        elif score >= 0.5:
            level = "mittel"
        else:
            level = "niedrig"
        reasons: list[str] = []
        if anomaly >= 0.75:
            reasons.append("deutlich erhoehter Anomaliegrad")
        if temperature >= 0.6:
            reasons.append("erhoehte Systemtemperatur")
        if acceleration >= 0.8:
            reasons.append("starke Trendbeschleunigung")
        elif acceleration >= 0.2:
            reasons.append("spuerbare Trendbeschleunigung")
        if tension >= 0.5:
            reasons.append("strukturelle Spannung im Feld")
        if not reasons:
            reasons.append("derzeit keine eskalierende Resonanzlage")
        return {
            "level": level,
            "score": round(score, 6),
            "confidence": round(confidence, 6),
            "reasons": reasons[:3],
        }

    def _render_dialog_answer(
        self,
        base_answer: str,
        *,
        resonance: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> tuple[str, dict[str, Any], list[str], list[str]]:
        cleaned = self._normalize_dialog_answer(base_answer)
        if not cleaned:
            cleaned = "Atheria beobachtet derzeit keine belastbare Dominanz im Informationsfeld."
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = re.sub(r"([.!?])\s+([A-ZÄÖÜ])", r"\1\n", cleaned, count=1)
        lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
        lead = lines[0] if lines else cleaned
        if len(lead) > 260:
            lead = lead[:257].rstrip(" ,;:.") + "..."
        focus_fields = self._dialog_focus_fields(resonance)
        risk = self._dialog_risk_assessment(resonance)
        source_titles = self._dialog_source_titles(evidence)
        answer_lines = [lead]
        if focus_fields:
            answer_lines.append(f"Dominante Felder: {', '.join(focus_fields)}.")
        answer_lines.append(
            "Risikoeinordnung: {level} (Anomalie {anomaly:.2f}, Temperatur {temperature:.2f}, Konfidenz {confidence:.2f}).".format(
                level=risk["level"],
                anomaly=_clamp(resonance.get("anomaly_score")),
                temperature=_clamp(resonance.get("system_temperature")),
                confidence=_clamp(resonance.get("confidence")),
            )
        )
        return "\n".join(answer_lines), risk, source_titles, focus_fields

    def _normalize_dialog_answer(self, text: str) -> str:
        cleaned = _ensure_text(text).replace("\r\n", "\n").strip()
        if not cleaned:
            return ""
        cut_markers = (
            "\n{",
            "\n\n{",
            "\nWeitere Atheria-Erinnerungen:",
            "\n\nWeitere Atheria-Erinnerungen:",
            "\nAtheria-Zustand:",
            "\n\nAtheria-Zustand:",
            "\nSystemfokus:",
            "\n\nSystemfokus:",
        )
        end_index = len(cleaned)
        for marker in cut_markers:
            position = cleaned.find(marker)
            if position != -1:
                end_index = min(end_index, position)
        cleaned = cleaned[:end_index].strip()
        cleaned = re.sub(r"\s+\n", "\n", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    def ask(self, question: str) -> dict[str, Any]:
        prompt = _ensure_text(question)
        if not prompt:
            raise ValueError("question must not be empty")
        state = self._load_state()
        recent_events = self.tail_events(limit=4)
        lens_refs: list[dict[str, Any]] = []
        if self.lens_store is not None:
            with contextlib.suppress(Exception):
                for item in self.lens_store.list(limit=8):
                    if str(item.get("stage") or "").startswith("atheria.als"):
                        lens_refs.append(item)
        atheria_hits: list[dict[str, Any]] = []
        if self.atheria_runtime is not None:
            with contextlib.suppress(Exception):
                atheria_hits = list(self.atheria_runtime.search_training(prompt, limit=4))
        provider, model = self._active_dialog_provider()
        answer_text = ""
        raw_payload: dict[str, Any] = {}
        if provider and self.ai_runtime is not None:
            evidence_bundle = {
                "question": prompt,
                "current_resonance": state.get("current_resonance", {}),
                "recent_events": recent_events,
                "atheria_hits": atheria_hits,
                "lens_refs": lens_refs[:4],
            }
            system_prompt = (
                "Du bist Atheria ALS. Antworte als laufende kognitive Instanz, nicht als generischer Chatbot. "
                "Nutze die Evidenzen, bleibe lokal begruendbar, benenne Unsicherheit explizit und antworte auf Deutsch "
                "in maximal zwei kurzen Saetzen. Gib keine JSON-Bloecke, keine internen Erinnerungen und keine "
                "Systemprompt-Wiederholung aus."
            )
            result = self.ai_runtime.complete_prompt(
                json.dumps(evidence_bundle, ensure_ascii=False, indent=2),
                provider=provider,
                model=model or None,
                system_prompt=system_prompt,
            )
            if result.error is None:
                raw_payload = dict(result.data or {})
                answer_text = self._normalize_dialog_answer(raw_payload.get("text") or result.output)
        if not answer_text:
            raw_payload = {"provider": provider or "heuristic", "model": model or "als-heuristic"}
            answer_text = self._heuristic_answer(prompt, recent_events)
        answer_text, risk_assessment, source_titles, focus_fields = self._render_dialog_answer(
            answer_text,
            resonance=dict(state.get("current_resonance") or {}),
            evidence=recent_events,
        )
        evidence_refs = [str(item.get("event_id") or "") for item in recent_events if str(item.get("event_id") or "").strip()]
        evidence_refs.extend(str(item.get("id") or "") for item in lens_refs[:4] if str(item.get("id") or "").strip())
        speech_act = self.voice_runtime.create_speech_act(
            mode="dialog",
            text=answer_text,
            evidence_refs=evidence_refs,
            resonance=dict(state.get("current_resonance") or {}),
            provider=str(raw_payload.get("provider") or provider or "heuristic"),
            model=str(raw_payload.get("model") or model or "als-heuristic"),
            audio_enabled=bool(self.load_config().get("voice", {}).get("audio_enabled", False)),
            voice_name=str(self.load_config().get("voice", {}).get("voice_name") or ""),
        )
        self._append_voice(speech_act, state)
        dialog_payload = {
            "dialog_id": f"als_dialog_{uuid.uuid4().hex[:12]}",
            "timestamp": time.time(),
            "timestamp_iso": _utc_now(),
            "kind": "ask",
            "question": prompt,
            "answer": answer_text,
            "provider": str(raw_payload.get("provider") or provider or "heuristic"),
            "model": str(raw_payload.get("model") or model or "als-heuristic"),
            "evidence_refs": evidence_refs,
            "dominant_topics": focus_fields,
            "risk_assessment": risk_assessment,
            "source_titles": source_titles,
            "atheria_hits": atheria_hits,
            "speech_act": speech_act,
        }
        self._append_dialog(dialog_payload, state)
        snapshot_id = self._record_lens_snapshot(
            "atheria.als.dialog.ask",
            output_text=answer_text,
            data_preview=json.dumps(dialog_payload, ensure_ascii=False, indent=2),
        )
        if snapshot_id:
            dialog_payload["lens_snapshot_id"] = snapshot_id
        self._save_state(state)
        return dialog_payload

    def feedback(self, text: str) -> dict[str, Any]:
        payload_text = _ensure_text(text)
        if not payload_text:
            raise ValueError("feedback must not be empty")
        state = self._load_state()
        inserted = 0
        if self.atheria_runtime is not None:
            with contextlib.suppress(Exception):
                inserted = int(self.atheria_runtime.train_rows([(f"Architect feedback {int(time.time())}", "architect_feedback", payload_text)]))
        answer = (
            "Feedback aufgenommen. Ich integriere die neue Hypothese in meine laufende Resonanzspur "
            "und nutze sie fuer kuenftige Stream-Bewertungen."
        )
        speech_act = self.voice_runtime.create_speech_act(
            mode="feedback",
            text=answer,
            evidence_refs=[],
            resonance=dict(state.get("current_resonance") or {}),
            provider="atheria",
            model="als-feedback",
            audio_enabled=bool(self.load_config().get("voice", {}).get("audio_enabled", False)),
            voice_name=str(self.load_config().get("voice", {}).get("voice_name") or ""),
        )
        self._append_voice(speech_act, state)
        dialog_payload = {
            "dialog_id": f"als_feedback_{uuid.uuid4().hex[:12]}",
            "timestamp": time.time(),
            "timestamp_iso": _utc_now(),
            "kind": "feedback",
            "feedback": payload_text,
            "inserted_rows": inserted,
            "answer": answer,
            "speech_act": speech_act,
        }
        self._append_dialog(dialog_payload, state)
        snapshot_id = self._record_lens_snapshot(
            "atheria.als.dialog.feedback",
            output_text=answer,
            data_preview=json.dumps(dialog_payload, ensure_ascii=False, indent=2),
        )
        if snapshot_id:
            dialog_payload["lens_snapshot_id"] = snapshot_id
        self._save_state(state)
        return dialog_payload

    def voice_status(self) -> dict[str, Any]:
        config = self.load_config()
        return {
            "enabled": bool(config.get("voice", {}).get("enabled", True)),
            "audio_enabled": bool(config.get("voice", {}).get("audio_enabled", False)),
            "voice_name": str(config.get("voice", {}).get("voice_name") or ""),
            "last_speech_act": self.last_voice(),
        }

    def voice_speak(self, text: str) -> dict[str, Any]:
        state = self._load_state()
        config = self.load_config()
        speech_act = self.voice_runtime.create_speech_act(
            mode="manual",
            text=text,
            evidence_refs=[],
            resonance=dict(state.get("current_resonance") or {}),
            provider="manual",
            model="manual-voice",
            audio_enabled=bool(config.get("voice", {}).get("audio_enabled", False)),
            voice_name=str(config.get("voice", {}).get("voice_name") or ""),
        )
        self._append_voice(speech_act, state)
        self._save_state(state)
        return speech_act

    def serve_forever(self, *, once: bool = False) -> int:
        config = self.configure({})
        self.stop_request_path.unlink(missing_ok=True)
        self.pid_path.write_text(str(os.getpid()), encoding="utf-8")
        self._append_audit_entry(
            "daemon_startup",
            market={
                "market_profile": "web_resonance_stream",
                "transport": "rss_stream",
                "trauma_pressure": 0.0,
                "recent_returns": {},
                "recent_volume_flux": {},
                "last_market_snapshot": {
                    "symbols": {},
                    "sensor_context": {
                        "als": {
                            "status": "startup",
                            "host": socket.gethostname(),
                            "topic": str(config.get("topic") or ""),
                            "web_search": dict(config.get("web_search") or {}),
                        }
                    },
                },
            },
            extra={
                "market_start": {
                    "transport": "rss_stream",
                    "host": socket.gethostname(),
                    "topic": str(config.get("topic") or ""),
                    "web_search": dict(config.get("web_search") or {}),
                }
            },
        )
        try:
            while True:
                self.run_cycle()
                if once:
                    break
                config = self.load_config()
                wait_seconds = max(3.0, _safe_float(config.get("interval_seconds"), 90.0))
                deadline = time.time() + wait_seconds
                while time.time() < deadline:
                    if self.stop_request_path.exists():
                        return 0
                    time.sleep(0.25)
        finally:
            self._append_audit_entry(
                "daemon_shutdown",
                market={
                    "market_profile": "web_resonance_stream",
                    "transport": "rss_stream",
                    "trauma_pressure": 0.0,
                    "recent_returns": {},
                    "recent_volume_flux": {},
                    "last_market_snapshot": {"symbols": {}, "sensor_context": {"als": {"status": "shutdown"}}},
                },
                extra={"shutdown": True},
            )
            self.pid_path.unlink(missing_ok=True)
            self.stop_request_path.unlink(missing_ok=True)
        return 0
