from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

from atheria_core import AtheriaCore


logger = logging.getLogger("atheria.daemon")


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, item in list(value.items())[:64]:
            out[str(key)] = _json_safe(item)
        return out
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in list(value)[:64]]
    return str(value)


@dataclass
class AtheriaDaemonConfig:
    report_dir: Path = Path("daemon_runtime")
    tick_interval: float = 0.05
    market_profile: str = "crypto"
    market_transport: str = "auto"
    market_poll_interval_seconds: float = 5.0
    audit_interval_seconds: float = 4.0 * 3600.0
    anomaly_check_interval_seconds: float = 15.0
    anomaly_cooldown_seconds: float = 15.0 * 60.0
    severe_trauma_threshold: float = 0.72
    elevated_trauma_threshold: float = 0.48
    symbols: Tuple[str, ...] = ()
    max_runtime_seconds: Optional[float] = None
    log_level: str = "INFO"
    report_filename: str = "atheria_daemon_audit.jsonl"


class AtheriaDaemon:
    """
    Long-running orchestrator for autonomous ATHERIA operation.
    - boots the core,
    - attaches the market feed immediately,
    - persists chained integrity snapshots,
    - triggers adaptive offspring on severe market anomalies.
    """

    def __init__(self, config: AtheriaDaemonConfig) -> None:
        self.config = config
        self.core = AtheriaCore(tick_interval=float(config.tick_interval))
        self.core.bootstrap_default_mesh()

        self.runtime_root = Path(config.report_dir)
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.report_path = self.runtime_root / str(config.report_filename)
        self.core_audit_root = self.runtime_root / "core_audit"
        self.lineage_root = self.runtime_root / "lineage"

        self.core.safety.audit_output_root = self.core_audit_root
        self.core.safety.audit_log_path = self.core_audit_root / f"{self.core.core_id.lower()}_safety_audit.jsonl"
        self.core.safety.audit_signing_key_path = self.core_audit_root / f"{self.core.core_id.lower()}_audit.key"
        self.core.safety._audit_signing_key = None
        self.core.reproduction.artifact_output_root = self.lineage_root
        self.core.lineage_auditor.lineage_root = self.lineage_root

        self._stop_event = asyncio.Event()
        self._tasks: list[asyncio.Task[Any]] = []
        self._previous_report_signature = "GENESIS"
        self._last_anomaly_trigger_ts = 0.0
        self._forced_profile_restore_task: Optional[asyncio.Task[Any]] = None
        self._report_key_fingerprint: Optional[str] = None
        self._shutdown_complete = False

    def _report_hmac_key(self) -> bytes:
        base_key = self.core.safety._load_or_create_audit_signing_key()
        derived = hashlib.sha256(base_key + b"|atheria-daemon").digest()
        self._report_key_fingerprint = hashlib.sha1(derived).hexdigest()[:12]
        return derived

    async def _sleep_or_stop(self, seconds: float) -> bool:
        delay = max(0.0, float(seconds))
        if delay <= 0.0:
            await asyncio.sleep(0)
            return self._stop_event.is_set()
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
            return True
        except asyncio.TimeoutError:
            return self._stop_event.is_set()

    def _market_anomaly_snapshot(self) -> Dict[str, Any]:
        market = self.core.market_alchemy_status()
        latest_symbols = dict((market.get("last_market_snapshot") or {}).get("symbols") or {})
        trauma = dict(market.get("last_trauma_event") or {})
        anchor_asset = str(trauma.get("anchor_asset") or "")
        if not anchor_asset:
            for candidate in ("BTC", "SP500", "DAX", "NASDAQ", "DOW", "RUSSELL"):
                if candidate in latest_symbols:
                    anchor_asset = candidate
                    break
        if not anchor_asset and latest_symbols:
            anchor_asset = next(iter(latest_symbols))
        anchor_row = dict(latest_symbols.get(anchor_asset) or {})
        trauma_pressure = _clamp(float(market.get("trauma_pressure", 0.0)), 0.0, 1.0)
        recent_return = float(anchor_row.get("recent_return", 0.0))
        volatility = max(0.0, float(anchor_row.get("volatility", 0.0)))
        severe = (
            trauma_pressure >= float(self.config.severe_trauma_threshold)
            or recent_return <= -0.045
            or volatility >= 0.03
        )
        elevated = (
            trauma_pressure >= float(self.config.elevated_trauma_threshold)
            or recent_return <= -0.02
            or volatility >= 0.015
        )
        profile = "stress-test" if trauma_pressure >= float(self.config.severe_trauma_threshold) or recent_return <= -0.06 else "survival"
        return {
            "severe": bool(severe),
            "elevated": bool(elevated),
            "profile": profile,
            "trauma_pressure": round(trauma_pressure, 6),
            "anchor_asset": anchor_asset or "BTC",
            "anchor_recent_return": round(recent_return, 6),
            "anchor_volatility": round(volatility, 6),
            "btc_recent_return": round(recent_return, 6),
            "btc_volatility": round(volatility, 6),
            "market_status": market,
        }

    def _shape_offspring_runtime(self, child: AtheriaCore, *, profile: str) -> None:
        if profile == "stress-test":
            child.phase_controller.system_temperature = max(child.phase_controller.system_temperature, 84.0)
            child.ecology.selection_pressure = max(child.ecology.selection_pressure, 0.82)
            child.reproduction.reproduction_threshold_offset = 0.04
            child.set_executive_goal("reduce_uncertainty", priority=0.94, origin="daemon")
        else:
            child.phase_controller.system_temperature = min(child.phase_controller.system_temperature, 56.0)
            child.ecology.resource_scarcity = max(child.ecology.resource_scarcity, 0.22)
            child.reproduction.reproduction_threshold_offset = -0.02
            child.set_executive_goal("stabilize_homeostasis", priority=0.9, origin="daemon")

    async def _wait_for_child_ready(self, child: AtheriaCore, *, timeout_seconds: float = 1.5) -> bool:
        started = time.perf_counter()
        while (time.perf_counter() - started) <= max(0.1, float(timeout_seconds)):
            if child.running:
                return True
            await asyncio.sleep(0.05)
        return bool(child.running)

    async def _restore_forced_profile_after_artifact(
        self,
        *,
        artifact_task: Optional[asyncio.Task[Any]],
        original_method: Any,
    ) -> None:
        try:
            if artifact_task is not None:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await artifact_task
        finally:
            self.core.reproduction._artifact_profile = original_method

    async def trigger_adaptive_generation(self, *, profile: str, anomaly: Dict[str, Any]) -> Dict[str, Any]:
        now = time.perf_counter()
        if (now - self._last_anomaly_trigger_ts) < float(self.config.anomaly_cooldown_seconds):
            return {
                "triggered": False,
                "reason": "cooldown",
                "seconds_remaining": round(float(self.config.anomaly_cooldown_seconds) - (now - self._last_anomaly_trigger_ts), 6),
                "profile": profile,
            }

        original_method = self.core.reproduction._artifact_profile
        self.core.reproduction._artifact_profile = lambda: str(profile)
        child_name = self.core.reproduction.force_reproduction()
        if child_name is None:
            self.core.reproduction._artifact_profile = original_method
            return {
                "triggered": False,
                "reason": "reproduction_blocked",
                "profile": profile,
            }

        self._last_anomaly_trigger_ts = now
        child = self.core.reproduction.offspring_cores.get(child_name)
        if child is not None:
            self._shape_offspring_runtime(child, profile=str(profile))
            if await self._wait_for_child_ready(child):
                selected_symbols = list(self.config.symbols) if self.config.symbols else None
                child.start_market_alchemy(
                    market_profile=str(self.config.market_profile),
                    transport=str(self.config.market_transport),
                    poll_interval_seconds=float(self.config.market_poll_interval_seconds),
                    symbols=selected_symbols,
                )

        artifact_task = self.core.reproduction.artifact_tasks.get(child_name)
        if self._forced_profile_restore_task is not None:
            self._forced_profile_restore_task.cancel()
        self._forced_profile_restore_task = asyncio.create_task(
            self._restore_forced_profile_after_artifact(
                artifact_task=artifact_task,
                original_method=original_method,
            ),
            name=f"atheria-daemon-profile-restore-{child_name}",
        )

        return {
            "triggered": True,
            "profile": str(profile),
            "child_name": child_name,
            "artifact_task_attached": bool(artifact_task is not None),
            "anomaly": {
                "trauma_pressure": anomaly.get("trauma_pressure"),
                "anchor_asset": anomaly.get("anchor_asset"),
                "anchor_recent_return": anomaly.get("anchor_recent_return"),
                "anchor_volatility": anomaly.get("anchor_volatility"),
                "btc_recent_return": anomaly.get("btc_recent_return"),
                "btc_volatility": anomaly.get("btc_volatility"),
            },
        }

    def _build_report_entry(self, *, reason: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        dashboard = self.core.dashboard_snapshot()
        market = self.core.market_alchemy_status()
        safety = self.core.safety.capture_sensitive_snapshot()
        lineage = self.core.audit_lineage(lineage_root=str(self.lineage_root), default_profile="survival")
        entry = {
            "timestamp": round(time.time(), 6),
            "reason": str(reason),
            "core_id": self.core.core_id,
            "dashboard": _json_safe(dashboard),
            "market": _json_safe(market),
            "safety": _json_safe(safety),
            "lineage": _json_safe(lineage),
            "extra": _json_safe(extra or {}),
        }
        key = self._report_hmac_key()
        payload = {
            "previous": self._previous_report_signature,
            "entry": entry,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        signature = hmac.new(key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()
        return {
            **entry,
            "previous": self._previous_report_signature,
            "journal_signature": signature,
            "journal_key_fingerprint": self._report_key_fingerprint,
        }

    async def write_integrity_report(self, *, reason: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        entry = self._build_report_entry(reason=reason, extra=extra)
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        with self.report_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        self._previous_report_signature = str(entry["journal_signature"])
        logger.info(
            "AtheriaDaemon Report | reason=%s | path=%s | signature=%s",
            reason,
            self.report_path,
            entry["journal_signature"][:12],
        )
        return entry

    async def _audit_loop(self) -> None:
        while not self._stop_event.is_set():
            if await self._sleep_or_stop(float(self.config.audit_interval_seconds)):
                break
            await self.write_integrity_report(reason="scheduled_integrity_audit")

    async def _anomaly_loop(self) -> None:
        while not self._stop_event.is_set():
            anomaly = self._market_anomaly_snapshot()
            if anomaly["severe"]:
                trigger = await self.trigger_adaptive_generation(
                    profile=str(anomaly["profile"]),
                    anomaly=anomaly,
                )
                if trigger.get("triggered", False):
                    await self.write_integrity_report(
                        reason=f"market_anomaly::{trigger['profile']}",
                        extra={"generation_trigger": trigger},
                    )
            elif anomaly["elevated"]:
                await self.write_integrity_report(
                    reason="market_alert",
                    extra={"anomaly": anomaly},
                )
            if await self._sleep_or_stop(float(self.config.anomaly_check_interval_seconds)):
                break

    async def start(self) -> Dict[str, Any]:
        await self.core.start()
        selected_symbols = list(self.config.symbols) if self.config.symbols else None
        market_report = self.core.start_market_alchemy(
            market_profile=str(self.config.market_profile),
            transport=str(self.config.market_transport),
            poll_interval_seconds=float(self.config.market_poll_interval_seconds),
            symbols=selected_symbols,
        )
        await self.write_integrity_report(
            reason="daemon_startup",
            extra={"market_start": market_report},
        )
        self._tasks = [
            asyncio.create_task(self._audit_loop(), name="atheria-daemon-audit"),
            asyncio.create_task(self._anomaly_loop(), name="atheria-daemon-anomaly"),
        ]
        logger.info(
            "AtheriaDaemon started | core=%s | transport=%s | reports=%s",
            self.core.core_id,
            self.config.market_transport,
            self.report_path,
        )
        return {
            "started": True,
            "core_id": self.core.core_id,
            "report_path": str(self.report_path),
            "market": market_report,
        }

    async def stop(self) -> Dict[str, Any]:
        if self._shutdown_complete:
            return {
                "stopped": True,
                "core_id": self.core.core_id,
                "report_path": str(self.report_path),
            }

        self._stop_event.set()
        for task in self._tasks:
            task.cancel()
        if self._forced_profile_restore_task is not None:
            self._forced_profile_restore_task.cancel()
        if self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._forced_profile_restore_task is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._forced_profile_restore_task
        self._tasks.clear()

        self.core.stop_market_alchemy(join_timeout=1.0)
        await self.write_integrity_report(reason="daemon_shutdown")
        await self.core.stop(shutdown_lineage=True)
        self._shutdown_complete = True
        logger.info("AtheriaDaemon stopped | core=%s", self.core.core_id)
        return {
            "stopped": True,
            "core_id": self.core.core_id,
            "report_path": str(self.report_path),
        }

    def request_stop(self) -> None:
        self._stop_event.set()

    async def run(self) -> Dict[str, Any]:
        await self.start()
        result: Dict[str, Any]
        try:
            if self.config.max_runtime_seconds is not None:
                await self._sleep_or_stop(float(self.config.max_runtime_seconds))
            else:
                await self._stop_event.wait()
        finally:
            result = await self.stop()
        return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="atheria_daemon.py",
        description="Autonomous ATHERIA launcher with persistent market feed, periodic integrity reports, and anomaly-triggered offspring.",
    )
    parser.add_argument("--report-dir", default="daemon_runtime", help="Directory for daemon reports, lineage artifacts, and core audits.")
    parser.add_argument("--market-profile", default="crypto", choices=["crypto", "finance"], help="Preset market profile for the ingestion layer.")
    parser.add_argument("--market-transport", default="auto", choices=["auto", "websocket", "poll"], help="Preferred market feed transport.")
    parser.add_argument("--market-poll-seconds", type=float, default=5.0, help="REST poll interval or websocket flush cadence anchor.")
    parser.add_argument("--audit-hours", type=float, default=4.0, help="Hours between scheduled integrity reports.")
    parser.add_argument("--anomaly-seconds", type=float, default=15.0, help="Seconds between anomaly checks.")
    parser.add_argument("--anomaly-cooldown-minutes", type=float, default=15.0, help="Cooldown between anomaly-triggered generations.")
    parser.add_argument("--tick-interval", type=float, default=0.05, help="Core tick interval.")
    parser.add_argument("--max-runtime-seconds", type=float, default=None, help="Optional bounded runtime for supervised sessions.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], help="Daemon log level.")
    return parser


def _config_from_args(args: argparse.Namespace) -> AtheriaDaemonConfig:
    return AtheriaDaemonConfig(
        report_dir=Path(str(args.report_dir)),
        tick_interval=float(args.tick_interval),
        market_profile=str(args.market_profile),
        market_transport=str(args.market_transport),
        market_poll_interval_seconds=float(args.market_poll_seconds),
        audit_interval_seconds=max(10.0, float(args.audit_hours) * 3600.0),
        anomaly_check_interval_seconds=max(2.0, float(args.anomaly_seconds)),
        anomaly_cooldown_seconds=max(30.0, float(args.anomaly_cooldown_minutes) * 60.0),
        max_runtime_seconds=None if args.max_runtime_seconds is None else max(1.0, float(args.max_runtime_seconds)),
        log_level=str(args.log_level),
    )


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, daemon: AtheriaDaemon) -> None:
    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, daemon.request_stop)
        except (NotImplementedError, RuntimeError):
            continue


async def _async_main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    config = _config_from_args(args)

    logging.basicConfig(
        level=getattr(logging, config.log_level),
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    daemon = AtheriaDaemon(config)
    _install_signal_handlers(asyncio.get_running_loop(), daemon)

    try:
        result = await daemon.run()
    except asyncio.CancelledError:
        logger.warning("AtheriaDaemon cancelled.")
        raise
    except KeyboardInterrupt:
        daemon.request_stop()
        result = await daemon.stop()
    except Exception as exc:
        logger.exception("AtheriaDaemon failed: %s", exc)
        with contextlib.suppress(Exception):
            await daemon.stop()
        return 1

    print(json.dumps(_json_safe(result), ensure_ascii=False, indent=2))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        return asyncio.run(_async_main(argv))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
