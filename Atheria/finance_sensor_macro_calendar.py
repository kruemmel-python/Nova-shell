from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _to_timestamp(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return float(parsed.timestamp())


def _first_business_day(year: int, month: int, *, start_day: int = 1) -> date:
    day = max(1, min(28, int(start_day)))
    current = date(int(year), int(month), int(day))
    while current.weekday() >= 5:
        current += timedelta(days=1)
    return current


def _first_weekday(year: int, month: int, weekday: int) -> date:
    current = date(int(year), int(month), 1)
    target = int(weekday) % 7
    while current.weekday() != target:
        current += timedelta(days=1)
    return current


def _severity_for_name(name: str) -> float:
    text = str(name).strip().upper()
    if "CPI" in text:
        return 0.9
    if "PAYROLL" in text or "NFP" in text or "EMPLOY" in text:
        return 0.86
    if "PMI" in text:
        return 0.68
    return 0.52


class MacroReleaseCalendarSensor:
    """
    Emits near-term macro trigger windows for Chronik/Insight.
    Source priority:
    1) Optional local JSON calendar file.
    2) Heuristic monthly schedule (PMI, payrolls, CPI).
    """

    def __init__(
        self,
        *,
        calendar_path: Optional[Path] = None,
        lookahead_hours: float = 120.0,
        max_releases: int = 5,
    ) -> None:
        self.calendar_path = calendar_path if calendar_path is not None else Path("data/macro_release_calendar.json")
        self.lookahead_hours = max(12.0, float(lookahead_hours))
        self.max_releases = max(1, int(max_releases))
        self.last_source = "heuristic"
        self.last_error = ""

    def required_symbols(self) -> list[str]:
        return []

    def _normalize_event(self, raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(raw, dict):
            return None
        name = str(raw.get("name") or raw.get("title") or "").strip()
        if not name:
            return None

        stamp = _to_timestamp(raw.get("timestamp"))
        if stamp is None:
            stamp = _to_timestamp(raw.get("datetime"))
        if stamp is None:
            raw_date = str(raw.get("date") or "").strip()
            raw_time = str(raw.get("time") or "00:00").strip()
            if raw_date:
                stamp = _to_timestamp(f"{raw_date}T{raw_time}:00+00:00")
        if stamp is None:
            return None

        tags = raw.get("tags")
        tag_list = [str(item).strip().upper() for item in tags] if isinstance(tags, list) else []
        severity = _safe_float(raw.get("severity"), _severity_for_name(name))
        return {
            "name": name,
            "timestamp": float(stamp),
            "severity": _clamp(severity, 0.05, 1.0),
            "tags": [item for item in tag_list if item],
        }

    def _load_file_events(self) -> list[Dict[str, Any]]:
        path = Path(self.calendar_path)
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            self.last_error = f"calendar_read_failed:{type(exc).__name__}:{exc}"
            return []

        if isinstance(payload, dict):
            rows = payload.get("events", [])
        elif isinstance(payload, list):
            rows = payload
        else:
            rows = []

        events: list[Dict[str, Any]] = []
        for row in rows:
            event = self._normalize_event(dict(row) if isinstance(row, dict) else {})
            if event is not None:
                events.append(event)
        return events

    def _heuristic_events(self, now_ts: float) -> list[Dict[str, Any]]:
        now_dt = datetime.fromtimestamp(float(now_ts), tz=timezone.utc)
        seeds = [(now_dt.year, now_dt.month)]
        next_month = (now_dt.replace(day=1) + timedelta(days=35)).replace(day=1)
        seeds.append((next_month.year, next_month.month))

        events: list[Dict[str, Any]] = []
        for year, month in seeds:
            pmi_day = _first_business_day(year, month, start_day=1)
            payroll_day = _first_weekday(year, month, 4)
            cpi_day = _first_business_day(year, month, start_day=10)

            pmi_ts = datetime(year, month, pmi_day.day, 15, 0, tzinfo=timezone.utc).timestamp()
            payroll_ts = datetime(year, month, payroll_day.day, 13, 30, tzinfo=timezone.utc).timestamp()
            cpi_ts = datetime(year, month, cpi_day.day, 13, 30, tzinfo=timezone.utc).timestamp()

            events.extend(
                [
                    {"name": "US ISM Manufacturing PMI", "timestamp": pmi_ts, "severity": 0.68, "tags": ["PMI"]},
                    {"name": "US Nonfarm Payrolls", "timestamp": payroll_ts, "severity": 0.86, "tags": ["LABOR"]},
                    {"name": "US CPI", "timestamp": cpi_ts, "severity": 0.9, "tags": ["CPI"]},
                ]
            )
        return events

    def _event_rows(self, now_ts: float) -> tuple[list[Dict[str, Any]], str]:
        file_events = self._load_file_events()
        if file_events:
            return file_events, "file"
        return self._heuristic_events(now_ts), "heuristic"

    def analyze(self, *, now_ts: Optional[float] = None) -> Dict[str, Any]:
        stamp = float(now_ts) if now_ts is not None else float(time.time())
        events, source = self._event_rows(stamp)
        self.last_source = source

        upcoming: list[Dict[str, Any]] = []
        for event in sorted(events, key=lambda item: float(item.get("timestamp", 0.0))):
            event_ts = _safe_float(event.get("timestamp"), 0.0)
            hours = (event_ts - stamp) / 3600.0
            if hours < 0.0 or hours > self.lookahead_hours:
                continue
            row = dict(event)
            row["hours_to_release"] = round(hours, 3)
            upcoming.append(row)
            if len(upcoming) >= self.max_releases:
                break

        pressure = 0.0
        for event in upcoming:
            severity = _safe_float(event.get("severity"), 0.5)
            hours = _safe_float(event.get("hours_to_release"), self.lookahead_hours)
            proximity = max(0.0, 1.0 - (hours / max(1.0, self.lookahead_hours)))
            pressure = max(pressure, severity * proximity)

        next_event = upcoming[0] if upcoming else {}
        return {
            "available": True,
            "source": source,
            "lookahead_hours": round(float(self.lookahead_hours), 3),
            "macro_pressure": round(_clamp(pressure, 0.0, 1.0), 6),
            "next_release_name": str(next_event.get("name") or ""),
            "next_release_in_hours": round(_safe_float(next_event.get("hours_to_release"), -1.0), 3),
            "upcoming_releases": upcoming,
            "last_error": self.last_error,
        }
