from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import os
import html
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Optional, Sequence, Tuple


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _format_timestamp(value: Any) -> str:
    stamp = _safe_float(value, 0.0)
    if stamp <= 0.0:
        return "unbekannte Zeit"
    return datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M:%S")


def _date_key(value: Any) -> str:
    stamp = _safe_float(value, 0.0)
    if stamp <= 0.0:
        return "unbekannt"
    return datetime.fromtimestamp(stamp).strftime("%Y-%m-%d")


def _tail_slice(items: Iterable[Any], count: int) -> list[float]:
    raw = list(items)
    if count <= 0:
        return []
    return [_safe_float(item) for item in raw[-count:]]


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _load_lines(path: Path) -> list[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[Dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _latest_resonance_invariant(report_root: Path) -> Optional[Dict[str, Any]]:
    core_audit_root = report_root / "core_audit"
    if not core_audit_root.exists():
        return None

    latest: Optional[Dict[str, Any]] = None
    latest_stamp = 0.0
    for path in sorted(core_audit_root.glob("*_inter_core_resonance.jsonl")):
        for row in _load_lines(path):
            invariant = dict(row.get("invariant") or {})
            if not invariant:
                continue
            details = dict(invariant.get("details") or {})
            stamp = _safe_float(row.get("timestamp") or invariant.get("timestamp"), 0.0)
            if stamp < latest_stamp:
                continue
            latest_stamp = stamp
            latest = {
                "timestamp": stamp,
                "statement": str(invariant.get("statement") or "Unbenannte Inter-Core-Invariante"),
                "confidence": _safe_float(invariant.get("confidence"), 0.0),
                "mean_effect_size": _safe_float(
                    details.get("mean_effect_size", invariant.get("mean_effect_size")),
                    0.0,
                ),
                "samples": max(
                    0,
                    int(_safe_float(details.get("samples", invariant.get("samples")), 0.0)),
                ),
                "observer_label": str(row.get("observer_label") or details.get("observer_label") or ""),
                "trigger_asset": str(details.get("trigger_asset") or row.get("trigger_asset") or ""),
                "target_asset": str(details.get("target_asset") or row.get("target_asset") or ""),
                "lag_minutes": _safe_float(details.get("lag_minutes", row.get("lag_minutes")), 0.0),
                "source_file": path.name,
            }
    return latest


class SignatureResolver:
    def __init__(self, report_root: Path) -> None:
        self.report_root = report_root
        self.core_audit_root = report_root / "core_audit"
        self._cache: Dict[Tuple[str, str], Optional[bytes]] = {}

    def _derived_key_from_file(self, path: Path) -> Optional[Tuple[bytes, str]]:
        if not path.exists():
            return None
        seed = path.read_text(encoding="utf-8").strip()
        if not seed:
            return None
        base = seed.encode("utf-8")
        derived = hashlib.sha256(base + b"|atheria-daemon").digest()
        fingerprint = hashlib.sha1(derived).hexdigest()[:12]
        return derived, fingerprint

    def resolve(self, *, core_id: str, fingerprint: str) -> Optional[bytes]:
        cache_key = (str(core_id), str(fingerprint))
        if cache_key in self._cache:
            return self._cache[cache_key]

        primary = self.core_audit_root / f"{str(core_id).lower()}_audit.key"
        candidate = self._derived_key_from_file(primary)
        if candidate is not None and candidate[1] == str(fingerprint):
            self._cache[cache_key] = candidate[0]
            return candidate[0]

        if self.core_audit_root.exists():
            for path in sorted(self.core_audit_root.glob("*_audit.key")):
                candidate = self._derived_key_from_file(path)
                if candidate is not None and candidate[1] == str(fingerprint):
                    self._cache[cache_key] = candidate[0]
                    return candidate[0]

        self._cache[cache_key] = None
        return None


def _verify_entry(entry: Dict[str, Any], *, key: Optional[bytes], expected_previous: Optional[str]) -> Dict[str, Any]:
    report = {
        "key_available": bool(key),
        "signature_ok": False,
        "chain_ok": True,
        "chain_reset": False,
        "verified": False,
    }

    if expected_previous is not None:
        current_previous = str(entry.get("previous") or "")
        report["chain_ok"] = current_previous == str(expected_previous)
        if not report["chain_ok"]:
            if current_previous == "GENESIS" and str(entry.get("reason") or "") == "daemon_startup":
                report["chain_ok"] = True
                report["chain_reset"] = True

    if key is None:
        return report

    signature = str(entry.get("journal_signature") or "")
    entry_payload = {
        key_name: value
        for key_name, value in entry.items()
        if key_name not in {"previous", "journal_signature", "journal_key_fingerprint"}
    }
    payload = {
        "previous": str(entry.get("previous") or ""),
        "entry": entry_payload,
    }
    digest = hmac.new(key, _stable_json(payload).encode("utf-8"), hashlib.sha256).hexdigest()
    report["signature_ok"] = digest == signature
    report["verified"] = bool(report["signature_ok"] and report["chain_ok"])
    return report


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / max(1, len(values))


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    variance = sum((item - mean) ** 2 for item in values) / float(len(values))
    return math.sqrt(max(0.0, variance))


def _inverse_correlation(lead: list[float], follow: list[float]) -> float:
    count = min(len(lead), len(follow))
    if count < 2:
        return 0.0
    left = lead[-count:]
    right = follow[-count:]
    left_mean = _mean(left)
    right_mean = _mean(right)
    left_std = _std(left)
    right_std = _std(right)
    if left_std <= 1e-8 or right_std <= 1e-8:
        return 0.0
    covariance = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right)) / float(count)
    corr = covariance / (left_std * right_std)
    return max(0.0, -corr)


def _market_profile(market: Dict[str, Any]) -> str:
    text = str(market.get("market_profile") or "").strip().lower()
    if text:
        return text
    trauma = dict(market.get("last_trauma_event") or {})
    text = str(trauma.get("market_profile") or "").strip().lower()
    return text or "market"


def _market_anchor_asset(market: Dict[str, Any]) -> str:
    trauma = dict(market.get("last_trauma_event") or {})
    anchor = str(trauma.get("anchor_asset") or "").strip().upper()
    if anchor:
        return anchor

    returns = dict(market.get("recent_returns") or {})
    latest_symbols = dict((dict(market.get("last_market_snapshot") or {}).get("symbols") or {}))
    for candidate in ("SP500", "DAX", "NASDAQ", "DOW", "RUSSELL", "SOFTWARE", "BTC", "ETH", "BNB", "SOL"):
        if candidate in returns or candidate in latest_symbols:
            return candidate
    if returns:
        return sorted(str(key) for key in returns.keys())[0]
    if latest_symbols:
        return sorted(str(key) for key in latest_symbols.keys())[0]
    return "BTC"


def _market_sensor_context(market: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = dict(market.get("last_market_snapshot") or {})
    return dict(snapshot.get("sensor_context") or {})


def _macro_release_hint(market: Dict[str, Any]) -> Optional[str]:
    sensors = _market_sensor_context(market)
    macro = dict(sensors.get("macro") or {})
    releases = list(macro.get("upcoming_releases") or [])
    if not releases:
        return None
    first = dict(releases[0] or {})
    name = str(first.get("name") or "").strip()
    hours = _safe_float(first.get("hours_to_release"), -1.0)
    if not name:
        return None
    if hours >= 0.0:
        return f"Naechster Makro-Trigger: {name} in {hours:.1f}h."
    return f"Naechster Makro-Trigger: {name}."


def _sector_rotation_hint(market: Dict[str, Any]) -> Optional[str]:
    sensors = _market_sensor_context(market)
    sector = dict(sensors.get("sector_rotation") or {})
    if not bool(sector.get("available")):
        return None
    bias = str(sector.get("rotation_bias") or "").strip().lower()
    score = _safe_float(sector.get("rotation_score"), 0.0)
    if not bias:
        return None
    return f"Sektor-Rotation: {bias} (Score {score:.2f})."


def _candidate_assets(market: Dict[str, Any], *, anchor_asset: str) -> list[str]:
    returns = dict(market.get("recent_returns") or {})
    volume_flux = dict(market.get("recent_volume_flux") or {})
    profile = _market_profile(market)
    preferred = (
        ["VIX", "MOVE", "GOLD", "OIL", "UTILITIES", "ENERGY", "DAX", "NASDAQ", "DOW", "RUSSELL", "SOFTWARE"]
        if profile == "finance"
        else ["ETH", "BNB", "SOL"]
    )

    ordered: list[str] = []
    seen: set[str] = set()
    for asset in list(preferred) + sorted({str(key) for key in returns.keys()} | {str(key) for key in volume_flux.keys()}):
        label = str(asset).strip().upper()
        if not label or label == str(anchor_asset).strip().upper() or label in seen:
            continue
        seen.add(label)
        ordered.append(label)
    return ordered


def _infer_discovery(entry: Dict[str, Any]) -> Optional[str]:
    market = dict(entry.get("market") or {})
    returns = dict(market.get("recent_returns") or {})
    volume_flux = dict(market.get("recent_volume_flux") or {})
    anchor_asset = _market_anchor_asset(market)
    anchor = [_safe_float(item) for item in returns.get(anchor_asset, [])]
    if len(anchor) < 3:
        return None

    follow = anchor[1:]
    best_asset = None
    best_score = 0.0
    best_support = 0.0

    for asset in _candidate_assets(market, anchor_asset=anchor_asset):
        lead_asset = [_safe_float(item) for item in returns.get(asset, [])]
        if len(lead_asset) < 3:
            continue
        lead = lead_asset[:-1]
        inverse = _inverse_correlation(lead, follow)
        flux = [_safe_float(item) for item in volume_flux.get(asset, [])]
        flux_tail = _tail_slice(flux, 3)
        if flux_tail:
            abs_mean = _mean([abs(item) for item in flux_tail])
            if abs_mean > 1e-8:
                support = max(0.0, _mean([max(0.0, item / abs_mean) for item in flux_tail]))
            else:
                support = 0.0
        else:
            support = 0.0
        score = inverse * 0.8 + min(1.0, support) * 0.2
        if score > best_score:
            best_asset = asset
            best_score = score
            best_support = min(1.0, support)

    if best_asset is None or best_score < 0.18:
        return None

    return (
        f"Letzte Entdeckung: inverse Leitbewegung {anchor_asset}/{best_asset} "
        f"(lag 1, Stärke {best_score:.2f}, Volumenstütze {best_support:.2f}) um {_format_timestamp(entry.get('timestamp'))}."
    )


def _verification_label(report: Dict[str, Any]) -> str:
    if report.get("chain_reset", False):
        if report["verified"]:
            return "Neuer Zyklus, Signatur verifiziert"
        if report["key_available"]:
            return "Neuer Zyklus, Signatur ungueltig"
        return "Neuer Zyklus"
    if report["verified"]:
        return "Signatur verifiziert"
    if report["key_available"] and not report["chain_ok"]:
        return "Kette gebrochen"
    if report["key_available"]:
        return "Signatur ungueltig"
    if not report["chain_ok"]:
        return "Kette unpruefbar"
    return "Signatur nicht pruefbar"


def _verification_tone(report: Dict[str, Any]) -> str:
    if report.get("chain_reset", False):
        return "reset"
    if report.get("verified", False):
        return "ok"
    if report.get("key_available", False) and not report.get("chain_ok", True):
        return "bad"
    if report.get("key_available", False):
        return "warn"
    if not report.get("chain_ok", True):
        return "warn"
    return "muted"


def _reason_summary(entry: Dict[str, Any]) -> str:
    reason = str(entry.get("reason") or "unbekannt")
    dashboard = dict(entry.get("dashboard") or {})
    market = dict(entry.get("market") or {})
    lineage = dict(entry.get("lineage") or {})
    extra = dict(entry.get("extra") or {})

    temperature = _safe_float(dashboard.get("system_temperature"), 0.0)
    resources = _safe_float(dashboard.get("resource_pool"), 0.0)
    trauma = _safe_float(market.get("trauma_pressure"), 0.0)
    recommended = str(lineage.get("recommended_profile") or "keine Empfehlung")
    market_profile = _market_profile(market)
    anchor_asset = _market_anchor_asset(market)

    if reason == "daemon_startup":
        market_start = dict(extra.get("market_start") or {})
        transport = str(market_start.get("transport") or market.get("transport") or "unbekannt")
        return (
            f"ATHERIA erwachte und band sich an den Markt (Profil: {market_profile}, Transport: {transport}). "
            f"Temperatur {temperature:.2f}, Ressourcen {resources:.2f}."
        )

    if reason == "scheduled_integrity_audit":
        base = (
            f"Regelmaessiger Integritaetsblick: Temperatur {temperature:.2f}, "
            f"Ressourcen {resources:.2f}, Trauma-Druck {trauma:.2f}, "
            f"Lineage-Profil {recommended}, Marktprofil {market_profile}."
        )
        hints: list[str] = []
        macro_hint = _macro_release_hint(market)
        if macro_hint:
            hints.append(macro_hint)
        sector_hint = _sector_rotation_hint(market)
        if sector_hint:
            hints.append(sector_hint)
        if hints:
            return base + " " + " ".join(hints)
        return base

    if reason == "market_alert":
        anomaly = dict(extra.get("anomaly") or {})
        observed_asset = str(anomaly.get("anchor_asset") or anchor_asset or "MARKT")
        observed_return = _safe_float(
            anomaly.get("anchor_recent_return"),
            _safe_float(anomaly.get("btc_recent_return"), 0.0),
        )
        base = (
            f"Das Marktrauschen nahm zu. Trauma-Druck {trauma:.2f}, "
            f"{observed_asset}-Rendite {observed_return:.3f}, ATHERIA beobachtet weiter."
        )
        hints: list[str] = []
        macro_hint = _macro_release_hint(market)
        if macro_hint:
            hints.append(macro_hint)
        sector_hint = _sector_rotation_hint(market)
        if sector_hint:
            hints.append(sector_hint)
        if hints:
            return base + " " + " ".join(hints)
        return base

    if reason.startswith("market_anomaly::"):
        profile = reason.split("::", 1)[1] if "::" in reason else "unbekannt"
        generation = dict(extra.get("generation_trigger") or {})
        child = str(generation.get("child_name") or "unbenanntes Offspring")
        anomaly = dict(generation.get("anomaly") or {})
        observed_asset = str(anomaly.get("anchor_asset") or anchor_asset or "MARKT")
        return (
            f"Eine schwere Marktanomalie loeste eine neue Generation aus. "
            f"Kind {child} startet mit Profil {profile}. "
            f"Leitachse {observed_asset}, Trauma-Druck {trauma:.2f}."
        )

    if reason == "daemon_shutdown":
        return "Der Daemon zog sich geordnet zurueck und schloss seine Chronik fuer diesen Lauf."

    return (
        f"Ein unbekannter Zustand wurde notiert ({reason}). "
        f"Temperatur {temperature:.2f}, Ressourcen {resources:.2f}, Trauma-Druck {trauma:.2f}."
    )


def format_diary_entry(entry: Dict[str, Any], *, verification: Dict[str, Any]) -> str:
    lines = [
        f"[{_format_timestamp(entry.get('timestamp'))}] {_reason_summary(entry)} {_verification_label(verification)}.",
    ]
    discovery = _infer_discovery(entry)
    if discovery:
        lines.append(discovery)
    return "\n".join(lines)


def _entry_record(entry: Dict[str, Any], *, verification: Dict[str, Any]) -> Dict[str, Any]:
    discovery = _infer_discovery(entry)
    return {
        "entry": entry,
        "verification": verification,
        "timestamp": _safe_float(entry.get("timestamp"), 0.0),
        "date": _date_key(entry.get("timestamp")),
        "reason": str(entry.get("reason") or "unbekannt"),
        "text": format_diary_entry(entry, verification=verification),
        "summary": _reason_summary(entry),
        "discovery": discovery,
    }


def _analyze_entries(
    entries: list[Dict[str, Any]],
    *,
    resolver: SignatureResolver,
    verify: bool,
    expected_previous: Optional[str] = None,
) -> tuple[list[Dict[str, Any]], Optional[str]]:
    previous_signature = expected_previous
    records: list[Dict[str, Any]] = []
    for entry in entries:
        key = None
        if verify:
            key = resolver.resolve(
                core_id=str(entry.get("core_id") or ""),
                fingerprint=str(entry.get("journal_key_fingerprint") or ""),
            )
        verification = _verify_entry(entry, key=key, expected_previous=previous_signature) if verify else {
            "key_available": False,
            "signature_ok": False,
            "chain_ok": True,
            "chain_reset": False,
            "verified": False,
        }
        records.append(_entry_record(entry, verification=verification))
        previous_signature = str(entry.get("journal_signature") or previous_signature or "")
    return records, previous_signature


def _daily_summaries(records: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for record in records:
        day = str(record["date"])
        bucket = grouped.get(day)
        if bucket is None:
            bucket = {
                "date": day,
                "entries": 0,
                "startups": 0,
                "shutdowns": 0,
                "scheduled_audits": 0,
                "market_alerts": 0,
                "anomalies": 0,
                "verified": 0,
                "resets": 0,
                "best_discovery": None,
                "best_discovery_score": 0.0,
                "max_trauma": 0.0,
                "last_entry": record,
            }
            grouped[day] = bucket

        entry = dict(record["entry"])
        verification = dict(record["verification"])
        reason = str(record["reason"])
        bucket["entries"] += 1
        bucket["last_entry"] = record

        if reason == "daemon_startup":
            bucket["startups"] += 1
        elif reason == "daemon_shutdown":
            bucket["shutdowns"] += 1
        elif reason == "scheduled_integrity_audit":
            bucket["scheduled_audits"] += 1
        elif reason == "market_alert":
            bucket["market_alerts"] += 1
        elif reason.startswith("market_anomaly::"):
            bucket["anomalies"] += 1

        if verification.get("verified", False):
            bucket["verified"] += 1
        if verification.get("chain_reset", False):
            bucket["resets"] += 1

        trauma = _safe_float(dict(entry.get("market") or {}).get("trauma_pressure"), 0.0)
        bucket["max_trauma"] = max(float(bucket["max_trauma"]), trauma)

        discovery = record.get("discovery")
        if discovery:
            score = 0.0
            marker = "Stärke "
            if marker in discovery:
                tail = discovery.split(marker, 1)[1]
                number = tail.split(",", 1)[0].strip().replace(",", ".")
                score = _safe_float(number, 0.0)
            if score >= float(bucket["best_discovery_score"]):
                bucket["best_discovery"] = str(discovery)
                bucket["best_discovery_score"] = score

    ordered = sorted(grouped.values(), key=lambda item: item["date"])
    return ordered


def _summary_line(summary: Dict[str, Any]) -> str:
    parts = [
        f"{summary['date']}: {summary['entries']} Eintraege",
        f"{summary['startups']} Start",
        f"{summary['shutdowns']} Stop",
        f"{summary['scheduled_audits']} Audits",
        f"{summary['market_alerts']} Alerts",
        f"{summary['anomalies']} Anomalien",
        f"max. Trauma {float(summary['max_trauma']):.2f}",
    ]
    if summary.get("best_discovery"):
        parts.append("Entdeckung vorhanden")
    if int(summary.get("resets", 0)) > 0:
        parts.append(f"{summary['resets']} Neustart-Zyklus")
    return " | ".join(parts)


def _render_summary_block(records: list[Dict[str, Any]]) -> str:
    summaries = _daily_summaries(records)
    if not summaries:
        return "Keine Tageszusammenfassung verfuegbar."

    lines = ["Tageszusammenfassung"]
    for summary in summaries:
        lines.append(_summary_line(summary))
        discovery = summary.get("best_discovery")
        if discovery:
            lines.append(f"  {discovery}")
    return "\n".join(lines)


_ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "cyan": "\033[36m",
    "white": "\033[37m",
}


def _supports_color() -> bool:
    term = str(os.environ.get("TERM", "")).lower()
    return sys.stdout.isatty() and term not in {"", "dumb"}


def _color(text: str, *styles: str, enabled: bool) -> str:
    if not enabled:
        return text
    prefix = "".join(_ANSI.get(style, "") for style in styles)
    return f"{prefix}{text}{_ANSI['reset']}"


def _render_tui(records: list[Dict[str, Any]], *, limit: int) -> str:
    color_enabled = _supports_color()
    recent = records[-max(1, int(limit)) :] if records else []
    summaries = _daily_summaries(records)
    latest = recent[-1] if recent else None

    lines = []
    lines.append(_color("Aion-Chronik", "bold", "cyan", enabled=color_enabled))
    lines.append(_color("=" * 72, "dim", enabled=color_enabled))

    if latest is not None:
        lines.append(
            _color("Letzter Zustand", "bold", "white", enabled=color_enabled)
            + ": "
            + _color(latest["summary"], "blue", enabled=color_enabled)
        )
        if latest.get("discovery"):
            lines.append(_color(str(latest["discovery"]), "yellow", enabled=color_enabled))
        lines.append("")

    lines.append(_color("Tageszusammenfassung", "bold", "white", enabled=color_enabled))
    if summaries:
        for summary in summaries:
            tone = "green"
            if int(summary.get("anomalies", 0)) > 0:
                tone = "red"
            elif int(summary.get("market_alerts", 0)) > 0:
                tone = "yellow"
            elif int(summary.get("resets", 0)) > 0:
                tone = "cyan"
            lines.append(_color(_summary_line(summary), tone, enabled=color_enabled))
            if summary.get("best_discovery"):
                lines.append(_color(f"  {summary['best_discovery']}", "dim", enabled=color_enabled))
    else:
        lines.append(_color("Keine Daten", "dim", enabled=color_enabled))

    lines.append("")
    lines.append(_color(f"Letzte {len(recent)} Tagebucheintraege", "bold", "white", enabled=color_enabled))
    for record in recent:
        tone_map = {
            "ok": ("green",),
            "reset": ("cyan",),
            "warn": ("yellow",),
            "bad": ("red",),
            "muted": ("dim",),
        }
        tone = tone_map.get(_verification_tone(dict(record["verification"])), ("white",))
        for idx, line in enumerate(str(record["text"]).splitlines()):
            prefix = "  " if idx > 0 else ""
            lines.append(prefix + _color(line, *tone, enabled=color_enabled))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_html(
    records: list[Dict[str, Any]],
    *,
    title: str = "Aion-Chronik",
    report_root: Optional[Path] = None,
) -> str:
    summaries = _daily_summaries(records)
    latest = records[-1] if records else None
    resonance = _latest_resonance_invariant(report_root) if report_root is not None else None
    default_report_dir = (
        str(report_root).replace("\\", "/") if report_root is not None else "daemon_runtime"
    )

    def esc(value: Any) -> str:
        return html.escape(str(value), quote=True)

    summary_cards = []
    for summary in summaries:
        badge_class = "ok"
        if int(summary.get("anomalies", 0)) > 0:
            badge_class = "bad"
        elif int(summary.get("market_alerts", 0)) > 0:
            badge_class = "warn"
        elif int(summary.get("resets", 0)) > 0:
            badge_class = "reset"
        discovery_html = ""
        if summary.get("best_discovery"):
            discovery_html = f"<p class=\"discovery\">{esc(summary['best_discovery'])}</p>"
        summary_cards.append(
            (
                "<section class=\"card\">"
                f"<div class=\"badge {badge_class}\">{esc(summary['date'])}</div>"
                f"<p>{esc(_summary_line(summary))}</p>"
                f"{discovery_html}"
                "</section>"
            )
        )

    entry_blocks = []
    for record in records:
        tone = _verification_tone(dict(record["verification"]))
        discovery_html = ""
        if record.get("discovery"):
            discovery_html = f"<p class=\"discovery\">{esc(record['discovery'])}</p>"
        entry_blocks.append(
            (
                f"<article class=\"entry {tone}\">"
                f"<h3>{esc(_format_timestamp(record['timestamp']))}</h3>"
                f"<p>{esc(record['summary'])}</p>"
                f"<p class=\"verify\">{esc(_verification_label(dict(record['verification'])))}</p>"
                f"{discovery_html}"
                "</article>"
            )
        )

    latest_html = ""
    if latest is not None:
        latest_html = (
            "<section class=\"hero\">"
            "<div class=\"hero-kicker\">Letzter Zustand</div>"
            f"<h1>{esc(latest['summary'])}</h1>"
            f"<p>{esc(_verification_label(dict(latest['verification'])))}</p>"
            + (f"<p class=\"discovery\">{esc(latest['discovery'])}</p>" if latest.get("discovery") else "")
            + "</section>"
        )

    resonance_html = ""
    if report_root is not None:
        if resonance is None:
            resonance_html = (
                "<div class=\"section-title\">Inter-Core-Resonanz</div>"
                "<div class=\"grid\">"
                "<section class=\"card\" id=\"chronik-resonance-card\">"
                "<div class=\"badge reset\" id=\"chronik-resonance-badge\">Wartet</div>"
                "<p id=\"chronik-resonance-statement\">Noch keine gelernte Invariante im Resonanz-Journal gefunden.</p>"
                "<p class=\"verify\" id=\"chronik-resonance-meta\">Erwartet unter core_audit/*_inter_core_resonance.jsonl</p>"
                "<p class=\"verify\" id=\"chronik-resonance-source\"></p>"
                "</section>"
                "</div>"
            )
        else:
            resonance_badge = "ok" if float(resonance["confidence"]) >= 0.75 else "warn"
            resonance_bits = []
            if resonance.get("trigger_asset") and resonance.get("target_asset"):
                resonance_bits.append(
                    f"Pfad {resonance['trigger_asset']} -> {resonance['target_asset']}"
                )
            if float(resonance.get("lag_minutes", 0.0)) > 0.0:
                resonance_bits.append(f"Lag {resonance['lag_minutes']:.0f} min")
            resonance_bits.append(f"Confidence {float(resonance['confidence']):.2f}")
            resonance_bits.append(f"Effekt {float(resonance['mean_effect_size']):.3f}")
            if int(resonance.get("samples", 0)) > 0:
                resonance_bits.append(f"Samples {int(resonance['samples'])}")
            if resonance.get("observer_label"):
                resonance_bits.append(f"Beobachter {resonance['observer_label']}")
            resonance_bits.append(f"Stand {_format_timestamp(resonance['timestamp'])}")
            resonance_html = (
                "<div class=\"section-title\">Inter-Core-Resonanz</div>"
                "<div class=\"grid\">"
                "<section class=\"card\" id=\"chronik-resonance-card\">"
                f"<div class=\"badge {resonance_badge}\" id=\"chronik-resonance-badge\">Invariante</div>"
                f"<p id=\"chronik-resonance-statement\">{esc(resonance['statement'])}</p>"
                f"<p class=\"discovery\" id=\"chronik-resonance-meta\">{esc(' | '.join(resonance_bits))}</p>"
                f"<p class=\"verify\" id=\"chronik-resonance-source\">Quelle: {esc(resonance['source_file'])}</p>"
                "</section>"
                "</div>"
            )

    query_script = (
        r"""
  <script>
    (function () {
      var defaultReportDir = "__DEFAULT_REPORT_DIR__";
      var reportDir = resolveReportDir(defaultReportDir);
      var navChronik = document.getElementById("nav-chronik");
      var navFinance = document.getElementById("nav-finance");
      var topbarNote = document.getElementById("topbar-note");
      var resonanceBadge = document.getElementById("chronik-resonance-badge");
      var resonanceStatement = document.getElementById("chronik-resonance-statement");
      var resonanceMeta = document.getElementById("chronik-resonance-meta");
      var resonanceSource = document.getElementById("chronik-resonance-source");

      function resolveReportDir(fallback) {
        var raw = "";
        try {
          raw = String(new URLSearchParams(window.location.search).get("reportDir") || "");
        } catch (error) {
          raw = "";
        }
        raw = raw.trim().replace(/\\/g, "/");
        raw = raw.split("/").filter(function (part) {
          return part && part !== "." && part !== "..";
        }).join("/");
        return raw || fallback;
      }

      function parseLatestJsonLine(text) {
        var lines = String(text || "").split(/\r?\n/);
        for (var index = lines.length - 1; index >= 0; index -= 1) {
          var line = lines[index].trim();
          if (!line) {
            continue;
          }
          try {
            return JSON.parse(line);
          } catch (error) {
            continue;
          }
        }
        return null;
      }

      function toFetchUrl(path) {
        var value = String(path || "").trim();
        if (!value) {
          return value;
        }
        value = value.replace(/\\/g, "/");
        if (/^[a-z]+:\/\/?/i.test(value) || value.indexOf("file:///") === 0) {
          return value;
        }
        if (/^[A-Za-z]:\//.test(value)) {
          return "file:///" + encodeURI(value).replace(/#/g, "%23");
        }
        if (value.charAt(0) === "/") {
          return "file://" + encodeURI(value).replace(/#/g, "%23");
        }
        return value;
      }

      function setBadge(tone, text) {
        if (!resonanceBadge) {
          return;
        }
        resonanceBadge.className = "badge " + tone;
        resonanceBadge.textContent = text;
      }

      function applyViewContext(activeReportDir) {
        var suffix = activeReportDir === defaultReportDir
          ? ""
          : ("?reportDir=" + encodeURIComponent(activeReportDir));
        if (navChronik) {
          navChronik.href = "chronik.html" + suffix;
        }
        if (navFinance) {
          navFinance.href = "finance_dashboard.html" + suffix;
        }
        if (topbarNote) {
          if (activeReportDir === defaultReportDir) {
            topbarNote.textContent = "Verknuepft mit der Finance-Ansicht | Report-Root " + activeReportDir;
          } else {
            topbarNote.textContent =
              "Statische Chronik aus " + defaultReportDir + " | Resonanz-Overlay liest " + activeReportDir;
          }
        }
      }

      function setResonanceFallback(message, activeReportDir) {
        setBadge("reset", "Wartet");
        if (resonanceStatement) {
          resonanceStatement.textContent = message;
        }
        if (resonanceMeta) {
          resonanceMeta.textContent =
            "Erwartet unter " + activeReportDir + "/core_audit/<core_id>_inter_core_resonance.jsonl";
        }
        if (resonanceSource) {
          resonanceSource.textContent = "";
        }
      }

      function updateResonance(record, resonanceFile) {
        if (!record || !record.invariant) {
          setResonanceFallback("Resonanz-Datei gefunden, aber noch ohne auswertbare Invariante.", reportDir);
          return;
        }
        var invariant = record.invariant || {};
        var confidence = Number(invariant.confidence || 0);
        var tone = confidence >= 0.75 ? "ok" : "warn";
        var triggerAsset = String(invariant.trigger_asset || "MARKET");
        var targetAsset = String(invariant.target_asset || "BTC");
        var lagMinutes = Number(invariant.lag_minutes || 0);
        var effectSize = Number(invariant.mean_effect_size || 0);
        var samples = Math.round(Number(invariant.samples || 0));
        setBadge(tone, "Invariante");
        if (resonanceStatement) {
          resonanceStatement.textContent = String(
            invariant.statement ||
            ("Wenn " + triggerAsset + " triggert, reagiert " + targetAsset + " nach " + lagMinutes + " Minuten.")
          );
        }
        if (resonanceMeta) {
          resonanceMeta.textContent =
            "Confidence " + Math.round(confidence * 100) + "%, Effekt " + effectSize.toFixed(3) +
            ", Samples " + samples + ", Lag " + lagMinutes.toFixed(0) + " min.";
        }
        if (resonanceSource) {
          resonanceSource.textContent = "Quelle: " + resonanceFile;
        }
      }

      function loadResonance(activeReportDir) {
        var auditFile = activeReportDir + "/atheria_daemon_audit.jsonl";
        fetch(toFetchUrl(auditFile), { cache: "no-store" })
          .then(function (response) {
            if (!response.ok) {
              throw new Error("HTTP " + response.status);
            }
            return response.text();
          })
          .then(function (text) {
            var entry = parseLatestJsonLine(text);
            var coreId = String(entry && entry.core_id || "").trim().toLowerCase();
            if (!coreId) {
              setResonanceFallback(
                "Kein `core_id` im Daemon-Report gefunden. Resonanz-Journal kann nicht aufgeloest werden.",
                activeReportDir
              );
              return;
            }
            var resonanceFile = activeReportDir + "/core_audit/" + coreId + "_inter_core_resonance.jsonl";
            return fetch(toFetchUrl(resonanceFile), { cache: "no-store" })
              .then(function (resonanceResponse) {
                if (!resonanceResponse.ok) {
                  throw new Error("HTTP " + resonanceResponse.status);
                }
                return resonanceResponse.text();
              })
              .then(function (resonanceText) {
                updateResonance(parseLatestJsonLine(resonanceText), resonanceFile);
              });
          })
          .catch(function () {
            setResonanceFallback(
              "Resonanz-Overlay konnte fuer den gewaehlten Report-Root nicht geladen werden.",
              activeReportDir
            );
          });
      }

      applyViewContext(reportDir);
      loadResonance(reportDir);
    }());
  </script>
"""
        .replace("__DEFAULT_REPORT_DIR__", esc(default_report_dir))
    )

    return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <style>
    :root {{
      --bg: #f6f1e8;
      --paper: #fffdf8;
      --ink: #18222d;
      --muted: #66727f;
      --line: #d8cdbd;
      --ok: #2c7a4b;
      --warn: #b7791f;
      --bad: #a43636;
      --reset: #0f6b78;
      --accent: #d7b66f;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      background:
        radial-gradient(circle at top right, rgba(215,182,111,0.28), transparent 32%),
        linear-gradient(180deg, #efe4cf, var(--bg));
      color: var(--ink);
    }}
    .wrap {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 32px 20px 64px;
    }}
    .topbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 18px;
      padding: 10px 14px;
      border-radius: 16px;
      border: 1px solid var(--line);
      background: rgba(255,253,248,0.82);
      box-shadow: 0 10px 24px rgba(24,34,45,0.05);
    }}
    .nav-links {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .nav-link {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 38px;
      padding: 8px 14px;
      border-radius: 999px;
      border: 1px solid rgba(24,34,45,0.08);
      color: var(--ink);
      text-decoration: none;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 0.76rem;
      font-weight: 700;
      background: rgba(24,34,45,0.03);
    }}
    .nav-link.active {{
      color: #f8f2e7;
      background: linear-gradient(135deg, rgba(24,34,45,0.95), rgba(15,107,120,0.92));
      border-color: rgba(255,248,231,0.08);
    }}
    .topbar-note {{
      font-size: 0.82rem;
      color: var(--muted);
    }}
    .hero {{
      background: linear-gradient(135deg, rgba(24,34,45,0.95), rgba(15,107,120,0.92));
      color: #f8f2e7;
      padding: 28px;
      border-radius: 18px;
      box-shadow: 0 20px 40px rgba(24,34,45,0.18);
      margin-bottom: 28px;
    }}
    .hero-kicker {{
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-size: 0.78rem;
      opacity: 0.78;
    }}
    h1, h2, h3 {{ margin: 0 0 10px; line-height: 1.15; }}
    h1 {{ font-size: clamp(1.7rem, 3vw, 2.7rem); }}
    h2 {{ font-size: 1.3rem; margin-bottom: 16px; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 16px;
      margin-bottom: 32px;
    }}
    .card, .entry {{
      background: rgba(255,253,248,0.92);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 18px;
      box-shadow: 0 10px 24px rgba(24,34,45,0.06);
    }}
    .badge {{
      display: inline-block;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 0.76rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      margin-bottom: 10px;
      background: rgba(24,34,45,0.08);
    }}
    .badge.ok, .entry.ok .verify {{ color: var(--ok); }}
    .badge.warn, .entry.warn .verify {{ color: var(--warn); }}
    .badge.bad, .entry.bad .verify {{ color: var(--bad); }}
    .badge.reset, .entry.reset .verify {{ color: var(--reset); }}
    .entry-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
    }}
    .entry.ok {{ border-left: 5px solid var(--ok); }}
    .entry.warn {{ border-left: 5px solid var(--warn); }}
    .entry.bad {{ border-left: 5px solid var(--bad); }}
    .entry.reset {{ border-left: 5px solid var(--reset); }}
    .entry.muted {{ border-left: 5px solid var(--muted); }}
    .verify {{
      font-size: 0.9rem;
      font-weight: 700;
    }}
    .discovery {{
      color: #5f4312;
      background: rgba(215,182,111,0.16);
      border-radius: 12px;
      padding: 10px 12px;
    }}
    .section-title {{
      margin: 26px 0 14px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 0.76rem;
      font-weight: 700;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <nav class="topbar" aria-label="Ansichten">
      <div class="nav-links">
        <a class="nav-link active" id="nav-chronik" href="chronik.html">Chronik</a>
        <a class="nav-link" id="nav-finance" href="finance_dashboard.html">Atheria-Finance</a>
      </div>
      <div class="topbar-note" id="topbar-note">Verknuepft mit der Finance-Ansicht</div>
    </nav>
    {latest_html}
    {resonance_html}
    <div class="section-title">Tageszusammenfassung</div>
    <div class="grid">
      {''.join(summary_cards) if summary_cards else '<section class="card"><p>Keine Zusammenfassung verfuegbar.</p></section>'}
    </div>
    <div class="section-title">Chronik</div>
    <div class="entry-grid">
      {''.join(entry_blocks) if entry_blocks else '<article class="entry muted"><p>Keine Eintraege verfuegbar.</p></article>'}
    </div>
  </div>
  {query_script}
</body>
</html>
"""


def _default_report_path(report_dir: Path) -> Path:
    return report_dir / "atheria_daemon_audit.jsonl"


def _iter_new_entries(path: Path, *, start_at_end: bool, poll_seconds: float) -> Iterator[Dict[str, Any]]:
    position = 0
    if start_at_end and path.exists():
        position = path.stat().st_size

    while True:
        if not path.exists():
            time.sleep(max(0.1, poll_seconds))
            continue

        with path.open("r", encoding="utf-8") as handle:
            handle.seek(position)
            while True:
                raw = handle.readline()
                if not raw:
                    position = handle.tell()
                    break
                position = handle.tell()
                line = raw.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    yield payload
        time.sleep(max(0.1, poll_seconds))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aion_chronik.py",
        description="Liest die signierten Daemon-Reports und uebersetzt sie in menschenlesbare Aion-Chronik-Eintraege.",
    )
    parser.add_argument("--report-dir", default="daemon_runtime", help="Verzeichnis des Daemon-Laufs.")
    parser.add_argument("--report-file", default=None, help="Optionale direkte Pfadangabe zur JSONL-Datei.")
    parser.add_argument("--limit", type=int, default=8, help="Anzahl der letzten Eintraege fuer den Initialauszug.")
    parser.add_argument("--follow", action="store_true", help="Bleibt offen und beobachtet neue Eintraege in Echtzeit.")
    parser.add_argument("--poll-seconds", type=float, default=1.0, help="Polling-Intervall im Follow-Modus.")
    parser.add_argument("--no-verify", action="store_true", help="Ueberspringt HMAC-Pruefung und Kettenvalidierung.")
    parser.add_argument("--start-at-end", action="store_true", help="Im Follow-Modus nur neue Eintraege ab Start beobachten.")
    parser.add_argument("--summary", action="store_true", help="Zeigt vor den Eintraegen eine kompakte Tageszusammenfassung.")
    parser.add_argument("--tui", action="store_true", help="Rendert eine farbige Terminalansicht statt einfacher Textliste.")
    parser.add_argument("--html-out", default=None, help="Schreibt zusaetzlich eine HTML-Ansicht in die angegebene Datei.")
    return parser


def _render_records_text(
    records: list[Dict[str, Any]],
    *,
    show_summary: bool,
) -> str:
    chunks: list[str] = []
    if show_summary:
        chunks.append(_render_summary_block(records))
    if records:
        entry_text = "\n\n".join(str(record["text"]) for record in records)
        chunks.append(entry_text)
    return "\n\n".join(chunk for chunk in chunks if chunk).rstrip() + ("\n" if chunks else "")


def _write_html(path: Path, records: list[Dict[str, Any]], report_root: Optional[Path] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_html(records, report_root=report_root), encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    report_dir = Path(str(args.report_dir))
    report_path = Path(str(args.report_file)) if args.report_file else _default_report_path(report_dir)
    resolver = SignatureResolver(report_dir)
    verify = not bool(args.no_verify)

    suppress_initial = bool(args.follow and args.start_at_end)
    initial_entries = [] if suppress_initial else _load_lines(report_path)
    if not initial_entries and not args.follow:
        print(f"Keine Chronik gefunden: {report_path}")
        return 1

    expected_previous: Optional[str] = None
    all_records: list[Dict[str, Any]] = []
    if initial_entries:
        subset = initial_entries[-max(1, int(args.limit)) :]
        if len(initial_entries) > len(subset):
            previous_row = initial_entries[-len(subset) - 1]
            expected_previous = str(previous_row.get("journal_signature") or "")
        all_records, expected_previous = _analyze_entries(
            subset,
            resolver=resolver,
            verify=verify,
            expected_previous=expected_previous,
        )
        if args.tui:
            print(_render_tui(all_records, limit=max(1, int(args.limit))), end="")
        else:
            print(
                _render_records_text(
                    all_records,
                    show_summary=bool(args.summary),
                ),
                end="",
            )
        if args.html_out:
            _write_html(Path(str(args.html_out)), all_records, report_dir)

    if not args.follow:
        return 0

    try:
        for entry in _iter_new_entries(
            report_path,
            start_at_end=True if initial_entries else bool(args.start_at_end),
            poll_seconds=max(0.1, float(args.poll_seconds)),
        ):
            new_records, expected_previous = _analyze_entries(
                [entry],
                resolver=resolver,
                verify=verify,
                expected_previous=expected_previous,
            )
            all_records.extend(new_records)
            if args.tui:
                if _supports_color():
                    sys.stdout.write("\033[2J\033[H")
                else:
                    sys.stdout.write("\n" + "=" * 72 + "\n")
                sys.stdout.write(_render_tui(all_records, limit=max(1, int(args.limit))))
                sys.stdout.flush()
            else:
                sys.stdout.write(
                    _render_records_text(
                        new_records,
                        show_summary=False,
                    )
                )
                sys.stdout.flush()
            if args.html_out:
                _write_html(Path(str(args.html_out)), all_records, report_dir)
    except KeyboardInterrupt:
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
