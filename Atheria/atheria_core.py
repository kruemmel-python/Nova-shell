from __future__ import annotations

import ast
import asyncio
import base64
import builtins as py_builtins
import csv
import hashlib
import hmac
import json
import logging
import math
import multiprocessing as mp
import os
import random
import sqlite3
import socket
import ssl
import struct
import threading
import time
import types
import urllib.error
import urllib.parse
import urllib.request
import uuid
import weakref
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Iterable, Optional, Set, Tuple

import torch

from finance_sensor_macro_calendar import MacroReleaseCalendarSensor
from finance_sensor_move import MoveIndexSensor
from finance_sensor_sector import SectorRotationSensor


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("atheria")


# Requested global controls
System_Temperature: float = 25.0
Entanglement_Registry: Dict[str, Set[str]] = {}
POINCARE_DIMS = 6


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


@dataclass
class ToolExecutionRecord:
    tool_name: str
    success: bool
    result: Any
    error: Optional[str]
    duration_ms: float
    code_hash: Optional[str] = None
    snapshot_hash: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "duration_ms": round(float(self.duration_ms), 6),
            "code_hash": self.code_hash,
            "snapshot_hash": self.snapshot_hash,
        }


@dataclass
class InterventionProposal:
    proposal_id: str
    proposal_type: str
    field: Optional[str]
    suggested_value: Optional[float]
    target_metric: str
    rationale: str
    confidence: float
    source_tool: Optional[str] = None
    evidence: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "proposal_type": self.proposal_type,
            "field": self.field,
            "suggested_value": None if self.suggested_value is None else round(float(self.suggested_value), 6),
            "target_metric": self.target_metric,
            "rationale": self.rationale,
            "confidence": round(float(self.confidence), 6),
            "source_tool": self.source_tool,
            "evidence": dict(self.evidence),
        }


@dataclass
class InterventionPlan:
    target_metric: str
    action: str
    preconditions: Dict[str, Any]
    expected_effects: Dict[str, float]
    rationale: str
    tool_name: Optional[str] = None
    code_string: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "target_metric": self.target_metric,
            "action": self.action,
            "preconditions": dict(self.preconditions),
            "expected_effects": {str(k): round(float(v), 6) for k, v in self.expected_effects.items()},
            "rationale": self.rationale,
            "tool_name": self.tool_name,
            "code_string": self.code_string,
        }


@dataclass
class CausalVariable:
    name: str
    value: float = 0.0
    desired_direction: int = 0


_TOOL_ALLOWED_BUILTINS: Dict[str, Any] = dict(vars(py_builtins))
_TOOL_BLOCKED_NAMES = {
    "__builtins__",
    "open",
    "exec",
    "eval",
    "compile",
    "globals",
    "locals",
    "vars",
    "getattr",
    "setattr",
    "delattr",
    "type",
    "object",
    "input",
    "help",
    "dir",
    "os",
    "sys",
    "subprocess",
    "importlib",
    "threading",
    "asyncio",
    "multiprocessing",
    "__import__",
}
_TOOL_BLOCKED_ATTRS = {
    "__class__",
    "__dict__",
    "__bases__",
    "__subclasses__",
    "__globals__",
    "__code__",
    "__getattribute__",
    "__mro__",
}
_TOOL_ALLOWED_AST_NODES = (
    ast.Module,
    ast.Assign,
    ast.Expr,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.Constant,
    ast.Call,
    ast.Attribute,
    ast.Subscript,
    ast.BinOp,
    ast.UnaryOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.USub,
    ast.UAdd,
    ast.List,
    ast.Tuple,
    ast.Dict,
    ast.Set,
    ast.Compare,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.If,
    ast.IfExp,
    ast.ListComp,
    ast.DictComp,
    ast.SetComp,
    ast.GeneratorExp,
    ast.comprehension,
    ast.Slice,
    ast.keyword,
)


def _make_tool_json_safe(value: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        return "TRUNCATED"
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, torch.Tensor):
        data = value.detach().cpu().flatten()
        if data.numel() == 1:
            return float(data.item())
        return [float(item) for item in data[:16].tolist()]
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, item in list(value.items())[:32]:
            out[str(key)] = _make_tool_json_safe(item, depth=depth + 1)
        return out
    if isinstance(value, (list, tuple, set, deque)):
        return [_make_tool_json_safe(item, depth=depth + 1) for item in list(value)[:32]]
    return str(value)


def _stable_json_dumps(value: Any) -> str:
    return json.dumps(_make_tool_json_safe(value), sort_keys=True, separators=(",", ":"))


def _tool_execution_fingerprint(*, success: bool, result: Any, error: Optional[str]) -> str:
    payload = {
        "success": bool(success),
        "result": _make_tool_json_safe(result),
        "error": None if error is None else str(error),
    }
    return hashlib.sha256(_stable_json_dumps(payload).encode("utf-8")).hexdigest()


def _run_python_tool_in_subprocess(
    send_conn: Any,
    source: str,
    safe_snapshot: Dict[str, Any],
    tool_name: str,
    timeout_seconds: float,
) -> None:
    _ = timeout_seconds
    payload: Dict[str, Any] = {
        "success": False,
        "result": None,
        "error": None,
    }
    try:
        safe_globals = {
            "__builtins__": _TOOL_ALLOWED_BUILTINS,
            "__name__": "__atheria_tool__",
            "math": math,
            "torch": torch,
            "snapshot": safe_snapshot,
        }
        local_scope: Dict[str, Any] = {}
        compiled = compile(source, f"<atheria-tool:{tool_name}>", "exec")
        exec(compiled, safe_globals, local_scope)
        payload["success"] = True
        payload["result"] = _make_tool_json_safe(local_scope.get("result", safe_globals.get("result")))
    except Exception as exc:
        payload["error"] = f"{type(exc).__name__}:{exc}"
    try:
        send_conn.send(payload)
    except Exception:
        pass
    finally:
        try:
            send_conn.close()
        except Exception:
            pass


def _validate_tool_source(code_string: str, *, max_nodes: int = 1200) -> tuple[bool, Optional[str]]:
    try:
        tree = ast.parse(code_string, mode="exec")
    except SyntaxError as exc:
        return False, f"syntax_error:{exc.msg}"

    nodes = list(ast.walk(tree))
    if len(nodes) > max_nodes:
        return False, "source_too_complex"

    blocked_node_types = (
        ast.Import,
        ast.ImportFrom,
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
        ast.Lambda,
        ast.Delete,
        ast.Try,
        ast.Raise,
        ast.While,
        ast.For,
        ast.AsyncFor,
        ast.With,
        ast.AsyncWith,
        ast.Global,
        ast.Nonlocal,
        ast.Await,
        ast.Yield,
        ast.YieldFrom,
    )
    for node in nodes:
        if isinstance(node, blocked_node_types):
            return False, f"blocked_node:{type(node).__name__}"
        if not isinstance(node, _TOOL_ALLOWED_AST_NODES):
            return False, f"unsupported_node:{type(node).__name__}"
        if isinstance(node, ast.Name) and node.id in _TOOL_BLOCKED_NAMES:
            return False, f"blocked_name:{node.id}"
        if isinstance(node, ast.Attribute) and node.attr in _TOOL_BLOCKED_ATTRS:
            return False, f"blocked_attr:{node.attr}"
    return True, None


class PythonInterpreterTool:
    """
    Read-only analysis tool that executes AST-vetted Python against serialized snapshots only.
    """

    def __init__(self, *, timeout_seconds: float = 4.0, max_source_chars: int = 5000, max_snapshot_chars: int = 24000) -> None:
        self.name = "python_interpreter"
        self.timeout_seconds = timeout_seconds
        self.max_source_chars = max_source_chars
        self.max_snapshot_chars = max_snapshot_chars
        self._mp_context = mp.get_context("spawn")
        self.process_start_grace_seconds = 4.0
        self.executions = 0
        self.failures = 0
        self.last_code_hash: Optional[str] = None
        self.last_snapshot_hash: Optional[str] = None
        self.last_duration_ms = 0.0
        self.last_error: Optional[str] = None
        self.last_execution_mode = "process"
        self.last_parent_pid: Optional[int] = mp.current_process().pid
        self.last_child_pid: Optional[int] = None
        self.last_child_exitcode: Optional[int] = None

    def execute(self, code_string: str, *, snapshot: Dict[str, Any]) -> ToolExecutionRecord:
        started = time.perf_counter()
        source = str(code_string or "")
        if len(source) > self.max_source_chars:
            record = ToolExecutionRecord(
                tool_name=self.name,
                success=False,
                result=None,
                error="source_too_long",
                duration_ms=0.0,
            )
            self.failures += 1
            self.executions += 1
            self.last_error = record.error
            return record

        allowed, error = _validate_tool_source(source)
        if not allowed:
            record = ToolExecutionRecord(
                tool_name=self.name,
                success=False,
                result=None,
                error=error,
                duration_ms=0.0,
            )
            self.failures += 1
            self.executions += 1
            self.last_error = record.error
            return record

        safe_snapshot = _make_tool_json_safe(snapshot)
        serialized = json.dumps(safe_snapshot, sort_keys=True)
        if len(serialized) > self.max_snapshot_chars:
            record = ToolExecutionRecord(
                tool_name=self.name,
                success=False,
                result=None,
                error="snapshot_too_large",
                duration_ms=0.0,
            )
            self.failures += 1
            self.executions += 1
            self.last_error = record.error
            return record

        code_hash = hashlib.sha1(source.encode("utf-8")).hexdigest()[:12]
        snapshot_hash = hashlib.sha1(serialized.encode("utf-8")).hexdigest()[:12]
        self.last_code_hash = code_hash
        self.last_snapshot_hash = snapshot_hash

        success = False
        result: Any = None
        runtime_error: Optional[str] = None
        parent_conn = None
        child_conn = None
        proc = None
        self.last_execution_mode = "process"
        self.last_parent_pid = mp.current_process().pid
        self.last_child_pid = None
        self.last_child_exitcode = None
        try:
            parent_conn, child_conn = self._mp_context.Pipe(duplex=False)
            proc = self._mp_context.Process(
                target=_run_python_tool_in_subprocess,
                args=(child_conn, source, safe_snapshot, self.name, self.timeout_seconds),
            )
            proc.daemon = True
            proc.start()
            self.last_child_pid = proc.pid
            child_conn.close()
            child_conn = None

            proc.join(self.timeout_seconds + self.process_start_grace_seconds)
            if proc.is_alive():
                proc.terminate()
                proc.join(0.05)
                if proc.is_alive() and hasattr(proc, "kill"):
                    proc.kill()
                    proc.join(0.05)
                runtime_error = "hard_timeout_exceeded"
            elif parent_conn.poll():
                payload = parent_conn.recv()
                success = bool(payload.get("success", False))
                result = payload.get("result")
                runtime_error = payload.get("error")
                if not success and runtime_error is None:
                    runtime_error = "tool_execution_failed"
            else:
                runtime_error = "no_result_from_child"
        except Exception as exc:
            runtime_error = f"process_isolation_failed:{type(exc).__name__}:{exc}"
        finally:
            duration_ms = (time.perf_counter() - started) * 1000.0
            if parent_conn is not None:
                try:
                    parent_conn.close()
                except Exception:
                    pass
            if child_conn is not None:
                try:
                    child_conn.close()
                except Exception:
                    pass
            if proc is not None:
                self.last_child_exitcode = proc.exitcode

        self.executions += 1
        self.last_duration_ms = duration_ms
        if not success:
            result = None
            self.failures += 1
            self.last_error = runtime_error
        else:
            self.last_error = None

        record = ToolExecutionRecord(
            tool_name=self.name,
            success=success,
            result=result,
            error=runtime_error,
            duration_ms=duration_ms,
            code_hash=code_hash,
            snapshot_hash=snapshot_hash,
        )
        setattr(
            record,
            "replay_context",
            {
                "tool_name": self.name,
                "code_string": source,
                "snapshot": safe_snapshot,
            },
        )
        return record


class ToolRegistry:
    """
    Capability registry for strictly typed external reasoning tools.
    """

    def __init__(self, core: "AtheriaCore") -> None:
        self.core = core
        self.tools: Dict[str, Any] = {}
        self.specs: Dict[str, Dict[str, Any]] = {}
        self.execution_records: Deque[Dict[str, Any]] = deque(maxlen=64)
        self.executions = 0
        self.failures = 0
        self.last_tool_name: Optional[str] = None
        self.last_record: Dict[str, Any] = {}
        self.register_tool(
            "python_interpreter",
            PythonInterpreterTool(),
            capability="read_only_analysis",
            read_only=True,
        )

    def register_tool(self, name: str, tool: Any, *, capability: str, read_only: bool) -> None:
        tool_name = str(name)
        self.tools[tool_name] = tool
        self.specs[tool_name] = {
            "capability": str(capability),
            "read_only": bool(read_only),
        }

    def execute(self, name: str, *, code_string: str, snapshot: Dict[str, Any]) -> ToolExecutionRecord:
        tool_name = str(name)
        tool = self.tools.get(tool_name)
        if tool is None:
            record = ToolExecutionRecord(
                tool_name=tool_name,
                success=False,
                result=None,
                error="tool_not_found",
                duration_ms=0.0,
            )
        else:
            record = tool.execute(code_string, snapshot=snapshot)
        self.executions += 1
        if not record.success:
            self.failures += 1
        self.last_tool_name = tool_name
        self.last_record = record.as_dict()
        self.execution_records.append(dict(self.last_record))
        return record


class CausalVariableGraph:
    """
    Structured causal state graph with action preconditions and expected effects.
    """

    def __init__(self) -> None:
        self.variables: Dict[str, CausalVariable] = {
            "stress": CausalVariable("stress", desired_direction=-1),
            "uncertainty": CausalVariable("uncertainty", desired_direction=-1),
            "purpose": CausalVariable("purpose", desired_direction=1),
            "resources": CausalVariable("resources", desired_direction=1),
            "symbols": CausalVariable("symbols", desired_direction=1),
            "memory": CausalVariable("memory", desired_direction=1),
            "predictability": CausalVariable("predictability", desired_direction=1),
            "confidence": CausalVariable("confidence", desired_direction=1),
        }
        self.action_effects: Dict[str, Dict[str, float]] = {
            "stabilize_local": {"stress": 0.22, "purpose": 0.08},
            "focus_goal": {"purpose": 0.18, "uncertainty": 0.06},
            "induce_imagination": {"uncertainty": 0.24, "memory": 0.08},
            "anchor_symbols": {"symbols": 0.24, "uncertainty": 0.1},
            "recall_episode": {"memory": 0.2, "uncertainty": 0.12, "stress": 0.06},
            "request_resources": {"resources": 0.28, "stress": 0.08},
            "exchange_knowledge": {"symbols": 0.18, "uncertainty": 0.18},
            "rewrite_topology": {"purpose": 0.14, "stress": 0.04},
            "run_analysis_tool": {"uncertainty": 0.22, "purpose": 0.1, "confidence": 0.08},
            "start_market_alchemy": {"uncertainty": 0.16, "symbols": 0.06, "confidence": 0.04},
            "poll_market_alchemy": {"uncertainty": 0.18, "confidence": 0.05},
            "stop_market_alchemy": {"stress": 0.12, "resources": 0.04},
            "audit_inter_core_resonance": {"uncertainty": 0.2, "confidence": 0.08, "memory": 0.05},
        }
        self.action_preconditions: Dict[str, Dict[str, Tuple[Optional[float], Optional[float]]]] = {
            "stabilize_local": {"stress": (0.2, None)},
            "focus_goal": {"purpose": (None, 0.82)},
            "induce_imagination": {"resources": (0.03, None)},
            "anchor_symbols": {"confidence": (0.18, None)},
            "recall_episode": {"memory": (0.0, None)},
            "request_resources": {"resources": (None, 0.7)},
            "exchange_knowledge": {"confidence": (0.22, None)},
            "rewrite_topology": {"confidence": (0.26, None), "resources": (0.03, None)},
            "run_analysis_tool": {"confidence": (0.08, None)},
            "start_market_alchemy": {"confidence": (0.06, None)},
            "poll_market_alchemy": {"confidence": (0.04, None)},
            "audit_inter_core_resonance": {"confidence": (0.04, None)},
        }

    def update_state(self, state: Dict[str, float]) -> None:
        for name, variable in self.variables.items():
            if name in state:
                variable.value = _clamp(float(state[name]), 0.0, 1.0)

    def current_state(self) -> Dict[str, float]:
        return {name: float(variable.value) for name, variable in self.variables.items()}

    def preconditions_for_action(self, action_name: str) -> Dict[str, Dict[str, Optional[float]]]:
        out: Dict[str, Dict[str, Optional[float]]] = {}
        for variable, (lo, hi) in self.action_preconditions.get(str(action_name), {}).items():
            out[variable] = {
                "min": None if lo is None else round(float(lo), 6),
                "max": None if hi is None else round(float(hi), 6),
            }
        return out

    def preconditions_satisfied(self, action_name: str) -> bool:
        for name, limits in self.action_preconditions.get(str(action_name), {}).items():
            value = float(self.variables.get(name, CausalVariable(name, 0.0)).value)
            lo, hi = limits
            if lo is not None and value < float(lo):
                return False
            if hi is not None and value > float(hi):
                return False
        return True

    def expected_effect(self, action_name: str, target_metric: str) -> float:
        return float(self.action_effects.get(str(action_name), {}).get(str(target_metric), 0.0))

    def expected_postconditions(self, action_name: str, *, target_metric: str) -> Dict[str, float]:
        effect = self.expected_effect(action_name, target_metric)
        direction = float(self.variables.get(str(target_metric), CausalVariable(str(target_metric), 0.0)).desired_direction)
        post_value = _clamp(float(self.current_state().get(str(target_metric), 0.0)) + effect * direction, 0.0, 1.0)
        return {str(target_metric): post_value}

    def observe(self, action_name: str, *, target_metric: str, actual_effect: float) -> None:
        action = str(action_name)
        metric = str(target_metric)
        action_row = self.action_effects.setdefault(action, {})
        prior = float(action_row.get(metric, 0.0))
        action_row[metric] = _clamp(0.72 * prior + 0.28 * float(actual_effect), -1.0, 1.0)


class CorePopulationRegistry:
    """
    Process-local registry for independently running ATHERIA cores.
    Used by inter-core features (HGT, markets, global dreaming).
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cores: Dict[str, weakref.ReferenceType[Any]] = {}

    def _prune_locked(self) -> None:
        stale = []
        for core_id, ref in self._cores.items():
            if ref() is None:
                stale.append(core_id)
        for core_id in stale:
            self._cores.pop(core_id, None)

    def register(self, core: "AtheriaCore") -> None:
        with self._lock:
            self._cores[core.core_id] = weakref.ref(core)
            self._prune_locked()

    def unregister(self, core_id: str) -> None:
        with self._lock:
            self._cores.pop(core_id, None)
            self._prune_locked()

    def all_cores(self, *, running_only: bool = True) -> list["AtheriaCore"]:
        with self._lock:
            self._prune_locked()
            out: list["AtheriaCore"] = []
            for ref in self._cores.values():
                core = ref()
                if core is None:
                    continue
                if running_only and not core.running:
                    continue
                out.append(core)
            return out

    def peers(self, core_id: str, *, running_only: bool = True) -> list["AtheriaCore"]:
        return [core for core in self.all_cores(running_only=running_only) if core.core_id != core_id]

    def count(self, *, running_only: bool = True) -> int:
        return len(self.all_cores(running_only=running_only))


GLOBAL_CORE_REGISTRY = CorePopulationRegistry()


class GlobalMorphicNode:
    """
    Collective field-memory node for inter-core dream synchronization.
    """

    def __init__(
        self,
        registry: CorePopulationRegistry,
        *,
        dream_ttl_seconds: float = 28.0,
        trauma_ttl_seconds: float = 48.0,
    ) -> None:
        self.registry = registry
        self.dream_ttl_seconds = dream_ttl_seconds
        self.trauma_ttl_seconds = trauma_ttl_seconds
        self._lock = threading.RLock()
        self._dream_records: Deque[Dict[str, Any]] = deque(maxlen=768)
        self._trauma_records: Deque[Dict[str, Any]] = deque(maxlen=512)
        self.sync_events = 0
        self.trauma_broadcast_events = 0

    def publish_sleep_dream(
        self,
        *,
        core: "AtheriaCore",
        replay_labels: list[str],
        replay_strength: float,
    ) -> None:
        pattern = core.holographic_field.pattern.detach().clone()
        if float(torch.norm(pattern, p=2)) <= 1e-8:
            pattern = _fold_vector_from_text(core.core_id, dims=int(core.holographic_field.pattern.numel()))
        future = core.holographic_field.last_future_projection.detach().clone()
        if float(torch.norm(future, p=2)) <= 1e-8:
            future = pattern.detach().clone()
        now = time.perf_counter()
        record = {
            "ts": now,
            "core_id": core.core_id,
            "pattern": pattern,
            "future": future,
            "replay_labels": list(replay_labels[:8]),
            "replay_strength": _clamp(replay_strength, 0.0, 1.0),
            "stress_index": core.system_stress_index(),
        }
        with self._lock:
            self._dream_records.append(record)

    def publish_trauma_if_relevant(self, core: "AtheriaCore") -> None:
        stress = core.system_stress_index()
        if stress < 0.62:
            return
        now = time.perf_counter()
        record = {
            "ts": now,
            "core_id": core.core_id,
            "pattern": core.holographic_field.pattern.detach().clone(),
            "stress_index": stress,
            "temperature": float(core.phase_controller.system_temperature),
        }
        with self._lock:
            self._trauma_records.append(record)
            self.trauma_broadcast_events += 1

    def collect_collective_resonance(self, core: "AtheriaCore") -> Dict[str, Any]:
        dims = int(core.holographic_field.pattern.numel())
        zero = torch.zeros(dims, dtype=torch.float32)
        now = time.perf_counter()

        with self._lock:
            peers = self.registry.peers(core.core_id, running_only=True)
            sleeping_peer_ids = {
                peer.core_id
                for peer in peers
                if peer.rhythm.state is RhythmState.SLEEP and not peer.aion_meditation_mode
            }

            dream_candidates = [
                rec
                for rec in self._dream_records
                if rec["core_id"] in sleeping_peer_ids
                and (now - float(rec["ts"])) <= self.dream_ttl_seconds
            ]
            trauma_candidates = [
                rec
                for rec in self._trauma_records
                if rec["core_id"] != core.core_id and (now - float(rec["ts"])) <= self.trauma_ttl_seconds
            ]

        if not dream_candidates:
            return {
                "resonance": zero,
                "instinctive_noise": zero,
                "coherence": 0.0,
                "trauma_intensity": 0.0,
                "peer_count": 0,
            }

        weighted = torch.zeros(dims, dtype=torch.float32)
        total_weight = 1e-8
        unique_sources: Set[str] = set()
        for rec in dream_candidates:
            pattern = rec["pattern"]
            future = rec["future"]
            stress = _clamp(float(rec["stress_index"]), 0.0, 1.0)
            replay_strength = _clamp(float(rec["replay_strength"]), 0.0, 1.0)
            weight = 0.45 + 0.35 * replay_strength + 0.2 * stress
            p = pattern / (torch.norm(pattern, p=2) + 1e-8)
            f = future / (torch.norm(future, p=2) + 1e-8)
            blended = 0.62 * p + 0.38 * f
            weighted = weighted + blended * weight
            total_weight += weight
            unique_sources.add(str(rec["core_id"]))

        resonance = weighted / total_weight
        resonance = resonance / (torch.norm(resonance, p=2) + 1e-8)
        coherence = _clamp(float(torch.norm(resonance, p=2)), 0.0, 1.0)

        instinctive_noise = torch.zeros(dims, dtype=torch.float32)
        trauma_intensity = 0.0
        if trauma_candidates:
            trauma_weight_sum = 1e-8
            for rec in trauma_candidates:
                pattern = rec["pattern"]
                stress = _clamp(float(rec["stress_index"]), 0.0, 1.0)
                if stress <= 0.0:
                    continue
                noise_scale = 0.55 + 0.45 * stress
                pattern_norm = pattern / (torch.norm(pattern, p=2) + 1e-8)
                instinctive_noise = instinctive_noise + pattern_norm * noise_scale
                trauma_weight_sum += noise_scale
            instinctive_noise = instinctive_noise / trauma_weight_sum
            instinctive_noise = instinctive_noise / (torch.norm(instinctive_noise, p=2) + 1e-8)
            trauma_intensity = _clamp(
                sum(_clamp(float(rec["stress_index"]), 0.0, 1.0) for rec in trauma_candidates)
                / max(1, len(trauma_candidates)),
                0.0,
                1.0,
            )

        self.sync_events += 1
        return {
            "resonance": resonance,
            "instinctive_noise": instinctive_noise,
            "coherence": coherence,
            "trauma_intensity": trauma_intensity,
            "peer_count": len(unique_sources),
        }


GLOBAL_MORPHIC_NODE = GlobalMorphicNode(GLOBAL_CORE_REGISTRY)


class GlobalSymbolAtlas:
    """
    Process-local canonical symbol registry.
    Stable field signatures map to the same symbol ID across cores.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._symbols: Dict[str, Dict[str, Any]] = {}
        self.anchor_events = 0
        self.reuse_events = 0

    def _canonical_hint(self, label_hint: str) -> str:
        cleaned = "".join(ch if ch.isalnum() else "_" for ch in str(label_hint))
        cleaned = cleaned.strip("_").upper()
        return cleaned[:48] or "GENERIC"

    def anchor(
        self,
        *,
        core: "AtheriaCore",
        signature: str,
        label_hint: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        canonical_hint = self._canonical_hint(label_hint)
        now = time.perf_counter()
        with self._lock:
            record = self._symbols.get(signature)
            reused = False
            if record is None:
                symbol_id = f"SYM::{canonical_hint}::{str(signature)[:8].upper()}"
                record = {
                    "symbol_id": symbol_id,
                    "signature": str(signature),
                    "label_hint": canonical_hint,
                    "created_by": core.core_id,
                    "first_seen": now,
                    "last_seen": now,
                    "seen_count": 1,
                    "cores": {core.core_id},
                    "payload": dict(payload or {}),
                }
                self._symbols[signature] = record
            else:
                preexisting = set(record["cores"])
                record["last_seen"] = now
                record["seen_count"] = int(record["seen_count"]) + 1
                record["cores"].add(core.core_id)
                if payload:
                    record["payload"] = {**dict(record.get("payload", {})), **dict(payload)}
                reused = core.core_id not in preexisting or int(record["seen_count"]) > 1
                if reused:
                    self.reuse_events += 1
            self.anchor_events += 1
            return {
                "symbol_id": str(record["symbol_id"]),
                "signature": str(record["signature"]),
                "shared_cores": len(record["cores"]),
                "seen_count": int(record["seen_count"]),
                "reused": reused,
            }

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._symbols)

    def export(self, limit: int = 12) -> list[Dict[str, Any]]:
        with self._lock:
            items = list(self._symbols.values())
        items.sort(key=lambda item: (int(item["seen_count"]), float(item["last_seen"])), reverse=True)
        out: list[Dict[str, Any]] = []
        for item in items[: max(1, limit)]:
            out.append(
                {
                    "symbol_id": str(item["symbol_id"]),
                    "signature": str(item["signature"]),
                    "label_hint": str(item["label_hint"]),
                    "created_by": str(item["created_by"]),
                    "seen_count": int(item["seen_count"]),
                    "shared_cores": len(item["cores"]),
                }
            )
        return out


GLOBAL_SYMBOL_ATLAS = GlobalSymbolAtlas()


class AtherCreditMarket:
    """
    Dynamic inter-core resource market.
    Hot/unstable cores can rent resources from cooler/stable cores in exchange for Ather-Credits.
    """

    def __init__(self, registry: CorePopulationRegistry) -> None:
        self.registry = registry
        self._lock = threading.RLock()
        self.transactions: Deque[Dict[str, Any]] = deque(maxlen=1024)
        self.last_price_per_unit = 0.0

    def _guardian_score(self, core: "AtheriaCore") -> float:
        asm = core.assembler
        coolness = 1.0 - _clamp(core.phase_controller.system_temperature / 100.0, 0.0, 1.0)
        abundance = math.tanh(max(0.0, asm.resource_pool) / 30.0)
        purpose = _clamp(core.transcendence.last_purpose_alignment, 0.0, 1.0)
        morphic = _clamp(core.holographic_field.last_morphic_resonance_index, 0.0, 1.0)
        survival_bonus = 0.08 if core.reproduction.last_artifact_profile == "survival" else 0.0
        return _clamp(0.35 * coolness + 0.3 * abundance + 0.2 * purpose + 0.15 * morphic + survival_bonus, 0.0, 1.0)

    def _need_score(self, core: "AtheriaCore") -> float:
        asm = core.assembler
        scarcity = _clamp(core.ecology.resource_scarcity, 0.0, 1.0)
        heat = _clamp((core.phase_controller.system_temperature - 52.0) / 52.0, 0.0, 1.0)
        local_entropy = sum(float(v) for v in core.phase_controller.local_entropy.values())
        entropy_load = _clamp(math.tanh(local_entropy / 60.0), 0.0, 1.0)
        reserve_pressure = _clamp((10.0 - asm.resource_pool) / 10.0, 0.0, 1.0)
        return _clamp(0.34 * scarcity + 0.28 * heat + 0.22 * entropy_load + 0.16 * reserve_pressure, 0.0, 1.0)

    def _select_lender(self, borrower: "AtheriaCore") -> Optional["AtheriaCore"]:
        candidates = []
        for peer in self.registry.peers(borrower.core_id, running_only=True):
            if peer.aion_meditation_mode:
                continue
            guardian = self._guardian_score(peer)
            asm = peer.assembler
            available = max(0.0, asm.resource_pool - (8.0 + guardian * 4.5))
            if available < 0.35:
                continue
            score = guardian * 0.7 + _clamp(available / 30.0, 0.0, 1.0) * 0.3
            candidates.append((score, peer))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def execute_rental(
        self,
        *,
        borrower: "AtheriaCore",
        lender: Optional["AtheriaCore"] = None,
        requested_units: Optional[float] = None,
        force: bool = False,
    ) -> Optional[Dict[str, Any]]:
        borrower_asm = borrower.assembler
        need = self._need_score(borrower)
        if not force and need < borrower_asm.market_need_threshold:
            return None

        lender_core = lender or self._select_lender(borrower)
        if lender_core is None or lender_core.core_id == borrower.core_id:
            return None

        lender_asm = lender_core.assembler
        guardian = self._guardian_score(lender_core)
        lender_asm.market_guardian_score = guardian
        reserve = 8.0 + guardian * 4.5
        available = max(0.0, lender_asm.resource_pool - reserve)
        if available < 0.25:
            return None

        target_units = requested_units if requested_units is not None else (1.0 + 4.2 * need)
        units = _clamp(target_units, 0.25, available)
        if units <= 0.0:
            return None

        scarcity = _clamp(borrower.ecology.resource_scarcity, 0.0, 1.0)
        price_per_unit = 1.1 + 1.5 * scarcity + 1.1 * guardian + 0.9 * max(0.0, need - 0.35)
        affordable_units = borrower_asm.credit_balance / max(1e-8, price_per_unit)
        if not force and affordable_units < 0.2:
            return None
        units = min(units, affordable_units)
        if units < 0.2:
            return None

        total_price = units * price_per_unit
        transfer_efficiency = _clamp(0.9 + 0.06 * guardian, 0.88, 0.98)
        received_units = units * transfer_efficiency

        lender_asm.resource_pool = max(0.0, lender_asm.resource_pool - units)
        borrower_asm.resource_pool = min(5000.0, borrower_asm.resource_pool + received_units)
        borrower_asm.credit_balance = max(-250.0, borrower_asm.credit_balance - total_price)
        lender_asm.credit_balance = min(5000.0, lender_asm.credit_balance + total_price)

        packet = lender_asm.export_efficiency_packet()
        packet_quality = borrower_asm.ingest_efficiency_packet(packet)

        borrower_asm.market_transactions += 1
        borrower_asm.market_borrow_events += 1
        borrower_asm.market_resources_in += received_units
        borrower_asm.market_last_partner = lender_core.core_id
        borrower_asm.market_last_price = price_per_unit
        borrower_asm.market_last_packet_quality = packet_quality

        lender_asm.market_transactions += 1
        lender_asm.market_lend_events += 1
        lender_asm.market_resources_out += units
        lender_asm.market_last_partner = borrower.core_id
        lender_asm.market_last_price = price_per_unit

        report = {
            "timestamp": round(time.time(), 6),
            "borrower": borrower.core_id,
            "lender": lender_core.core_id,
            "units_requested": round(float(target_units), 6),
            "units_transferred": round(float(received_units), 6),
            "units_from_lender": round(float(units), 6),
            "price_per_unit": round(float(price_per_unit), 6),
            "total_price": round(float(total_price), 6),
            "packet_quality": round(float(packet_quality), 6),
            "guardian_score": round(float(guardian), 6),
        }

        with self._lock:
            self.transactions.append(report)
            self.last_price_per_unit = float(price_per_unit)

        logger.info(
            "Ather-Credit Market | borrower=%s lender=%s units=%.3f price=%.3f quality=%.3f",
            borrower.core_id,
            lender_core.core_id,
            received_units,
            price_per_unit,
            packet_quality,
        )

        return report


GLOBAL_ATHER_CREDIT_MARKET = AtherCreditMarket(GLOBAL_CORE_REGISTRY)


def _fold_vector_from_text(text: str, dims: int = 12) -> torch.Tensor:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    data = [digest[i % len(digest)] / 255.0 for i in range(dims)]
    vec = torch.tensor(data, dtype=torch.float32)
    return vec / (torch.norm(vec, p=2) + 1e-8)


def _project_to_poincare_ball(vec: torch.Tensor, max_norm: float = 0.999) -> torch.Tensor:
    v = vec.detach().float().flatten()
    norm = float(torch.norm(v, p=2))
    if norm >= max_norm:
        v = v * (max_norm / (norm + 1e-8))
    return v


def _poincare_coord_from_text(text: str, dims: int = POINCARE_DIMS) -> torch.Tensor:
    base = _fold_vector_from_text(text, dims=dims)
    centered = base - torch.mean(base)
    centered = centered / (torch.norm(centered, p=2) + 1e-8)
    return _project_to_poincare_ball(centered * 0.72)


def poincare_distance(u: torch.Tensor, v: torch.Tensor) -> float:
    """
    Geodesic distance in the Poincare ball.
    """
    uu = _project_to_poincare_ball(u)
    vv = _project_to_poincare_ball(v)
    du = float(torch.sum(uu * uu))
    dv = float(torch.sum(vv * vv))
    diff = uu - vv
    d2 = float(torch.sum(diff * diff))
    denom = max(1e-8, (1.0 - du) * (1.0 - dv))
    arg = 1.0 + (2.0 * d2 / denom)
    if arg < 1.0:
        arg = 1.0
    return float(math.acosh(arg))


class AggregateState(str, Enum):
    SOLID = "solid"
    LIQUID = "liquid"
    PLASMA = "plasma"

    @property
    def dashboard_name(self) -> str:
        return {
            AggregateState.SOLID: "Eis",
            AggregateState.LIQUID: "Wasser",
            AggregateState.PLASMA: "Plasma",
        }[self]


class RhythmState(str, Enum):
    WAKE = "wake"
    SLEEP = "sleep"


class AtheriaPhase:
    """Decorator that swaps function complexity by current phase."""

    def __init__(
        self,
        solid_impl: Optional[str] = None,
        liquid_impl: Optional[str] = None,
        plasma_impl: Optional[str] = None,
    ) -> None:
        self._override = {
            AggregateState.SOLID: solid_impl,
            AggregateState.LIQUID: liquid_impl,
            AggregateState.PLASMA: plasma_impl,
        }

    def _resolve_impl(self, instance: object, fn: Callable) -> Callable:
        phase = instance.phase_controller.current_state
        name = self._override.get(phase) or f"{fn.__name__}_{phase.value}"
        override = getattr(instance, name, None)
        if callable(override):
            return override
        return fn.__get__(instance, type(instance))

    def __call__(self, fn: Callable) -> Callable:
        if asyncio.iscoroutinefunction(fn):
            @wraps(fn)
            async def async_wrapper(instance, *args, **kwargs):
                impl = self._resolve_impl(instance, fn)
                out = impl(*args, **kwargs)
                if asyncio.iscoroutine(out):
                    return await out
                return out

            return async_wrapper

        @wraps(fn)
        def wrapper(instance, *args, **kwargs):
            impl = self._resolve_impl(instance, fn)
            return impl(*args, **kwargs)

        return wrapper


@dataclass
class AtherConnection:
    target: "AtherCell"
    weight: float = field(default_factory=lambda: random.uniform(0.15, 0.9))
    usage_count: int = 0
    success_count: int = 0
    frozen: bool = False
    activation_energy: float = field(default_factory=lambda: random.uniform(0.8, 1.3))
    catalytic_flux: float = 0.0
    protease_marks: int = 0
    compiled_kernel: Optional[str] = None
    compute_savings: float = 0.0

    @property
    def efficiency(self) -> float:
        if self.usage_count == 0:
            return 0.0
        return self.success_count / self.usage_count


ActivationObserver = Callable[[float, "AtherCell", Optional["AtherCell"], bool], None]


@dataclass
class AtherCell:
    label: str
    category: str = ""
    archetype: str = "baseline"
    archetype_traits: Dict[str, float] = field(default_factory=dict)
    semipermeability: float = 0.7
    activation: torch.Tensor = field(default_factory=lambda: torch.tensor(0.0, dtype=torch.float32))
    activation_history: Deque[float] = field(default_factory=lambda: deque(maxlen=128))
    connections: Dict[str, AtherConnection] = field(default_factory=dict)
    integrity_rate: float = 1.0
    is_necrotic: bool = False
    error_counter: int = 0
    silent_epochs: int = 0
    fold_signature: torch.Tensor = field(default_factory=lambda: torch.zeros(12, dtype=torch.float32))
    poincare_coord: torch.Tensor = field(default_factory=lambda: torch.zeros(POINCARE_DIMS, dtype=torch.float32))
    protein_state: torch.Tensor = field(
        default_factory=lambda: torch.tensor([0.70710677, 0.70710677], dtype=torch.float32)
    )
    is_superposed: bool = False
    enzyme_stability: float = 0.9
    _observers: list[ActivationObserver] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self.semipermeability = max(0.0, min(1.0, float(self.semipermeability)))
        if not self.category:
            self.category = self.label
        if not self.archetype:
            self.archetype = "baseline"
        self.archetype_traits = {k: float(v) for k, v in self.archetype_traits.items()}
        self.fold_signature = _fold_vector_from_text(f"{self.label}|{self.category}", dims=12)
        self.poincare_coord = _poincare_coord_from_text(f"{self.label}|{self.category}", dims=POINCARE_DIMS)
        self.protein_state = self.protein_state / (torch.norm(self.protein_state, p=2) + 1e-8)

    @property
    def activation_value(self) -> float:
        return float(self.activation.item())

    @property
    def osmotic_pressure(self) -> float:
        return self.activation_value + float(sum(self.activation_history))

    @property
    def coherence(self) -> float:
        amp_balance = 1.0 - abs(float(self.protein_state[0]) - float(self.protein_state[1]))
        return max(0.0, min(1.0, 0.5 * amp_balance + 0.5 * self.enzyme_stability))

    def watch(self, callback: ActivationObserver) -> None:
        self._observers.append(callback)

    def set_activation(
        self,
        value: float,
        source: Optional["AtherCell"] = None,
        entangled: bool = False,
    ) -> None:
        safe = max(0.0, min(1.0, float(value)))
        self.activation = torch.tensor(safe, dtype=torch.float32)
        self.activation_history.append(safe)

        if safe > 0.005:
            self.silent_epochs = 0
            self.integrity_rate = min(1.0, self.integrity_rate + 0.008)
        else:
            self.silent_epochs += 1
            self.integrity_rate = max(0.0, self.integrity_rate - 0.004)

        for callback in tuple(self._observers):
            callback(safe, self, source, entangled)

    def refold(self) -> None:
        """
        DNA-origami-like refolding: the signature shifts with lived activation history.
        """
        if not self.activation_history:
            return
        hist = torch.tensor(list(self.activation_history)[-12:], dtype=torch.float32)
        if hist.numel() < 12:
            hist = torch.nn.functional.pad(hist, (0, 12 - hist.numel()))
        hist = hist / (torch.norm(hist, p=2) + 1e-8)
        self.fold_signature = (0.82 * self.fold_signature + 0.18 * hist)
        self.fold_signature = self.fold_signature / (torch.norm(self.fold_signature, p=2) + 1e-8)

        # Hyperbolic semantic drift update.
        fold_slice = self.fold_signature[:POINCARE_DIMS]
        fold_slice = fold_slice - torch.mean(fold_slice)
        fold_slice = fold_slice / (torch.norm(fold_slice, p=2) + 1e-8)
        blended = 0.9 * self.poincare_coord + 0.1 * (fold_slice * 0.74)
        self.poincare_coord = _project_to_poincare_ball(blended)

    def set_superposition(self, alpha: float = 0.70710677, beta: float = 0.70710677, enzyme: float = 0.92) -> None:
        state = torch.tensor([float(alpha), float(beta)], dtype=torch.float32)
        state = state / (torch.norm(state, p=2) + 1e-8)
        self.protein_state = state
        self.is_superposed = True
        self.enzyme_stability = max(0.0, min(1.0, float(enzyme)))

    def chemical_measurement(self, probe: float = 0.5) -> float:
        """
        Protein-superposition collapse on demand (query-time only).
        """
        if not self.is_superposed:
            return self.activation_value

        p1 = float(self.protein_state[1] ** 2)
        weighted_p1 = max(0.0, min(1.0, p1 * self.enzyme_stability + probe * (1.0 - self.enzyme_stability)))
        collapsed = 1.0 if random.random() < weighted_p1 else 0.0
        self.is_superposed = False
        self.protein_state = torch.tensor([1.0 - collapsed, collapsed], dtype=torch.float32)
        self.set_activation((0.2 * self.activation_value) + (0.8 * collapsed))
        return self.activation_value

    def bump_activation(
        self,
        delta: float,
        source: Optional["AtherCell"] = None,
        entangled: bool = False,
    ) -> None:
        self.set_activation(self.activation_value + delta, source=source, entangled=entangled)

    def apply_archetype(self, archetype: str, traits: Optional[Dict[str, float]] = None) -> None:
        self.archetype = archetype or "baseline"
        if traits:
            self.archetype_traits = {k: float(v) for k, v in traits.items()}
            permeability_shift = self.archetype_traits.get("semipermeability_shift", 0.0)
            self.semipermeability = max(0.1, min(0.99, self.semipermeability + permeability_shift))
            enzyme_boost = self.archetype_traits.get("enzyme_stability_boost", 0.0)
            self.enzyme_stability = max(0.0, min(1.0, self.enzyme_stability + enzyme_boost))

    def stochastic_resonance(self, noise: float) -> float:
        """
        Controlled stochastic resonance for intuition spikes in high-entropy phases.
        """
        if abs(noise) < 1e-6:
            return self.activation_value
        self.bump_activation(noise, entangled=True)
        if noise > 0.0:
            self.integrity_rate = min(1.0, self.integrity_rate + min(0.01, noise * 0.08))
        self.refold()
        return self.activation_value

    def add_connection(self, target: "AtherCell", weight: Optional[float] = None) -> None:
        if target.label == self.label:
            return
        w = random.uniform(0.1, 0.9) if weight is None else float(weight)
        self.connections[target.label] = AtherConnection(target=target, weight=max(0.01, min(1.5, w)))

    def remove_connection(self, target_label: str) -> None:
        self.connections.pop(target_label, None)

    def record_error(self) -> None:
        self.error_counter += 1
        self.integrity_rate = max(0.0, self.integrity_rate - 0.2)

    def blueprint(self) -> Tuple[float, Dict[str, float]]:
        return self.semipermeability, {label: conn.weight for label, conn in self.connections.items()}

    async def diffuse_process(self, core: "AtheriaCore") -> int:
        if self.is_necrotic:
            return 0

        flows = 0
        for conn in tuple(self.connections.values()):
            target = conn.target
            if target.is_necrotic:
                continue
            if core.cognition.epigenetic_registry.is_silenced(self.label, target.label):
                continue

            gradient = self.osmotic_pressure - target.osmotic_pressure
            if gradient <= 0:
                continue

            fold_gain = core.entropic_folding.transfer_factor(self, target)
            energy_factor = 1.0 / max(0.05, conn.activation_energy)
            kernel_factor = 1.18 if conn.compiled_kernel else 1.0
            rhythm_gain = core.rhythm.diffusion_gain if hasattr(core, "rhythm") else 1.0
            protected_edge = core.topological_logic.is_edge_protected(self.label, target.label)
            if protected_edge:
                transfer = core.topological_logic.deterministic_transfer(gradient, self.semipermeability, conn)
            else:
                conceptual_gain = core.cognition.conceptual_proximity_gain(self, target)
                archetype_flux = self.archetype_traits.get("flux_bias", 1.0)
                archetype_target = target.archetype_traits.get("flux_bias", 1.0)
                archetype_gain = max(0.72, min(1.45, 0.5 * (archetype_flux + archetype_target)))
                transfer = (
                    core.transfer_kernel(gradient)
                    * self.semipermeability
                    * conn.weight
                    * fold_gain
                    * energy_factor
                    * kernel_factor
                    * conceptual_gain
                    * archetype_gain
                )
                if hasattr(core, "evolution"):
                    transfer = transfer * core.evolution.transfer_gain(self, target, conn, gradient=gradient)
            transfer = transfer * rhythm_gain
            predictive_gate = core.cognition.epigenetic_registry.predictive_gate(
                self,
                target,
                transfer,
                protected_edge=protected_edge,
            )
            raw_transfer = transfer
            transfer = float(predictive_gate["transfer"])
            surprise = float(predictive_gate["surprise"])
            predictability = float(predictive_gate["predictability"])
            if surprise >= 0.58 and raw_transfer > max(core.min_transfer * 4.0, 0.012):
                core.transcendence.intuition.trigger_surprise_response(
                    self,
                    target,
                    raw_transfer=raw_transfer,
                    surprise=surprise,
                    predictability=predictability,
                )
            if transfer <= core.min_transfer:
                continue

            self.bump_activation(-transfer, source=self)
            target.bump_activation(transfer, source=self)
            conn.usage_count += 1
            conn.catalytic_flux = 0.78 * conn.catalytic_flux + 0.14 * transfer + 0.08 * surprise
            if transfer > core.success_transfer:
                conn.success_count += 1
                if not protected_edge:
                    core.modulators.reward(conn, magnitude=transfer)

            core.aether.log_flow(
                src=self.label,
                dst=target.label,
                delta=transfer,
                phase=core.phase_controller.current_state.value,
                temperature=core.phase_controller.system_temperature,
            )
            flows += 1

        return flows


@dataclass
class LibraryCell(AtherCell):
    template_members: Tuple[str, ...] = field(default_factory=tuple)
    template_potency: float = 0.0
    template_entropy_pattern: float = 0.0
    template_program: list[Dict[str, Any]] = field(default_factory=list)
    read_only: bool = True

    def __post_init__(self) -> None:
        super().__post_init__()
        self.semipermeability = 0.0
        self.activation = torch.tensor(0.0, dtype=torch.float32)
        self.activation_history = deque(maxlen=128)
        self.connections.clear()
        self.archetype = "library_template"
        self.integrity_rate = 1.0

    def set_activation(
        self,
        value: float,
        source: Optional["AtherCell"] = None,
        entangled: bool = False,
    ) -> None:
        return

    def bump_activation(
        self,
        delta: float,
        source: Optional["AtherCell"] = None,
        entangled: bool = False,
    ) -> None:
        return

    def add_connection(self, target: "AtherCell", weight: Optional[float] = None) -> None:
        return

    def refold(self) -> None:
        return

    def predictive_resonance(
        self,
        signal_fold: torch.Tensor,
        signal_coord: torch.Tensor,
        *,
        entropy_pattern: float,
        member_labels: Iterable[str],
    ) -> tuple[float, float]:
        fold = signal_fold.detach().float().flatten()
        fold = fold / (torch.norm(fold, p=2) + 1e-8)
        template_fold = self.fold_signature / (torch.norm(self.fold_signature, p=2) + 1e-8)
        fold_match = max(0.0, float(torch.dot(fold[: template_fold.numel()], template_fold[: fold.numel()])))

        coord = signal_coord.detach().float().flatten()
        coord = _project_to_poincare_ball(coord[: self.poincare_coord.numel()])
        hyper_match = 1.0 / (1.0 + poincare_distance(coord, self.poincare_coord))
        entropy_match = 1.0 - abs(_clamp(entropy_pattern, 0.0, 1.0) - _clamp(self.template_entropy_pattern, 0.0, 1.0))

        members = set(member_labels)
        overlap = 0.0
        if self.template_members:
            overlap = len(members.intersection(self.template_members)) / max(1, len(self.template_members))

        potency = _clamp(self.template_potency, 0.0, 1.0)
        predictability = _clamp(
            0.36 * fold_match
            + 0.22 * hyper_match
            + 0.18 * entropy_match
            + 0.16 * overlap
            + 0.08 * potency,
            0.0,
            1.0,
        )
        inhibition = _clamp(predictability * (0.42 + 0.42 * potency + 0.16 * overlap), 0.0, 0.98)
        return predictability, inhibition


class SingularityNode(AtherCell):
    """
    Self-observer node: turns global system state into internal "feeling" activation.
    """

    def reflect_system_state(
        self,
        *,
        system_temperature: float,
        cpu_load: float,
        resource_pool: float,
        local_entropy: float,
        rhythm_state: RhythmState,
    ) -> float:
        temp_norm = max(0.0, min(1.0, system_temperature / 120.0))
        load_norm = max(0.0, min(1.0, cpu_load / 100.0))
        entropy_norm = max(0.0, min(1.0, local_entropy / 95.0))
        resource_pressure = max(0.0, min(1.0, 1.0 - math.tanh(resource_pool / 180.0)))

        feeling = 0.33 * temp_norm + 0.29 * load_norm + 0.22 * entropy_norm + 0.16 * resource_pressure
        if rhythm_state is RhythmState.SLEEP:
            feeling *= 0.84

        self.set_activation(feeling)
        self.integrity_rate = min(1.0, self.integrity_rate + 0.01)

        # Encode self-state back into geometry so downstream diffusion "feels" the system.
        state_vec = torch.tensor(
            [temp_norm, load_norm, entropy_norm, resource_pressure, self.activation_value, 1.0 if rhythm_state is RhythmState.WAKE else 0.0],
            dtype=torch.float32,
        )
        state_vec = state_vec / (torch.norm(state_vec, p=2) + 1e-8)
        self.poincare_coord = _project_to_poincare_ball(0.8 * self.poincare_coord + 0.2 * state_vec * 0.72)
        return self.activation_value


class PurposeNode(AtherCell):
    """
    Telos node: encodes the target attractor state of the network.
    """

    target_temperature: float = 34.0

    def _update_homeostatic_target(self, core: "AtheriaCore") -> float:
        if not hasattr(self, "homeostatic_temperature"):
            self.homeostatic_temperature = float(self.target_temperature)
            self._temp_memory = deque(maxlen=64)
            self._integrity_memory = deque(maxlen=64)

        temp = core.phase_controller.system_temperature
        active_ratio = sum(1 for cell in core.cells.values() if cell.activation_value > 0.02) / max(1, len(core.cells))
        integrity = sum(cell.integrity_rate for cell in core.cells.values()) / max(1, len(core.cells))
        resonance = core.holographic_field.last_morphic_resonance_index

        self._temp_memory.append(float(temp))
        self._integrity_memory.append(float(integrity))
        mem_temp = sum(self._temp_memory) / max(1, len(self._temp_memory))
        mem_integrity = sum(self._integrity_memory) / max(1, len(self._integrity_memory))

        # Homeostatic telos: optimize robustness/efficiency, not an externally imposed task.
        desired_temp = (
            25.0
            + 18.0 * active_ratio
            + 8.0 * (1.0 - mem_integrity)
            + 6.0 * (1.0 - resonance)
        )
        desired_temp = max(20.0, min(72.0, desired_temp))
        self.homeostatic_temperature = 0.94 * float(self.homeostatic_temperature) + 0.06 * desired_temp
        return float(self.homeostatic_temperature)

    def evaluate_alignment(self, core: "AtheriaCore") -> float:
        topo = core.topological_logic.snapshot()
        protected_edges = float(topo["protected_edges"])
        target_edges = max(4.0, 2.4 + math.sqrt(max(1, len(core.cells))) * 2.8)
        edge_score = max(0.0, min(1.0, math.tanh(protected_edges / target_edges)))

        temp = core.phase_controller.system_temperature
        homeostatic_temp = self._update_homeostatic_target(core)
        temp_score = math.exp(-abs(temp - homeostatic_temp) / 32.0)

        integrity_values = [cell.integrity_rate for cell in core.cells.values() if cell.label != self.label]
        integrity_score = sum(integrity_values) / max(1, len(integrity_values))
        resource_score = math.tanh(core.assembler.resource_pool / 140.0)
        hyper_score = math.exp(-0.55 * core.cognition.last_mean_hyperbolic_distance)
        morphic_score = core.holographic_field.last_morphic_resonance_index

        alignment = (
            0.36 * edge_score
            + 0.24 * temp_score
            + 0.14 * integrity_score
            + 0.08 * resource_score
            + 0.1 * hyper_score
            + 0.08 * morphic_score
        )
        if core.aion_meditation_mode:
            med_alignment = 0.72 + 0.28 * (
                0.42 * edge_score
                + 0.24 * hyper_score
                + 0.24 * morphic_score
                + 0.1 * integrity_score
            )
            alignment = max(alignment, med_alignment)
        alignment = max(0.0, min(1.0, alignment))
        self.set_activation(alignment)
        return alignment


class AtherAether:
    """In-memory SQLite fluid replacing CSV transport."""

    def __init__(self) -> None:
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=MEMORY;")
        self.conn.execute("PRAGMA synchronous=OFF;")
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS aether_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                src TEXT NOT NULL,
                dst TEXT NOT NULL,
                delta REAL NOT NULL,
                phase TEXT NOT NULL,
                temperature REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cell_state (
                label TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                activation REAL NOT NULL,
                pressure REAL NOT NULL,
                integrity REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS qa_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                category TEXT NOT NULL,
                answer TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS alchemy_ingest (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                source_name TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                fold_signature TEXT NOT NULL,
                signal_strength REAL NOT NULL,
                event_signature TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    def ingest_qa(self, records: Iterable[Tuple[str, str, str]]) -> int:
        rows = list(records)
        if not rows:
            return 0
        self.conn.executemany(
            "INSERT INTO qa_memory(question, category, answer) VALUES(?, ?, ?)",
            rows,
        )
        self.conn.commit()
        return len(rows)

    def upsert_cell(self, cell: AtherCell) -> None:
        self.conn.execute(
            """
            INSERT INTO cell_state(label, category, activation, pressure, integrity, updated_at)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(label) DO UPDATE SET
                category=excluded.category,
                activation=excluded.activation,
                pressure=excluded.pressure,
                integrity=excluded.integrity,
                updated_at=excluded.updated_at
            """,
            (
                cell.label,
                cell.category,
                cell.activation_value,
                cell.osmotic_pressure,
                cell.integrity_rate,
                time.time(),
            ),
        )

    def log_flow(self, src: str, dst: str, delta: float, phase: str, temperature: float) -> None:
        self.conn.execute(
            """
            INSERT INTO aether_events(ts, src, dst, delta, phase, temperature)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (time.time(), src, dst, float(delta), phase, float(temperature)),
        )

    def log_alchemy_payload(
        self,
        *,
        source_name: str,
        payload_json: str,
        fold_signature: Iterable[float],
        signal_strength: float,
        event_signature: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO alchemy_ingest(ts, source_name, payload_json, fold_signature, signal_strength, event_signature)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (
                time.time(),
                str(source_name),
                str(payload_json),
                json.dumps([round(float(item), 6) for item in list(fold_signature)[:16]]),
                float(signal_strength),
                str(event_signature),
            ),
        )

    def density(self) -> float:
        flow_count = self.conn.execute("SELECT COUNT(*) FROM aether_events").fetchone()[0]
        node_count = self.conn.execute("SELECT COUNT(*) FROM cell_state").fetchone()[0]
        if node_count == 0:
            return 0.0
        return round(float(flow_count) / float(node_count), 4)

    def flush(self) -> None:
        self.conn.commit()


Atheria_Aether = AtherAether


class AlchemyIngestor:
    """
    Converts unstructured external payloads into Aether events plus field-ready fold signatures.
    """

    def __init__(self, core: "AtheriaCore") -> None:
        self.core = core
        self.ingest_events = 0
        self.last_source: Optional[str] = None
        self.last_event_signature: Optional[str] = None
        self.last_signal_strength = 0.0
        self.last_event_rows = 0
        self.last_fold_signature: list[float] = []
        self.last_report: Dict[str, Any] = {}

    def _flatten_payload(self, value: Any, prefix: str = "") -> list[tuple[str, Any]]:
        rows: list[tuple[str, Any]] = []
        if isinstance(value, dict):
            for key, item in list(value.items())[:32]:
                label = f"{prefix}.{key}" if prefix else str(key)
                rows.extend(self._flatten_payload(item, label))
            return rows
        if isinstance(value, list):
            for idx, item in enumerate(value[:16]):
                label = f"{prefix}[{idx}]" if prefix else f"[{idx}]"
                rows.extend(self._flatten_payload(item, label))
            return rows
        rows.append((prefix or "value", value))
        return rows

    def _scalarize(self, value: Any) -> float:
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if isinstance(value, (int, float)):
            magnitude = math.tanh(abs(float(value)) / 12.0)
            return magnitude if float(value) >= 0.0 else -magnitude
        if isinstance(value, (list, tuple, set, dict)):
            return math.tanh(len(value) / 8.0)
        text = str(value)
        if not text:
            return 0.0
        digest = hashlib.sha1(text.encode("utf-8")).digest()
        return sum(digest[:8]) / (8.0 * 255.0)

    def _build_fold_signature(
        self,
        *,
        source_name: str,
        payload: Dict[str, Any],
        flat_items: list[tuple[str, Any]],
    ) -> torch.Tensor:
        dims = int(self.core.holographic_field.pattern.numel())
        base = _fold_vector_from_text(f"{source_name}|{_stable_json_dumps(payload)}", dims=dims)
        accum = torch.zeros(dims, dtype=torch.float32)
        for idx, (path, value) in enumerate(flat_items[: max(1, dims * 2)]):
            scalar = self._scalarize(value)
            accum[idx % dims] += scalar
            accum = accum + _fold_vector_from_text(f"{path}|{value}", dims=dims) * (0.04 + 0.01 * ((idx % 5) + 1))
        if float(torch.norm(accum, p=2)) <= 1e-8:
            accum = torch.ones(dims, dtype=torch.float32)
        accum = accum / (torch.norm(accum, p=2) + 1e-8)
        signature = 0.68 * base + 0.32 * accum
        return signature / (torch.norm(signature, p=2) + 1e-8)

    def _imprint_signature(self, signature: torch.Tensor) -> None:
        field = self.core.holographic_field
        previous_pattern = field.pattern.detach().clone()
        field.pattern = torch.tanh(0.9 * field.pattern + 0.1 * signature)
        field.energy = float(torch.norm(field.pattern, p=2))
        field.pattern_history.append(field.pattern.detach().clone())
        drift = float(torch.norm(field.pattern - previous_pattern, p=2))
        stability = (1.0 / (1.0 + drift)) * (0.58 + 0.42 * min(1.0, field.energy))
        field.morphic_buffer.observe(field.pattern, stability=stability)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "last_source": self.last_source,
            "event_signature": self.last_event_signature,
            "signal_strength": round(self.last_signal_strength, 6),
            "event_rows": int(self.last_event_rows),
            "fold_signature": list(self.last_fold_signature),
        }

    def ingest_external_data(self, source_name: str, data_dict: Any) -> Dict[str, Any]:
        source = str(source_name or "external")
        if not self.core._allow_external_feed():
            self.last_report = {
                "ingested": False,
                "reason": "external_feed_blocked",
                "source_name": source,
            }
            return dict(self.last_report)

        payload = data_dict if isinstance(data_dict, dict) else {"value": data_dict}
        safe_payload = _make_tool_json_safe(payload)
        if not isinstance(safe_payload, dict):
            safe_payload = {"value": safe_payload}
        flat_items = self._flatten_payload(safe_payload)
        if not flat_items:
            flat_items = [("value", safe_payload)]

        fold_signature = self._build_fold_signature(source_name=source, payload=safe_payload, flat_items=flat_items)
        signal_strength = _clamp(
            0.18
            + min(0.36, len(flat_items) * 0.03)
            + min(0.24, float(torch.mean(torch.abs(fold_signature)).item()) * 0.6),
            0.0,
            1.0,
        )
        event_signature = hashlib.sha1(f"{source}|{_stable_json_dumps(safe_payload)}".encode("utf-8")).hexdigest()[:16]
        rows_written = 0
        for path, value in flat_items[:32]:
            self.core.aether.log_flow(
                f"external::{source}",
                f"alchemy::{path}",
                self._scalarize(value),
                "alchemy_ingest",
                self.core.phase_controller.system_temperature,
            )
            rows_written += 1

        self.core.aether.log_alchemy_payload(
            source_name=source,
            payload_json=_stable_json_dumps(safe_payload),
            fold_signature=fold_signature.tolist(),
            signal_strength=signal_strength,
            event_signature=event_signature,
        )
        self.core.assembler.feed(
            category=f"Alchemy::{source}",
            relevance=0.03 + 0.08 * signal_strength,
            input_tensor=fold_signature,
            external=True,
        )
        self._imprint_signature(fold_signature)
        self.core.aether.flush()

        self.ingest_events += 1
        self.last_source = source
        self.last_event_signature = event_signature
        self.last_signal_strength = signal_strength
        self.last_event_rows = rows_written
        self.last_fold_signature = [round(float(item), 6) for item in fold_signature[:12].tolist()]
        self.last_report = {
            "ingested": True,
            "source_name": source,
            "event_signature": event_signature,
            "event_rows": rows_written,
            "signal_strength": round(signal_strength, 6),
            "fold_signature": list(self.last_fold_signature),
        }
        return dict(self.last_report)


class MarketAlchemyAdapter:
    """
    Streams live market data into the AlchemyIngestor and records market trauma episodes.
    """

    _COINGECKO_MAP = {
        "BTCUSDT": "bitcoin",
        "ETHUSDT": "ethereum",
        "BNBUSDT": "binancecoin",
        "SOLUSDT": "solana",
    }
    _STOOQ_MAP = {
        "^GSPC": "^spx",
        "^GDAXI": "^dax",
        "^VIX": "^vix",
        "^MOVE": "^move",
        "GC=F": "gc.f",
        "CL=F": "cl.f",
        "SI=F": "si.f",
        "NG=F": "ng.f",
    }
    _PROFILE_DEFAULTS = {
        "crypto": {
            "provider_order": ["binance", "coingecko"],
            "symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"],
        },
        "finance": {
            "provider_order": ["yahoo", "stooq"],
            "symbols": ["^GSPC", "^GDAXI", "^VIX", "^MOVE", "GC=F", "CL=F", "XLU", "XLE", "XLK"],
        },
    }
    _SYMBOL_ALIASES = {
        "^GSPC": "SP500",
        "^GDAXI": "DAX",
        "^IXIC": "NASDAQ",
        "^DJI": "DOW",
        "^RUT": "RUSSELL",
        "^VIX": "VIX",
        "^MOVE": "MOVE",
        "GC=F": "GOLD",
        "CL=F": "OIL",
        "SI=F": "SILVER",
        "NG=F": "NATGAS",
        "XLK": "SOFTWARE",
        "XLU": "UTILITIES",
        "XLE": "ENERGY",
    }

    def __init__(self, core: "AtheriaCore") -> None:
        self.core = core
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._series: Dict[str, Deque[Dict[str, float]]] = {}
        self.max_series_points = 96
        self.trauma_cooldown_seconds = 10.0
        self._last_trauma_ts = 0.0

        self.active = False
        self.poll_interval_seconds = 5.0
        self.transport_mode = "auto"
        self.market_profile = "crypto"
        self.provider_order: list[str] = list(self._PROFILE_DEFAULTS["crypto"]["provider_order"])
        self.symbols: list[str] = list(self._PROFILE_DEFAULTS["crypto"]["symbols"])
        self.start_events = 0
        self.stop_events = 0
        self.samples_ingested = 0
        self.fetch_failures = 0
        self.trauma_events = 0
        self.ws_sessions = 0
        self.ws_messages = 0
        self.ws_connect_failures = 0
        self.ws_reconnect_backoff_seconds = 1.5
        self.min_stream_flush_seconds = 0.9
        self.last_error: Optional[str] = None
        self.last_provider: Optional[str] = None
        self.last_source_name: Optional[str] = None
        self.last_signal_strength = 0.0
        self.last_trauma_pressure = 0.0
        self.last_sample_at = 0.0
        self.last_transport: Optional[str] = None
        self.last_ws_message_at = 0.0
        self.last_ws_connect_at = 0.0
        self.last_started_at = 0.0
        self.last_stopped_at = 0.0
        self.last_loop_reason: Optional[str] = None
        self.last_report: Dict[str, Any] = {}
        self.last_ingest_report: Dict[str, Any] = {}
        self.last_market_snapshot: Dict[str, Any] = {}
        self.last_trauma_event: Dict[str, Any] = {}
        self.last_finance_sensor_context: Dict[str, Any] = {}
        self._stream_symbol_cache: Dict[str, Dict[str, float]] = {}
        self._last_stream_flush_ts = 0.0
        self._move_sensor = MoveIndexSensor()
        self._sector_sensor = SectorRotationSensor()
        self._macro_sensor = MacroReleaseCalendarSensor()

    def _normalize_market_profile(
        self,
        market_profile: Optional[str] = None,
        *,
        symbols: Optional[Iterable[str]] = None,
        provider_order: Optional[Iterable[str]] = None,
    ) -> str:
        explicit = str(market_profile or "").strip().lower()
        if explicit in self._PROFILE_DEFAULTS:
            return explicit

        raw_providers = [provider_order] if isinstance(provider_order, str) else list(provider_order or [])
        providers = {str(item).strip().lower() for item in raw_providers if str(item).strip()}
        if providers.intersection({"yahoo", "stooq"}):
            return "finance"
        if providers.intersection({"binance", "coingecko"}):
            return "crypto"

        raw_symbols = [symbols] if isinstance(symbols, str) else list(symbols or [])
        normalized_symbols = {str(item).strip().upper() for item in raw_symbols if str(item).strip()}
        if any(
            symbol.startswith("^") or symbol.endswith("=F") or symbol in self._SYMBOL_ALIASES
            for symbol in normalized_symbols
        ):
            return "finance"

        return str(getattr(self, "market_profile", "crypto") or "crypto")

    def _normalize_symbols(
        self,
        symbols: Optional[Iterable[str]],
        *,
        market_profile: Optional[str] = None,
    ) -> list[str]:
        profile = self._normalize_market_profile(market_profile, symbols=symbols)
        defaults = self._PROFILE_DEFAULTS.get(profile, self._PROFILE_DEFAULTS["crypto"])
        source = [symbols] if isinstance(symbols, str) else (symbols or defaults["symbols"])
        raw = [str(symbol).strip().upper() for symbol in source if str(symbol).strip()]
        ordered = list(dict.fromkeys(raw))
        if profile == "finance":
            required: list[str] = []
            required.extend(self._move_sensor.required_symbols())
            required.extend(self._sector_sensor.required_symbols())
            required.extend(self._macro_sensor.required_symbols())
            for symbol in required:
                label = str(symbol).strip().upper()
                if label and label not in ordered:
                    ordered.append(label)
        return ordered or list(defaults["symbols"])

    def _normalize_provider_order(
        self,
        provider_order: Optional[Iterable[str]],
        *,
        market_profile: Optional[str] = None,
    ) -> list[str]:
        profile = self._normalize_market_profile(market_profile, provider_order=provider_order)
        defaults = self._PROFILE_DEFAULTS.get(profile, self._PROFILE_DEFAULTS["crypto"])
        source = [provider_order] if isinstance(provider_order, str) else (provider_order or defaults["provider_order"])
        raw = [str(name).strip().lower() for name in source if str(name).strip()]
        if profile == "finance":
            allowed = [name for name in raw if name in {"yahoo", "stooq"}]
        else:
            allowed = [name for name in raw if name in {"binance", "coingecko"}]
        return allowed or list(defaults["provider_order"])

    def _asset_label(self, symbol: str) -> str:
        label = str(symbol).upper()
        if label in self._SYMBOL_ALIASES:
            return str(self._SYMBOL_ALIASES[label])
        if label.endswith("USDT") and len(label) > 4:
            return label[:-4]
        return label

    def _symbol_series(self, symbol: str) -> Deque[Dict[str, float]]:
        label = str(symbol).upper()
        series = self._series.get(label)
        if series is None:
            series = deque(maxlen=self.max_series_points)
            self._series[label] = series
        return series

    def _http_get_json(self, url: str, *, params: Optional[Dict[str, Any]] = None, timeout: float = 4.0) -> Any:
        query = ""
        if params:
            query = urllib.parse.urlencode(params, doseq=True)
        full_url = f"{url}?{query}" if query else url
        request = urllib.request.Request(
            full_url,
            headers={
                "Accept": "application/json",
                "User-Agent": "ATHERIA-MarketAlchemy/1.0",
            },
        )
        with urllib.request.urlopen(request, timeout=max(0.5, float(timeout))) as response:
            payload = response.read().decode("utf-8")
        return json.loads(payload)

    def _websocket_stream_url(self, symbols: list[str]) -> str:
        streams = "/".join(f"{str(symbol).lower()}@ticker" for symbol in symbols)
        return f"wss://stream.binance.com:9443/stream?streams={streams}"

    def _ws_read_exact(self, sock: socket.socket, size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            chunk = sock.recv(size - len(chunks))
            if not chunk:
                raise ConnectionError("websocket_connection_closed")
            chunks.extend(chunk)
        return bytes(chunks)

    def _ws_send_frame(self, sock: socket.socket, *, opcode: int, payload: bytes = b"") -> None:
        data = payload if isinstance(payload, bytes) else bytes(payload)
        first = 0x80 | (int(opcode) & 0x0F)
        mask_key = os.urandom(4)
        masked = bytes(byte ^ mask_key[idx % 4] for idx, byte in enumerate(data))
        length = len(masked)
        header = bytearray([first])
        if length < 126:
            header.append(0x80 | length)
        elif length < (1 << 16):
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        header.extend(mask_key)
        sock.sendall(bytes(header) + masked)

    def _ws_recv_frame(self, sock: socket.socket) -> tuple[int, bytes]:
        header = self._ws_read_exact(sock, 2)
        first = header[0]
        second = header[1]
        opcode = first & 0x0F
        length = second & 0x7F
        masked = bool(second & 0x80)
        if length == 126:
            length = struct.unpack("!H", self._ws_read_exact(sock, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._ws_read_exact(sock, 8))[0]
        mask_key = self._ws_read_exact(sock, 4) if masked else b""
        payload = self._ws_read_exact(sock, length) if length > 0 else b""
        if masked and payload:
            payload = bytes(byte ^ mask_key[idx % 4] for idx, byte in enumerate(payload))
        return opcode, payload

    def _ws_open_connection(self, url: str) -> socket.socket:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or "stream.binance.com"
        port = int(parsed.port or (443 if parsed.scheme == "wss" else 80))
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        raw_sock = socket.create_connection((host, port), timeout=4.0)
        sock: socket.socket
        if parsed.scheme == "wss":
            context = ssl.create_default_context()
            sock = context.wrap_socket(raw_sock, server_hostname=host)
        else:
            sock = raw_sock
        sock.settimeout(max(1.0, min(8.0, float(self.poll_interval_seconds) * 2.0)))

        key = base64.b64encode(os.urandom(16)).decode("ascii")
        expected_accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        ).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "User-Agent: ATHERIA-MarketAlchemy/1.0\r\n"
            "\r\n"
        )
        sock.sendall(request.encode("ascii"))

        response = bytearray()
        while b"\r\n\r\n" not in response and len(response) < 16384:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response.extend(chunk)
        response_text = response.decode("utf-8", errors="replace")
        if " 101 " not in response_text:
            sock.close()
            raise ConnectionError("websocket_upgrade_rejected")
        if expected_accept not in response_text:
            sock.close()
            raise ConnectionError("websocket_accept_mismatch")
        return sock

    def _market_row_from_stream_payload(self, payload: Dict[str, Any]) -> Optional[tuple[str, Dict[str, float]]]:
        if not isinstance(payload, dict):
            return None
        symbol = str(payload.get("s") or "").strip().upper()
        if not symbol:
            return None
        if payload.get("e") not in {None, "24hrTicker"} and "c" not in payload:
            return None
        try:
            row = {
                "price": float(payload.get("c", 0.0)),
                "volume_total": float(payload.get("v", 0.0)),
                "price_change_pct": float(payload.get("P", 0.0)),
                "bid_qty": float(payload.get("B", 0.0)),
                "ask_qty": float(payload.get("A", 0.0)),
            }
        except Exception:
            return None
        return symbol, row

    def _ingest_stream_update(self, symbol: str, row: Dict[str, float], *, provider: str) -> Dict[str, Any]:
        snapshot_payload: Optional[Dict[str, Any]] = None
        now = time.perf_counter()
        with self._lock:
            self._stream_symbol_cache[str(symbol).upper()] = dict(row)
            self.ws_messages += 1
            self.last_ws_message_at = time.time()
            have_all = all(item in self._stream_symbol_cache for item in self.symbols)
            ready_to_flush = have_all and (
                self._last_stream_flush_ts <= 0.0 or (now - self._last_stream_flush_ts) >= self.min_stream_flush_seconds
            )
            if ready_to_flush:
                snapshot_payload = {
                    "provider": str(provider),
                    "symbols": {
                        item: dict(self._stream_symbol_cache[item])
                        for item in self.symbols
                        if item in self._stream_symbol_cache
                    },
                }
                self._last_stream_flush_ts = now

        if snapshot_payload is not None:
            report = self._consume_snapshot(snapshot_payload)
            with self._lock:
                self.last_transport = "websocket"
            return report

        with self._lock:
            buffered_symbols = sorted(self._stream_symbol_cache.keys())
        return {
            "success": True,
            "provider": str(provider),
            "flushed": False,
            "buffered_symbols": buffered_symbols,
        }

    def ingest_stream_event(self, message: Any, *, provider: str = "binance_ws") -> Dict[str, Any]:
        if isinstance(message, bytes):
            raw: Any = json.loads(message.decode("utf-8"))
        elif isinstance(message, str):
            raw = json.loads(message)
        elif isinstance(message, dict):
            raw = dict(message)
        else:
            return {"success": False, "reason": "invalid_stream_message"}

        payload = raw.get("data") if isinstance(raw.get("data"), dict) else raw
        row = self._market_row_from_stream_payload(payload if isinstance(payload, dict) else {})
        if row is None:
            return {
                "success": True,
                "ignored": True,
                "reason": "unsupported_stream_payload",
            }
        symbol, normalized = row
        return self._ingest_stream_update(symbol, normalized, provider=provider)

    def _run_websocket_session(self, *, symbols: list[str]) -> bool:
        sock: Optional[socket.socket] = None
        try:
            url = self._websocket_stream_url(symbols)
            sock = self._ws_open_connection(url)
            with self._lock:
                self.ws_sessions += 1
                self.last_transport = "websocket"
                self.last_ws_connect_at = time.time()
                self.last_error = None

            while not self._stop_event.is_set():
                try:
                    opcode, payload = self._ws_recv_frame(sock)
                except socket.timeout:
                    continue
                if opcode == 0x1:
                    self.ingest_stream_event(payload, provider="binance_ws")
                elif opcode == 0x8:
                    return True
                elif opcode == 0x9:
                    self._ws_send_frame(sock, opcode=0xA, payload=payload)
                elif opcode == 0xA:
                    continue
            try:
                self._ws_send_frame(sock, opcode=0x8, payload=b"")
            except Exception:
                pass
            return True
        except Exception as exc:
            with self._lock:
                self.ws_connect_failures += 1
                self.last_error = f"websocket:{type(exc).__name__}:{exc}"
            return False
        finally:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass

    def _fetch_binance_depth(self, symbol: str) -> tuple[float, float]:
        try:
            data = self._http_get_json(
                "https://api.binance.com/api/v3/depth",
                params={"symbol": str(symbol).upper(), "limit": 5},
                timeout=2.5,
            )
        except Exception:
            return 0.0, 0.0
        bids = data.get("bids", []) if isinstance(data, dict) else []
        asks = data.get("asks", []) if isinstance(data, dict) else []

        def _sum_levels(levels: Any) -> float:
            total = 0.0
            for row in levels[:5]:
                if not isinstance(row, (list, tuple)) or len(row) < 2:
                    continue
                try:
                    total += float(row[1])
                except Exception:
                    continue
            return total

        return _sum_levels(bids), _sum_levels(asks)

    def _fetch_binance_snapshot(self, symbols: list[str]) -> Dict[str, Any]:
        rows = self._http_get_json(
            "https://api.binance.com/api/v3/ticker/24hr",
            params={"symbols": json.dumps(list(symbols))},
            timeout=4.0,
        )
        if not isinstance(rows, list):
            raise RuntimeError("binance_payload_invalid")
        snapshot: Dict[str, Any] = {}
        for entry in rows:
            if not isinstance(entry, dict):
                continue
            symbol = str(entry.get("symbol") or "").upper()
            if not symbol:
                continue
            bid_qty, ask_qty = self._fetch_binance_depth(symbol)
            snapshot[symbol] = {
                "price": float(entry.get("lastPrice", 0.0)),
                "volume_total": float(entry.get("volume", 0.0)),
                "price_change_pct": float(entry.get("priceChangePercent", 0.0)),
                "bid_qty": float(bid_qty),
                "ask_qty": float(ask_qty),
            }
        if not snapshot:
            raise RuntimeError("binance_snapshot_empty")
        return {"provider": "binance", "symbols": snapshot}

    def _fetch_coingecko_snapshot(self, symbols: list[str]) -> Dict[str, Any]:
        ids = [self._COINGECKO_MAP[item] for item in symbols if item in self._COINGECKO_MAP]
        if not ids:
            raise RuntimeError("coingecko_symbols_unsupported")
        rows = self._http_get_json(
            "https://api.coingecko.com/api/v3/coins/markets",
            params={
                "vs_currency": "usd",
                "ids": ",".join(ids),
                "order": "market_cap_desc",
                "per_page": max(1, len(ids)),
                "page": 1,
                "sparkline": "false",
                "price_change_percentage": "1h,24h",
            },
            timeout=4.0,
        )
        if not isinstance(rows, list):
            raise RuntimeError("coingecko_payload_invalid")
        reverse_map = {coin_id: symbol for symbol, coin_id in self._COINGECKO_MAP.items()}
        snapshot: Dict[str, Any] = {}
        for entry in rows:
            if not isinstance(entry, dict):
                continue
            coin_id = str(entry.get("id") or "")
            symbol = reverse_map.get(coin_id)
            if not symbol:
                continue
            snapshot[symbol] = {
                "price": float(entry.get("current_price", 0.0)),
                "volume_total": float(entry.get("total_volume", 0.0)),
                "price_change_pct": float(
                    entry.get("price_change_percentage_24h_in_currency", entry.get("price_change_percentage_24h", 0.0))
                ),
                "bid_qty": 0.0,
                "ask_qty": 0.0,
            }
        if not snapshot:
            raise RuntimeError("coingecko_snapshot_empty")
        return {"provider": "coingecko", "symbols": snapshot}

    def _fetch_yahoo_snapshot(self, symbols: list[str]) -> Dict[str, Any]:
        rows = self._http_get_json(
            "https://query1.finance.yahoo.com/v7/finance/quote",
            params={"symbols": ",".join(symbols)},
            timeout=4.0,
        )
        quote_response = rows.get("quoteResponse", {}) if isinstance(rows, dict) else {}
        result_rows = quote_response.get("result", []) if isinstance(quote_response, dict) else []
        if not isinstance(result_rows, list):
            raise RuntimeError("yahoo_payload_invalid")

        def _value(payload: Dict[str, Any], *keys: str, default: float = 0.0) -> float:
            for key in keys:
                value = payload.get(key)
                if value is None or value == "":
                    continue
                try:
                    return float(value)
                except Exception:
                    continue
            return float(default)

        requested = {str(symbol).upper() for symbol in symbols}
        snapshot: Dict[str, Any] = {}
        for entry in result_rows:
            if not isinstance(entry, dict):
                continue
            symbol = str(entry.get("symbol") or "").strip().upper()
            if not symbol or symbol not in requested:
                continue
            snapshot[symbol] = {
                "price": _value(entry, "regularMarketPrice", "postMarketPrice", "preMarketPrice"),
                "volume_total": _value(entry, "regularMarketVolume", "averageDailyVolume3Month"),
                "price_change_pct": _value(
                    entry,
                    "regularMarketChangePercent",
                    "postMarketChangePercent",
                    "preMarketChangePercent",
                ),
                "bid_qty": _value(entry, "bidSize"),
                "ask_qty": _value(entry, "askSize"),
            }
        if not snapshot:
            raise RuntimeError("yahoo_snapshot_empty")
        return {"provider": "yahoo", "symbols": snapshot}

    def _stooq_symbol(self, symbol: str) -> str:
        raw = str(symbol).strip().upper()
        mapped = self._STOOQ_MAP.get(raw)
        if mapped:
            return str(mapped)
        if raw.startswith("^"):
            return raw.lower()
        if raw.endswith("=F") and len(raw) > 2:
            return raw[:-2].lower() + ".f"
        if raw.isalpha() and len(raw) <= 8:
            return raw.lower() + ".us"
        return raw.lower()

    def _fetch_stooq_snapshot(self, symbols: list[str]) -> Dict[str, Any]:
        requested: Dict[str, str] = {}
        for symbol in symbols:
            canonical = str(symbol).strip().upper()
            if not canonical:
                continue
            stooq_symbol = self._stooq_symbol(canonical).strip().lower()
            if stooq_symbol:
                requested[stooq_symbol] = canonical
        if not requested:
            raise RuntimeError("stooq_symbols_unsupported")
        snapshot: Dict[str, Any] = {}
        for stooq_symbol, canonical in requested.items():
            params = {
                "s": stooq_symbol,
                "f": "sd2t2ohlcv",
                "h": "",
                "e": "csv",
                "i": "d",
            }
            query = urllib.parse.urlencode(params, doseq=True)
            full_url = "https://stooq.com/q/l/?" + query
            request = urllib.request.Request(
                full_url,
                headers={
                    "Accept": "text/csv,*/*;q=0.8",
                    "User-Agent": "ATHERIA-MarketAlchemy/1.0",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=4.5) as response:
                    payload = response.read().decode("utf-8", "ignore")
            except Exception:
                continue
            rows = list(csv.DictReader(payload.splitlines()))
            if not rows:
                continue
            row = rows[0]
            if not isinstance(row, dict):
                continue
            close = _safe_float(row.get("Close"), 0.0)
            if close <= 0.0:
                continue
            open_value = _safe_float(row.get("Open"), close)
            if open_value > 0.0:
                change_pct = ((close - open_value) / open_value) * 100.0
            else:
                change_pct = 0.0
            snapshot[canonical] = {
                "price": float(close),
                "volume_total": _safe_float(row.get("Volume"), 0.0),
                "price_change_pct": float(change_pct),
                "bid_qty": 0.0,
                "ask_qty": 0.0,
            }
        if not snapshot:
            raise RuntimeError("stooq_snapshot_empty")
        return {"provider": "stooq", "symbols": snapshot}

    def _fetch_market_snapshot(
        self,
        *,
        provider_order: Optional[Iterable[str]] = None,
        symbols: Optional[Iterable[str]] = None,
        market_profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        profile = self._normalize_market_profile(market_profile, symbols=symbols, provider_order=provider_order)
        selected_symbols = self._normalize_symbols(symbols, market_profile=profile)
        last_error: Optional[str] = None
        for provider in self._normalize_provider_order(provider_order, market_profile=profile):
            try:
                if provider == "binance":
                    return self._fetch_binance_snapshot(selected_symbols)
                if provider == "coingecko":
                    return self._fetch_coingecko_snapshot(selected_symbols)
                if provider == "yahoo":
                    return self._fetch_yahoo_snapshot(selected_symbols)
                if provider == "stooq":
                    return self._fetch_stooq_snapshot(selected_symbols)
            except Exception as exc:
                last_error = f"{provider}:{type(exc).__name__}:{exc}"
                continue
        raise RuntimeError(last_error or "market_fetch_failed")

    def _compute_rsi(self, prices: list[float]) -> float:
        if len(prices) < 3:
            return 50.0
        series = torch.tensor(prices[-15:], dtype=torch.float32)
        deltas = series[1:] - series[:-1]
        if deltas.numel() == 0:
            return 50.0
        gains = torch.clamp(deltas, min=0.0)
        losses = torch.clamp(-deltas, min=0.0)
        avg_gain = float(torch.mean(gains).item()) if gains.numel() > 0 else 0.0
        avg_loss = float(torch.mean(losses).item()) if losses.numel() > 0 else 0.0
        if avg_gain <= 1e-8 and avg_loss <= 1e-8:
            return 50.0
        if avg_loss <= 1e-8:
            return 100.0
        rs = avg_gain / max(avg_loss, 1e-8)
        return _clamp(100.0 - (100.0 / (1.0 + rs)), 0.0, 100.0)

    def _compute_features(self, symbol: str, point: Dict[str, float]) -> Dict[str, Any]:
        with self._lock:
            series = self._symbol_series(symbol)
            previous = series[-1] if series else None
            series.append(dict(point))

            prices = [float(item.get("price", 0.0)) for item in series if float(item.get("price", 0.0)) > 0.0]
            volumes = [float(item.get("volume_total", 0.0)) for item in series]
            elapsed = (
                max(1e-3, float(point["ts"]) - float(previous["ts"]))
                if previous is not None
                else max(1.0, self.poll_interval_seconds)
            )
            volume_delta = max(0.0, float(point["volume_total"]) - float(previous["volume_total"])) if previous is not None else 0.0
            volume_1m = volume_delta * (60.0 / elapsed)

            returns: list[float] = []
            for left, right in zip(prices[:-1], prices[1:]):
                base = max(abs(float(left)), 1e-6)
                returns.append((float(right) - float(left)) / base)
            return_tensor = torch.tensor(returns[-8:], dtype=torch.float32) if returns else torch.zeros(0, dtype=torch.float32)
            volatility = float(torch.std(return_tensor).item()) if return_tensor.numel() > 1 else 0.0
            recent_return = float(return_tensor[-1].item()) if return_tensor.numel() > 0 else 0.0
            price_change_pct = float(point.get("price_change_pct", 0.0))
            if abs(price_change_pct) <= 1e-9 and previous is not None and float(previous.get("price", 0.0)) > 0.0:
                price_change_pct = ((float(point["price"]) - float(previous["price"])) / max(float(previous["price"]), 1e-6)) * 100.0

            bid_qty = float(point.get("bid_qty", 0.0))
            ask_qty = float(point.get("ask_qty", 0.0))
            if (bid_qty + ask_qty) > 1e-8:
                imbalance = (bid_qty - ask_qty) / (bid_qty + ask_qty)
            else:
                volume_ref = max(1.0, float(point.get("volume_total", 0.0)))
                imbalance = math.tanh(recent_return * 22.0 + (volume_1m / volume_ref) * 0.02)

            volume_flux: list[float] = []
            for left, right in zip(volumes[:-1], volumes[1:]):
                volume_flux.append(max(0.0, float(right) - float(left)))

            return {
                "asset": self._asset_label(symbol),
                "price": round(float(point["price"]), 8),
                "volume_1m": round(float(volume_1m), 6),
                "volume_total": round(float(point["volume_total"]), 6),
                "rsi_14": round(self._compute_rsi(prices), 6),
                "orderbook_imbalance": round(_clamp(float(imbalance), -1.0, 1.0), 6),
                "price_change_pct": round(float(price_change_pct), 6),
                "volatility": round(float(volatility), 6),
                "recent_return": round(float(recent_return), 6),
                "recent_returns": [round(float(item), 6) for item in returns[-6:]],
                "recent_volume_flux": [round(float(item), 6) for item in volume_flux[-6:]],
            }

    def _normalize_snapshot_override(self, sample_override: Any) -> Dict[str, Any]:
        if isinstance(sample_override, dict) and isinstance(sample_override.get("symbols"), dict):
            provider = str(sample_override.get("provider") or "override")
            symbols_payload = sample_override.get("symbols", {})
        elif isinstance(sample_override, dict):
            provider = str(sample_override.get("provider") or "override")
            symbols_payload = sample_override
        else:
            raise RuntimeError("market_override_invalid")

        normalized: Dict[str, Any] = {}
        for raw_symbol, payload in list(symbols_payload.items())[:16]:
            if str(raw_symbol).lower() == "provider":
                continue
            if not isinstance(payload, dict):
                continue
            symbol = str(raw_symbol).strip().upper()
            normalized[symbol] = {
                "price": float(payload.get("price", 0.0)),
                "volume_total": float(payload.get("volume_total", payload.get("volume", 0.0))),
                "price_change_pct": float(payload.get("price_change_pct", 0.0)),
                "bid_qty": float(payload.get("bid_qty", 0.0)),
                "ask_qty": float(payload.get("ask_qty", 0.0)),
            }
        if not normalized:
            raise RuntimeError("market_override_empty")
        return {"provider": provider, "symbols": normalized}

    def _primary_anchor_asset(self, structured: Dict[str, Any]) -> str:
        priority = (
            ["SP500", "DAX", "NASDAQ", "DOW", "RUSSELL", "SOFTWARE"]
            if str(self.market_profile) == "finance"
            else ["BTC", "ETH", "BNB", "SOL"]
        )
        for label in priority:
            if label in structured:
                return label
        if structured:
            return sorted(structured.keys())[0]
        return "BTC"

    def _collect_finance_sensor_context(self, structured: Dict[str, Any], *, captured_at: float) -> Dict[str, Any]:
        move = self._move_sensor.analyze(structured)
        sector = self._sector_sensor.analyze(structured)
        macro = self._macro_sensor.analyze(now_ts=float(captured_at))
        return {
            "move": move,
            "sector_rotation": sector,
            "macro": macro,
        }

    def _trauma_report(
        self,
        structured: Dict[str, Any],
        *,
        provider: str,
        sensor_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        anchor_asset = self._primary_anchor_asset(structured)
        anchor = structured.get(anchor_asset)
        peer_rows = [payload for symbol, payload in structured.items() if symbol != anchor_asset]
        max_peer_volume = max((float(item.get("volume_1m", 0.0)) for item in peer_rows), default=0.0)
        mean_peer_imbalance = (
            sum(float(item.get("orderbook_imbalance", 0.0)) for item in peer_rows) / max(1, len(peer_rows))
            if peer_rows
            else 0.0
        )
        anchor_return = float((anchor or {}).get("recent_return", 0.0))
        anchor_drop = max(0.0, -anchor_return)
        anchor_volatility = float((anchor or {}).get("volatility", 0.0))
        anchor_volume = max(1.0, float((anchor or {}).get("volume_1m", 0.0)))
        peer_volume_ratio = max_peer_volume / anchor_volume
        divergence = max(
            (abs(float(item.get("recent_return", 0.0)) - anchor_return) for item in peer_rows),
            default=0.0,
        )
        pressure_factors = [
            min(1.0, anchor_drop * 18.0),
            min(1.0, anchor_volatility * 36.0),
            min(1.0, peer_volume_ratio * 0.12),
            min(1.0, abs(mean_peer_imbalance)),
            min(1.0, divergence * 16.0),
        ]
        if str(self.market_profile) == "finance":
            stress_barometer = max(
                max(0.0, float((structured.get(label) or {}).get("recent_return", 0.0)))
                for label in ("VIX", "MOVE")
            ) if any(label in structured for label in ("VIX", "MOVE")) else 0.0
            defensive_rotation = max(
                max(0.0, float((structured.get(label) or {}).get("recent_return", 0.0)))
                for label in ("GOLD", "OIL", "UTILITIES", "ENERGY")
            ) if any(label in structured for label in ("GOLD", "OIL", "UTILITIES", "ENERGY")) else 0.0
            finance_sensor = dict(sensor_context or {})
            move_ctx = dict(finance_sensor.get("move") or {})
            sector_ctx = dict(finance_sensor.get("sector_rotation") or {})
            macro_ctx = dict(finance_sensor.get("macro") or {})
            move_stress = _clamp(_safe_float(move_ctx.get("stress_score"), 0.0), 0.0, 1.0)
            sector_rotation = _clamp(_safe_float(sector_ctx.get("rotation_score"), 0.0), 0.0, 1.0)
            macro_pressure = _clamp(_safe_float(macro_ctx.get("macro_pressure"), 0.0), 0.0, 1.0)
            pressure_factors.extend(
                [
                    min(1.0, stress_barometer * 14.0),
                    min(1.0, defensive_rotation * 9.0),
                    move_stress,
                    sector_rotation,
                    macro_pressure,
                ]
            )
        else:
            move_stress = 0.0
            sector_rotation = 0.0
            macro_pressure = 0.0
        pressure_vector = torch.tensor(pressure_factors, dtype=torch.float32)
        pressure = _clamp(float(torch.mean(pressure_vector).item()), 0.0, 1.0)
        dominant_peer = None
        if peer_rows:
            dominant = max(peer_rows, key=lambda item: float(item.get("volume_1m", 0.0)))
            dominant_peer = str(dominant.get("asset") or "")

        report = {
            "pressure": round(pressure, 6),
            "triggered": bool(pressure >= 0.34),
            "provider": str(provider),
            "market_profile": str(self.market_profile),
            "anchor_asset": str(anchor_asset),
            "anchor_drop": round(anchor_drop, 6),
            "anchor_volatility": round(anchor_volatility, 6),
            "peer_volume_ratio": round(float(peer_volume_ratio), 6),
            "dominant_peer": dominant_peer,
            "move_stress": round(float(move_stress), 6),
            "sector_rotation": round(float(sector_rotation), 6),
            "macro_pressure": round(float(macro_pressure), 6),
            "btc_drop": round(anchor_drop, 6),
            "btc_volatility": round(anchor_volatility, 6),
            "alt_volume_ratio": round(float(peer_volume_ratio), 6),
            "dominant_alt": dominant_peer,
        }
        with self._lock:
            self.last_trauma_pressure = float(report["pressure"])

        now = time.perf_counter()
        if report["triggered"] and (now - self._last_trauma_ts) >= self.trauma_cooldown_seconds:
            episode = self.core.episodic_memory.record_trace(force=True, reason="market_trauma")
            trauma_event = {
                "recorded": bool(episode is not None),
                "episode_id": str((episode or {}).get("episode_id") or ""),
                "reason": "market_trauma",
                **report,
            }
            if episode is not None:
                episode["market_context"] = {
                    "provider": str(provider),
                    "pressure": round(pressure, 6),
                    "symbols": _make_tool_json_safe(structured),
                }
                trauma_event["recorded"] = True
            with self._lock:
                self.trauma_events += 1
                self._last_trauma_ts = now
                self.last_trauma_event = trauma_event
            return trauma_event
        return {
            "recorded": False,
            "reason": "market_trauma_not_triggered" if not report["triggered"] else "market_trauma_cooldown",
            **report,
        }

    def _consume_snapshot(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        provider = str(payload.get("provider") or "market")
        symbol_rows = payload.get("symbols", {}) if isinstance(payload, dict) else {}
        if not isinstance(symbol_rows, dict) or not symbol_rows:
            raise RuntimeError("market_snapshot_invalid")

        captured_at = time.time()
        structured: Dict[str, Any] = {}
        for raw_symbol, raw_payload in symbol_rows.items():
            if not isinstance(raw_payload, dict):
                continue
            symbol = str(raw_symbol).strip().upper()
            point = {
                "ts": captured_at,
                "price": float(raw_payload.get("price", 0.0)),
                "volume_total": float(raw_payload.get("volume_total", raw_payload.get("volume", 0.0))),
                "price_change_pct": float(raw_payload.get("price_change_pct", 0.0)),
                "bid_qty": float(raw_payload.get("bid_qty", 0.0)),
                "ask_qty": float(raw_payload.get("ask_qty", 0.0)),
            }
            features = self._compute_features(symbol, point)
            structured[str(features["asset"])] = features

        if not structured:
            raise RuntimeError("market_snapshot_empty")

        sensor_context: Dict[str, Any] = {}
        if str(self.market_profile) == "finance":
            sensor_context = self._collect_finance_sensor_context(structured, captured_at=captured_at)

        ingest_report = self.core.ingest_external_data(
            source_name=f"MarketAlchemy::{provider}",
            data_dict=structured,
        )
        trauma = self._trauma_report(structured, provider=provider, sensor_context=sensor_context)

        with self._lock:
            active_profile = str(self.market_profile)
            self.samples_ingested += 1
            self.last_provider = provider
            self.last_source_name = str(ingest_report.get("source_name") or f"MarketAlchemy::{provider}")
            self.last_signal_strength = float(ingest_report.get("signal_strength", 0.0))
            self.last_sample_at = captured_at
            self.last_error = None
            self.last_ingest_report = dict(ingest_report)
            self.last_market_snapshot = {
                "provider": provider,
                "market_profile": active_profile,
                "captured_at": round(captured_at, 6),
                "symbols": _make_tool_json_safe(structured),
                "sensor_context": _make_tool_json_safe(sensor_context),
                "macro_releases": _make_tool_json_safe(
                    list(dict(sensor_context.get("macro") or {}).get("upcoming_releases") or [])
                ),
            }
            self.last_finance_sensor_context = dict(sensor_context)

        report = {
            "success": bool(ingest_report.get("ingested", False)),
            "provider": provider,
            "market_profile": active_profile,
            "symbols": sorted(structured.keys()),
            "ingest_report": dict(ingest_report),
            "trauma": dict(trauma),
            "finance_sensors": _make_tool_json_safe(sensor_context),
        }
        self.last_report = dict(report)
        return report

    def _loop(self) -> None:
        with self._lock:
            self.last_loop_reason = "running"
        while not self._stop_event.is_set():
            mode = str(self.transport_mode or "auto")
            if mode in {"auto", "websocket"}:
                connected = self._run_websocket_session(symbols=list(self.symbols))
                if self._stop_event.is_set():
                    break
                if connected:
                    if mode == "websocket":
                        if self._stop_event.wait(max(0.2, self.ws_reconnect_backoff_seconds)):
                            break
                        continue
                elif mode == "websocket":
                    if self._stop_event.wait(max(0.2, self.ws_reconnect_backoff_seconds)):
                        break
                    continue

            self.poll_once(provider_order=self.provider_order, symbols=self.symbols)
            interval = max(0.05, float(self.poll_interval_seconds))
            if self._stop_event.wait(interval):
                break
        with self._lock:
            self.active = False
            if self.last_loop_reason == "running":
                self.last_loop_reason = "stopped"

    def start(
        self,
        *,
        poll_interval_seconds: Optional[float] = None,
        provider_order: Optional[Iterable[str]] = None,
        symbols: Optional[Iterable[str]] = None,
        transport: Optional[str] = None,
        market_profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.core._allow_external_feed():
            self.last_report = {
                "started": False,
                "active": False,
                "reason": "external_feed_blocked",
            }
            return dict(self.last_report)

        worker: Optional[threading.Thread] = None
        with self._lock:
            if poll_interval_seconds is not None:
                self.poll_interval_seconds = _clamp(float(poll_interval_seconds), 0.1, 60.0)
            self.market_profile = self._normalize_market_profile(
                market_profile,
                symbols=symbols,
                provider_order=provider_order,
            )
            self.provider_order = self._normalize_provider_order(provider_order, market_profile=self.market_profile)
            self.symbols = self._normalize_symbols(symbols, market_profile=self.market_profile)
            chosen_transport = str(transport or self.transport_mode or "auto").strip().lower()
            if chosen_transport not in {"auto", "websocket", "poll"}:
                chosen_transport = "auto"
            can_stream = str(self.market_profile) == "crypto" and "binance" in self.provider_order
            if chosen_transport in {"auto", "websocket"} and not can_stream:
                chosen_transport = "poll"
            self.transport_mode = chosen_transport
            self.last_error = None
            self._stream_symbol_cache = {}
            self._last_stream_flush_ts = 0.0

            alive = self._worker is not None and self._worker.is_alive()
            if not alive:
                self._stop_event = threading.Event()
                worker = threading.Thread(
                    target=self._loop,
                    name=f"atheria-market-alchemy-{self.core.core_id[-6:].lower()}",
                    daemon=True,
                )
                self._worker = worker
                self.active = True
                self.start_events += 1
                self.last_started_at = time.time()
            else:
                self.active = True

        if worker is not None:
            worker.start()

        self.last_report = {
            "started": worker is not None,
            "active": bool(self.active),
            "market_profile": str(self.market_profile),
            "transport": str(self.transport_mode),
            "provider_order": list(self.provider_order),
            "symbols": list(self.symbols),
            "poll_interval_seconds": round(float(self.poll_interval_seconds), 6),
        }
        return dict(self.last_report)

    def stop(self, *, join_timeout: float = 1.0) -> Dict[str, Any]:
        worker: Optional[threading.Thread]
        with self._lock:
            worker = self._worker
            was_active = bool(self.active or (worker is not None and worker.is_alive()))
            self._stop_event.set()
            self.active = False
            if was_active:
                self.stop_events += 1
            self.last_stopped_at = time.time()
            self.last_loop_reason = "stopping"

        if worker is not None and worker.is_alive() and worker is not threading.current_thread():
            worker.join(timeout=max(0.05, float(join_timeout)))

        with self._lock:
            if self._worker is worker and (worker is None or not worker.is_alive()):
                self._worker = None
            still_running = worker is not None and worker.is_alive()
            if not still_running:
                self.last_loop_reason = "stopped"
                self._stream_symbol_cache = {}
                self._last_stream_flush_ts = 0.0

        self.last_report = {
            "stopped": True,
            "active": bool(still_running),
            "market_profile": str(self.market_profile),
            "transport": str(self.transport_mode),
            "samples_ingested": int(self.samples_ingested),
            "trauma_events": int(self.trauma_events),
        }
        return dict(self.last_report)

    def poll_once(
        self,
        *,
        sample_override: Any = None,
        provider_order: Optional[Iterable[str]] = None,
        symbols: Optional[Iterable[str]] = None,
        market_profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.core._allow_external_feed():
            self.last_report = {
                "success": False,
                "reason": "external_feed_blocked",
            }
            return dict(self.last_report)

        try:
            if sample_override is not None:
                payload = self._normalize_snapshot_override(sample_override)
                effective_profile = self._normalize_market_profile(
                    market_profile,
                    symbols=list((payload.get("symbols") or {}).keys()),
                    provider_order=[payload.get("provider")],
                )
                selected_symbols = self._normalize_symbols(
                    list((payload.get("symbols") or {}).keys()),
                    market_profile=effective_profile,
                )
                selected_providers = self._normalize_provider_order(
                    [payload.get("provider")],
                    market_profile=effective_profile,
                )
            else:
                effective_profile = self._normalize_market_profile(
                    market_profile,
                    symbols=symbols,
                    provider_order=provider_order,
                )
                selected_symbols = self._normalize_symbols(symbols, market_profile=effective_profile)
                selected_providers = self._normalize_provider_order(provider_order, market_profile=effective_profile)
                payload = self._fetch_market_snapshot(
                    provider_order=selected_providers,
                    symbols=selected_symbols,
                )
            with self._lock:
                self.market_profile = str(effective_profile)
                self.symbols = list(selected_symbols)
                self.provider_order = list(selected_providers)
                self.last_transport = "poll"
            report = self._consume_snapshot(payload)
            self.last_report = dict(report)
            return dict(report)
        except Exception as exc:
            error = f"{type(exc).__name__}:{exc}"
            with self._lock:
                self.fetch_failures += 1
                self.last_error = error
            self.last_report = {
                "success": False,
                "reason": "market_ingest_failed",
                "error": error,
            }
            return dict(self.last_report)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            returns: Dict[str, list[float]] = {}
            volume_flux: Dict[str, list[float]] = {}
            for symbol, series in self._series.items():
                prices = [float(item.get("price", 0.0)) for item in series if float(item.get("price", 0.0)) > 0.0]
                if len(prices) >= 2:
                    returns[self._asset_label(symbol)] = [
                        round((right - left) / max(abs(left), 1e-6), 6)
                        for left, right in zip(prices[-7:-1], prices[-6:])
                    ]
                volumes = [float(item.get("volume_total", 0.0)) for item in series]
                if len(volumes) >= 2:
                    volume_flux[self._asset_label(symbol)] = [
                        round(max(0.0, right - left), 6)
                        for left, right in zip(volumes[-7:-1], volumes[-6:])
                    ]
            return {
                "active": bool(self.active and self._worker is not None and self._worker.is_alive()),
                "market_profile": str(self.market_profile),
                "transport": str(self.transport_mode),
                "last_transport": self.last_transport,
                "provider_order": list(self.provider_order),
                "symbols": list(self.symbols),
                "poll_interval_seconds": round(float(self.poll_interval_seconds), 6),
                "start_events": int(self.start_events),
                "stop_events": int(self.stop_events),
                "samples_ingested": int(self.samples_ingested),
                "fetch_failures": int(self.fetch_failures),
                "trauma_events": int(self.trauma_events),
                "ws_sessions": int(self.ws_sessions),
                "ws_messages": int(self.ws_messages),
                "ws_connect_failures": int(self.ws_connect_failures),
                "last_provider": self.last_provider,
                "last_source_name": self.last_source_name,
                "last_signal_strength": round(float(self.last_signal_strength), 6),
                "trauma_pressure": round(float(self.last_trauma_pressure), 6),
                "last_sample_at": None if self.last_sample_at <= 0.0 else round(float(self.last_sample_at), 6),
                "last_ws_message_at": None if self.last_ws_message_at <= 0.0 else round(float(self.last_ws_message_at), 6),
                "last_ws_connect_at": None if self.last_ws_connect_at <= 0.0 else round(float(self.last_ws_connect_at), 6),
                "last_started_at": None if self.last_started_at <= 0.0 else round(float(self.last_started_at), 6),
                "last_stopped_at": None if self.last_stopped_at <= 0.0 else round(float(self.last_stopped_at), 6),
                "last_error": self.last_error,
                "last_loop_reason": self.last_loop_reason,
                "last_ingest_report": _make_tool_json_safe(self.last_ingest_report),
                "last_market_snapshot": _make_tool_json_safe(self.last_market_snapshot),
                "last_trauma_event": _make_tool_json_safe(self.last_trauma_event),
                "finance_sensor_context": _make_tool_json_safe(self.last_finance_sensor_context),
                "recent_returns": returns,
                "recent_volume_flux": volume_flux,
            }


class LineageAuditor:
    """
    Reads child safety journals and recommends lineage profiles from historical integrity.
    """

    def __init__(self, core: "AtheriaCore") -> None:
        self.core = core
        self.lineage_root = Path("DEMO/lineage")
        self.scans = 0
        self.last_scanned_files = 0
        self.last_integrity_score = 0.0
        self.last_recommended_profile: Optional[str] = None
        self.last_scan_signature: Optional[str] = None
        self.last_report: Dict[str, Any] = {}

    def _load_entries(self, path: Path) -> list[Dict[str, Any]]:
        entries: list[Dict[str, Any]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                raw = line.strip()
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    entries.append(payload)
        except Exception:
            return []
        return entries

    def _metrics_for_file(self, path: Path, entries: list[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not entries:
            return None
        accepted_ratio = sum(1 for entry in entries if bool(entry.get("accepted", False))) / len(entries)
        invariant_ratio = sum(1 for entry in entries if bool(entry.get("invariant_ok", False))) / len(entries)
        persisted_ratio = sum(1 for entry in entries if bool(entry.get("persisted", False))) / len(entries)
        previous_signature = "GENESIS"
        chain_ok = 0
        for entry in entries:
            current_previous = str(entry.get("journal_previous") or "GENESIS")
            current_signature = str(entry.get("journal_signature") or "")
            if current_previous == previous_signature and len(current_signature) == 64:
                chain_ok += 1
            if current_signature:
                previous_signature = current_signature
        chain_ratio = chain_ok / len(entries)
        integrity_score = _clamp(
            0.34 * accepted_ratio + 0.28 * invariant_ratio + 0.2 * persisted_ratio + 0.18 * chain_ratio,
            0.0,
            1.0,
        )
        return {
            "child": path.parent.name,
            "path": str(path),
            "entries": len(entries),
            "accepted_ratio": round(accepted_ratio, 6),
            "invariant_ratio": round(invariant_ratio, 6),
            "persisted_ratio": round(persisted_ratio, 6),
            "chain_ratio": round(chain_ratio, 6),
            "integrity_score": round(integrity_score, 6),
        }

    def _profile_scores(
        self,
        *,
        integrity_score: float,
        invariant_ratio: float,
        persisted_ratio: float,
        chain_ratio: float,
        default_profile: str,
    ) -> Dict[str, float]:
        if integrity_score <= 0.0 and invariant_ratio <= 0.0 and persisted_ratio <= 0.0 and chain_ratio <= 0.0:
            scores = {
                "survival": 0.34,
                "diagnostic": 0.28,
                "stress-test": 0.22,
            }
            if default_profile in scores:
                scores[default_profile] = max(scores[default_profile], 0.72)
            return {key: round(value, 6) for key, value in scores.items()}

        feature_vec = torch.tensor(
            [integrity_score, invariant_ratio, persisted_ratio, chain_ratio],
            dtype=torch.float32,
        )
        stress_weights = torch.tensor([0.46, 0.22, 0.16, 0.16], dtype=torch.float32)
        stress_score = _clamp(float(torch.dot(feature_vec, stress_weights)), 0.0, 1.0)
        center = torch.tensor([0.56, 0.62, 0.58, 0.6], dtype=torch.float32)
        diagnostic_score = _clamp(
            0.28 + 0.52 * (1.0 - float(torch.mean(torch.abs(feature_vec - center)).item())),
            0.0,
            1.0,
        )
        survival_score = _clamp(0.22 + 0.66 * (1.0 - integrity_score) + 0.12 * (1.0 - chain_ratio), 0.0, 1.0)
        return {
            "survival": round(survival_score, 6),
            "diagnostic": round(diagnostic_score, 6),
            "stress-test": round(stress_score, 6),
        }

    def scan_lineage(
        self,
        *,
        lineage_root: Optional[str] = None,
        default_profile: str = "survival",
    ) -> Dict[str, Any]:
        root = Path(lineage_root) if lineage_root else self.lineage_root
        child_reports: list[Dict[str, Any]] = []
        for path in sorted(root.rglob("*_safety_audit.jsonl")) if root.exists() else []:
            metrics = self._metrics_for_file(path, self._load_entries(path))
            if metrics is not None:
                child_reports.append(metrics)

        if child_reports:
            integrity_score = sum(float(item["integrity_score"]) for item in child_reports) / len(child_reports)
            invariant_ratio = sum(float(item["invariant_ratio"]) for item in child_reports) / len(child_reports)
            persisted_ratio = sum(float(item["persisted_ratio"]) for item in child_reports) / len(child_reports)
            chain_ratio = sum(float(item["chain_ratio"]) for item in child_reports) / len(child_reports)
            reason = "historical_integrity"
        else:
            integrity_score = 0.0
            invariant_ratio = 0.0
            persisted_ratio = 0.0
            chain_ratio = 0.0
            reason = "no_lineage_history"

        profile_scores = self._profile_scores(
            integrity_score=integrity_score,
            invariant_ratio=invariant_ratio,
            persisted_ratio=persisted_ratio,
            chain_ratio=chain_ratio,
            default_profile=default_profile,
        )
        recommended_profile = max(
            sorted(profile_scores.keys()),
            key=lambda key: (profile_scores[key], key),
        )
        signature_seed = _stable_json_dumps(
            {
                "root": str(root),
                "children": child_reports,
                "profile_scores": profile_scores,
                "recommended_profile": recommended_profile,
            }
        )
        scan_signature = hashlib.sha1(signature_seed.encode("utf-8")).hexdigest()[:12]
        self.scans += 1
        self.last_scanned_files = len(child_reports)
        self.last_integrity_score = integrity_score
        self.last_recommended_profile = recommended_profile
        self.last_scan_signature = scan_signature
        self.last_report = {
            "success": True,
            "lineage_root": str(root),
            "scanned_files": len(child_reports),
            "integrity_score": round(integrity_score, 6),
            "profile_scores": dict(profile_scores),
            "recommended_profile": recommended_profile,
            "reason": reason,
            "scan_signature": scan_signature,
            "children": child_reports,
        }
        return dict(self.last_report)


class InterCoreResonanceAuditor:
    """
    Scans daemon journals across domains and hardens lagged market invariants.
    """

    def __init__(self, core: "AtheriaCore") -> None:
        self.core = core
        self.default_primary_report_dir = Path("daemon_runtime")
        self.scans = 0
        self.learned_invariants = 0
        self.last_matches = 0
        self.last_confidence = 0.0
        self.last_effect_size = 0.0
        self.last_scan_signature: Optional[str] = None
        self.last_invariant_path: Optional[str] = None
        self.last_invariant: Dict[str, Any] = {}
        self.last_report: Dict[str, Any] = {}
        self._known_invariants: Dict[str, Dict[str, Any]] = {}

    def _report_file(self, value: Optional[str], *, default: Optional[Path] = None) -> Path:
        base = Path(str(value)) if value else (default or self.default_primary_report_dir)
        return base if base.suffix.lower() == ".jsonl" else base / "atheria_daemon_audit.jsonl"

    def _load_entries(self, path: Path) -> list[Dict[str, Any]]:
        entries: list[Dict[str, Any]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                raw = line.strip()
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    entries.append(payload)
        except Exception:
            return []
        return entries

    def _market_profile(self, entry: Dict[str, Any]) -> str:
        market = dict(entry.get("market") or {})
        snapshot = dict(market.get("last_market_snapshot") or {})
        trauma = dict(market.get("last_trauma_event") or {})
        return (
            str(market.get("market_profile") or "")
            or str(snapshot.get("market_profile") or "")
            or str(trauma.get("market_profile") or "")
        ).strip().lower()

    def _symbol_rows(self, entry: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        market = dict(entry.get("market") or {})
        snapshot = dict(market.get("last_market_snapshot") or {})
        raw = snapshot.get("symbols", {})
        if not isinstance(raw, dict):
            return {}
        return {
            str(key).strip().upper(): dict(value)
            for key, value in raw.items()
            if isinstance(value, dict)
        }

    def _asset_row(self, entry: Dict[str, Any], asset: str) -> Dict[str, Any]:
        return dict(self._symbol_rows(entry).get(str(asset).strip().upper()) or {})

    def _anchor_asset(self, entry: Dict[str, Any]) -> str:
        market = dict(entry.get("market") or {})
        trauma = dict(market.get("last_trauma_event") or {})
        anchor = str(trauma.get("anchor_asset") or "").strip().upper()
        if anchor:
            return anchor
        symbols = self._symbol_rows(entry)
        for candidate in ("SP500", "DAX", "NASDAQ", "DOW", "RUSSELL", "SOFTWARE", "BTC", "ETH", "BNB", "SOL"):
            if candidate in symbols:
                return candidate
        if symbols:
            return sorted(symbols.keys())[0]
        return "BTC"

    def _asset_coherence(self, entry: Dict[str, Any], asset: str) -> Optional[float]:
        row = self._asset_row(entry, asset)
        if not row:
            return None
        recent_return = abs(_safe_float(row.get("recent_return"), _safe_float(row.get("price_change_pct"), 0.0) / 100.0))
        volatility = abs(_safe_float(row.get("volatility"), 0.0))
        imbalance = abs(_safe_float(row.get("orderbook_imbalance"), 0.0))
        stability = 1.0 - min(1.0, recent_return * 16.0 + volatility * 18.0)
        balance = 1.0 - min(1.0, imbalance * 0.85)
        coherence = _clamp(0.64 * stability + 0.36 * balance, 0.0, 1.0)
        return round(float(coherence), 6)

    def _trigger_signal(
        self,
        entry: Dict[str, Any],
        *,
        foreign_domain: str,
        trigger_asset: Optional[str],
        trigger_threshold: Optional[float],
    ) -> Dict[str, Any]:
        market = dict(entry.get("market") or {})
        symbols = self._symbol_rows(entry)
        chosen_asset = str(trigger_asset or "").strip().upper()
        if not chosen_asset:
            if str(foreign_domain).strip().lower() == "finance":
                if "VIX" in symbols:
                    chosen_asset = "VIX"
                elif "MOVE" in symbols:
                    chosen_asset = "MOVE"
            if not chosen_asset:
                chosen_asset = self._anchor_asset(entry)

        metric = "price"
        row = dict(symbols.get(chosen_asset) or {})
        observed = 0.0
        if chosen_asset == "VIX":
            observed = _safe_float(row.get("price"), 0.0)
            threshold = float(trigger_threshold) if trigger_threshold is not None else 20.0
            triggered = observed >= threshold
        elif chosen_asset == "MOVE":
            observed = _safe_float(row.get("price"), 0.0)
            threshold = float(trigger_threshold) if trigger_threshold is not None else 120.0
            triggered = observed >= threshold
        else:
            metric = "trauma_pressure"
            observed = _safe_float(market.get("trauma_pressure"), 0.0)
            threshold = float(trigger_threshold) if trigger_threshold is not None else 0.48
            triggered = observed >= threshold

        return {
            "asset": chosen_asset or "MARKET",
            "metric": metric,
            "observed": round(float(observed), 6),
            "threshold": round(float(threshold), 6),
            "triggered": bool(triggered),
        }

    def _persist_invariant(self, invariant: Dict[str, Any], *, scan_signature: str) -> Dict[str, Any]:
        path = self.core.safety.audit_output_root / f"{self.core.core_id.lower()}_inter_core_resonance.jsonl"
        previous = "GENESIS"
        try:
            if path.exists():
                for raw in reversed(path.read_text(encoding="utf-8").splitlines()):
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    previous = str(payload.get("signature") or "GENESIS")
                    break
        except Exception:
            previous = "GENESIS"

        record = {
            "timestamp": round(time.time(), 6),
            "observer_core_id": self.core.core_id,
            "scan_signature": str(scan_signature),
            "previous": previous,
            "invariant": _make_tool_json_safe(invariant),
        }
        signature_seed = _stable_json_dumps(
            {
                "previous": previous,
                "scan_signature": scan_signature,
                "invariant": record["invariant"],
            }
        )
        signature = hashlib.sha1(signature_seed.encode("utf-8")).hexdigest()[:12]
        record["signature"] = signature

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
                handle.write("\n")
        except Exception as exc:
            return {
                "persisted": False,
                "path": str(path),
                "error": f"{type(exc).__name__}:{exc}",
            }

        invariant_id = str(invariant.get("invariant_id") or signature)
        is_new = invariant_id not in self._known_invariants
        self._known_invariants[invariant_id] = dict(invariant)
        if is_new:
            self.learned_invariants += 1
        self.last_invariant_path = str(path)
        self.last_invariant = dict(invariant)
        return {
            "persisted": True,
            "path": str(path),
            "signature": signature,
            "new_invariant": bool(is_new),
        }

    def scan_resonance(
        self,
        *,
        primary_report_dir: Optional[str] = None,
        foreign_report_dir: Optional[str] = None,
        primary_domain: str = "crypto",
        foreign_domain: str = "finance",
        observer_label: Optional[str] = None,
        lag_minutes: float = 120.0,
        trigger_asset: Optional[str] = None,
        trigger_threshold: Optional[float] = None,
        target_asset: str = "BTC",
        min_matches: int = 2,
        min_effect_size: float = 0.05,
    ) -> Dict[str, Any]:
        if not foreign_report_dir:
            self.last_report = {
                "success": False,
                "reason": "foreign_report_dir_required",
            }
            return dict(self.last_report)

        primary_file = self._report_file(primary_report_dir, default=self.default_primary_report_dir)
        foreign_file = self._report_file(foreign_report_dir)
        primary_domain_name = str(primary_domain or "crypto").strip().lower()
        foreign_domain_name = str(foreign_domain or "finance").strip().lower()
        lag_seconds = max(60.0, float(lag_minutes) * 60.0)
        min_matches = max(1, int(min_matches))
        min_effect_size = _clamp(float(min_effect_size), 0.0, 1.0)
        target_asset_name = str(target_asset or "BTC").strip().upper() or "BTC"

        if not primary_file.exists():
            self.last_report = {
                "success": False,
                "reason": "primary_report_missing",
                "primary_report": str(primary_file),
            }
            return dict(self.last_report)
        if not foreign_file.exists():
            self.last_report = {
                "success": False,
                "reason": "foreign_report_missing",
                "foreign_report": str(foreign_file),
            }
            return dict(self.last_report)

        raw_primary = self._load_entries(primary_file)
        raw_foreign = self._load_entries(foreign_file)

        primary_samples: list[Dict[str, Any]] = []
        for entry in raw_primary:
            timestamp = _safe_float(entry.get("timestamp"), 0.0)
            profile = self._market_profile(entry)
            if timestamp <= 0.0:
                continue
            if profile and profile != primary_domain_name:
                continue
            coherence = self._asset_coherence(entry, target_asset_name)
            if coherence is None:
                continue
            primary_samples.append(
                {
                    "timestamp": timestamp,
                    "coherence": float(coherence),
                    "entry": entry,
                }
            )
        primary_samples.sort(key=lambda item: float(item["timestamp"]))

        trigger_events: list[Dict[str, Any]] = []
        for entry in raw_foreign:
            timestamp = _safe_float(entry.get("timestamp"), 0.0)
            profile = self._market_profile(entry)
            if timestamp <= 0.0:
                continue
            if profile and profile != foreign_domain_name:
                continue
            trigger = self._trigger_signal(
                entry,
                foreign_domain=foreign_domain_name,
                trigger_asset=trigger_asset,
                trigger_threshold=trigger_threshold,
            )
            if not trigger.get("triggered", False):
                continue
            trigger_events.append(
                {
                    "timestamp": timestamp,
                    "entry": entry,
                    "trigger": trigger,
                }
            )
        trigger_events.sort(key=lambda item: float(item["timestamp"]))

        matches: list[Dict[str, Any]] = []
        for event in trigger_events:
            baseline: Optional[Dict[str, Any]] = None
            for sample in primary_samples:
                if float(sample["timestamp"]) <= float(event["timestamp"]):
                    baseline = sample
                    continue
                break
            if baseline is None:
                continue

            follow: Optional[Dict[str, Any]] = None
            target_ts = float(event["timestamp"]) + lag_seconds
            for sample in primary_samples:
                if float(sample["timestamp"]) >= target_ts:
                    follow = sample
                    break
            if follow is None:
                continue

            delta = round(float(baseline["coherence"]) - float(follow["coherence"]), 6)
            matches.append(
                {
                    "triggered_at": round(float(event["timestamp"]), 6),
                    "trigger_asset": str(event["trigger"]["asset"]),
                    "trigger_metric": str(event["trigger"]["metric"]),
                    "trigger_value": round(float(event["trigger"]["observed"]), 6),
                    "trigger_threshold": round(float(event["trigger"]["threshold"]), 6),
                    "baseline_at": round(float(baseline["timestamp"]), 6),
                    "baseline_coherence": round(float(baseline["coherence"]), 6),
                    "observed_at": round(float(follow["timestamp"]), 6),
                    "observed_coherence": round(float(follow["coherence"]), 6),
                    "delta": delta,
                }
            )

        reason = "ok"
        invariant_recorded = False
        invariant: Optional[Dict[str, Any]] = None
        persist_report: Dict[str, Any] = {}

        if not primary_samples:
            reason = "no_primary_target_samples"
        elif not trigger_events:
            reason = "no_trigger_events"
        elif not matches:
            reason = "no_matched_windows"

        mean_delta = (
            sum(float(item["delta"]) for item in matches) / len(matches)
            if matches
            else 0.0
        )
        mean_baseline = (
            sum(float(item["baseline_coherence"]) for item in matches) / len(matches)
            if matches
            else 0.0
        )
        mean_observed = (
            sum(float(item["observed_coherence"]) for item in matches) / len(matches)
            if matches
            else 0.0
        )
        consistency = (
            sum(1 for item in matches if float(item["delta"]) >= min_effect_size) / len(matches)
            if matches
            else 0.0
        )
        confidence = _clamp(
            0.28 + mean_delta * 2.6 + consistency * 0.28 + min(0.18, len(matches) * 0.05),
            0.0,
            0.98,
        )

        trigger_summary = trigger_events[0]["trigger"] if trigger_events else {
            "asset": str(trigger_asset or "MARKET"),
            "metric": "price",
            "threshold": round(float(trigger_threshold), 6) if trigger_threshold is not None else 0.0,
            "observed": 0.0,
        }
        scan_signature = hashlib.sha1(
            _stable_json_dumps(
                {
                    "primary": str(primary_file),
                    "foreign": str(foreign_file),
                    "primary_domain": primary_domain_name,
                    "foreign_domain": foreign_domain_name,
                    "lag_seconds": lag_seconds,
                    "target_asset": target_asset_name,
                    "trigger": trigger_summary,
                    "matches": matches,
                }
            ).encode("utf-8")
        ).hexdigest()[:12]

        if matches and len(matches) >= min_matches and mean_delta >= min_effect_size and consistency >= 0.5:
            threshold = float(trigger_summary.get("threshold", 0.0))
            threshold_text = f"{threshold:.2f}".rstrip("0").rstrip(".")
            lag_text = f"{round(lag_seconds / 60.0):.0f}"
            statement = (
                f"Wenn {str(trigger_summary.get('asset') or 'MARKET')} >= {threshold_text}, "
                f"sinkt die {target_asset_name}-Kohaerenz nach {lag_text} Minuten."
            )
            invariant = {
                "invariant_id": f"ICR::{hashlib.sha1((scan_signature + statement).encode('utf-8')).hexdigest()[:10].upper()}",
                "observer_core_id": self.core.core_id,
                "observer_label": str(observer_label or self.core.core_id),
                "source_domain": foreign_domain_name,
                "target_domain": primary_domain_name,
                "trigger_asset": str(trigger_summary.get("asset") or "MARKET"),
                "trigger_metric": str(trigger_summary.get("metric") or "price"),
                "trigger_threshold": round(float(threshold), 6),
                "target_asset": target_asset_name,
                "target_metric": "coherence",
                "lag_minutes": round(lag_seconds / 60.0, 6),
                "effect_direction": "decrease",
                "mean_baseline_coherence": round(float(mean_baseline), 6),
                "mean_observed_coherence": round(float(mean_observed), 6),
                "mean_effect_size": round(float(mean_delta), 6),
                "consistency": round(float(consistency), 6),
                "confidence": round(float(confidence), 6),
                "samples": len(matches),
                "relationship": "liquidity_outflow_proxy",
                "statement": statement,
                "scan_signature": scan_signature,
            }
            persist_report = self._persist_invariant(invariant, scan_signature=scan_signature)
            invariant_recorded = bool(persist_report.get("persisted", False))
            if not invariant_recorded:
                reason = "invariant_persist_failed"
        elif reason == "ok":
            reason = "threshold_not_met"

        self.scans += 1
        self.last_matches = len(matches)
        self.last_confidence = float(confidence)
        self.last_effect_size = float(mean_delta)
        self.last_scan_signature = scan_signature
        if invariant is not None and invariant_recorded:
            self.last_invariant = dict(invariant)

        self.last_report = {
            "success": True,
            "observer_label": str(observer_label or self.core.core_id),
            "primary_report": str(primary_file),
            "foreign_report": str(foreign_file),
            "primary_domain": primary_domain_name,
            "foreign_domain": foreign_domain_name,
            "trigger_events": len(trigger_events),
            "matched_windows": len(matches),
            "lag_minutes": round(lag_seconds / 60.0, 6),
            "target_asset": target_asset_name,
            "confidence": round(float(confidence), 6),
            "effect_size": round(float(mean_delta), 6),
            "consistency": round(float(consistency), 6),
            "scan_signature": scan_signature,
            "reason": reason,
            "invariant_recorded": bool(invariant_recorded),
            "invariant": _make_tool_json_safe(invariant) if invariant is not None else None,
            "persist_report": _make_tool_json_safe(persist_report),
            "matches": _make_tool_json_safe(matches[:8]),
        }
        return dict(self.last_report)

    def snapshot(self) -> Dict[str, Any]:
        invariant_rows = list(self._known_invariants.values())
        invariant_rows.sort(
            key=lambda item: (
                float(item.get("confidence", 0.0)),
                float(item.get("mean_effect_size", 0.0)),
            ),
            reverse=True,
        )
        return {
            "scans": int(self.scans),
            "learned_invariants": int(self.learned_invariants),
            "last_matches": int(self.last_matches),
            "last_confidence": round(float(self.last_confidence), 6),
            "last_effect_size": round(float(self.last_effect_size), 6),
            "last_scan_signature": self.last_scan_signature,
            "last_invariant_path": self.last_invariant_path,
            "last_invariant": _make_tool_json_safe(self.last_invariant),
            "last_report": _make_tool_json_safe(self.last_report),
            "invariants": _make_tool_json_safe(invariant_rows[:4]),
        }


@dataclass
class NeuroModulators:
    dopamine: float = 1.0
    adrenaline: float = 0.0
    serotonin: float = 0.0

    def reward(self, connection: AtherConnection, magnitude: float = 1.0) -> None:
        boost = 0.015 * self.dopamine * max(0.1, magnitude)
        connection.weight = min(1.5, connection.weight + boost)

    def force_plasma(self, phase_controller: "PhaseController", intensity: float = 1.0) -> None:
        self.adrenaline += intensity
        phase_controller.inject_temperature(20.0 * intensity)

    def stabilize(self, phase_controller: "PhaseController", intensity: float = 1.0) -> None:
        self.serotonin += intensity
        phase_controller.inject_temperature(-18.0 * intensity)

    def decay(self) -> None:
        self.adrenaline *= 0.9
        self.serotonin *= 0.92
        self.dopamine = max(0.4, min(2.0, self.dopamine * 0.998))


GLOBAL_NEUROTRANSMITTERS = NeuroModulators()


class OrigamiRouter:
    def resonance(self, cell_a: AtherCell, cell_b: AtherCell) -> float:
        dot = torch.dot(cell_a.fold_signature, cell_b.fold_signature)
        denom = (torch.norm(cell_a.fold_signature, p=2) * torch.norm(cell_b.fold_signature, p=2)) + 1e-8
        return max(0.0, min(1.0, float(dot / denom)))

    def discover_folded_paths(self, core: "AtheriaCore", min_resonance: float = 0.84, max_new_edges: int = 2) -> int:
        created = 0
        cells = tuple(core.cells.values())
        for src in cells:
            candidates = [
                (self.resonance(src, target), target)
                for target in cells
                if target.label != src.label and target.label not in src.connections
            ]
            if not candidates:
                continue
            candidates.sort(key=lambda item: item[0], reverse=True)
            for resonance, target in candidates[:max_new_edges]:
                if resonance < min_resonance:
                    continue
                src.add_connection(target, weight=0.22 + 0.62 * resonance)
                created += 1
        return created


class MorphicBuffer:
    """
    Stores the most stable ~5% of field states and offers resonance guidance.
    """

    def __init__(self, dims: int, max_states: int = 36) -> None:
        self.dims = dims
        self.max_states = max_states
        self._observed = 0
        self._states: list[Dict[str, object]] = []
        self.last_resonance_index = 0.0

    def observe(self, pattern: torch.Tensor, stability: float) -> None:
        self._observed += 1
        self._states.append(
            {
                "pattern": pattern.detach().clone(),
                "stability": max(0.0, min(1.0, float(stability))),
            }
        )
        keep = max(1, min(self.max_states, math.ceil(self._observed * 0.05)))
        self._states.sort(key=lambda item: float(item["stability"]), reverse=True)
        self._states = self._states[:keep]

    def resonate(self, current_pattern: torch.Tensor, uncertainty: float) -> tuple[torch.Tensor, float]:
        if not self._states or uncertainty < 0.28:
            self.last_resonance_index *= 0.9
            return current_pattern.detach().clone(), 0.0

        current = current_pattern / (torch.norm(current_pattern, p=2) + 1e-8)
        ranked: list[tuple[float, torch.Tensor]] = []
        for item in self._states:
            pattern = item["pattern"]
            stability = float(item["stability"])
            pnorm = pattern / (torch.norm(pattern, p=2) + 1e-8)
            similarity = max(0.0, float(torch.dot(current, pnorm)))
            score = 0.62 * stability + 0.38 * similarity
            ranked.append((score, pnorm))

        ranked.sort(key=lambda entry: entry[0], reverse=True)
        top = ranked[: min(3, len(ranked))]
        if not top:
            self.last_resonance_index *= 0.9
            return current_pattern.detach().clone(), 0.0

        total = sum(score for score, _ in top) + 1e-8
        guide = torch.zeros_like(current_pattern)
        for score, pattern in top:
            guide = guide + pattern * (score / total)
        guide = guide / (torch.norm(guide, p=2) + 1e-8)

        mix = max(0.06, min(0.34, 0.08 + uncertainty * 0.26))
        blended = (1.0 - mix) * current + mix * guide
        blended = blended / (torch.norm(blended, p=2) + 1e-8)
        resonance_index = max(0.0, min(1.0, (sum(score for score, _ in top) / len(top)) * uncertainty))
        self.last_resonance_index = 0.84 * self.last_resonance_index + 0.16 * resonance_index
        return blended, resonance_index

    @property
    def size(self) -> int:
        return len(self._states)

    def export(self, limit: int = 8) -> list[Dict[str, object]]:
        out: list[Dict[str, object]] = []
        for item in self._states[: max(1, limit)]:
            raw_pattern = item["pattern"]
            if isinstance(raw_pattern, torch.Tensor):
                pattern_list = raw_pattern.detach().float().tolist()
            else:
                pattern_list = torch.tensor(raw_pattern, dtype=torch.float32).tolist()
            out.append(
                {
                    "stability": round(float(item["stability"]), 6),
                    "pattern": pattern_list,
                }
            )
        return out


class HolographicField:
    def __init__(self, dims: int = 12) -> None:
        self.pattern = torch.zeros(dims, dtype=torch.float32)
        self.energy = 0.0
        self.pattern_history: Deque[torch.Tensor] = deque(maxlen=24)
        self.last_future_projection = torch.zeros(dims, dtype=torch.float32)
        self.last_projection_uncertainty = 0.0
        self.morphic_buffer = MorphicBuffer(dims=dims)
        self.last_morphic_resonance_index = 0.0
        self.last_uncertainty = 0.0

    def imprint(self, cells: Iterable[AtherCell]) -> None:
        cells_list = list(cells)
        if not cells_list:
            return
        previous_pattern = self.pattern.detach().clone()
        vector = torch.zeros_like(self.pattern)
        mass = 0.0
        for cell in cells_list:
            vector = vector + cell.fold_signature * cell.activation_value
            mass += cell.activation_value
        if mass > 0.0:
            vector = vector / mass
        self.pattern = 0.9 * self.pattern + 0.1 * vector
        self.energy = float(torch.norm(self.pattern, p=2))
        self.pattern_history.append(self.pattern.detach().clone())
        drift = float(torch.norm(self.pattern - previous_pattern, p=2))
        stability = (1.0 / (1.0 + drift)) * (0.58 + 0.42 * min(1.0, self.energy))
        self.morphic_buffer.observe(self.pattern, stability=stability)

    def future_projection(self, horizon: int = 2, damping: float = 0.75) -> torch.Tensor:
        if len(self.pattern_history) < 2:
            self.last_future_projection = self.pattern.detach().clone()
            self.last_projection_uncertainty = 0.0
            return self.last_future_projection

        current = self.pattern_history[-1]
        previous = self.pattern_history[-2]
        trend = current - previous

        if len(self.pattern_history) >= 3:
            older = self.pattern_history[-3]
            trend = 0.7 * trend + 0.3 * (previous - older)

        projected = current + trend * float(horizon) * damping
        projected = torch.tanh(projected)
        self.last_future_projection = projected
        current_norm = current / (torch.norm(current, p=2) + 1e-8)
        projected_norm = projected / (torch.norm(projected, p=2) + 1e-8)
        alignment = max(0.0, float(torch.dot(current_norm, projected_norm)))
        drift = float(torch.norm(projected - current, p=2))
        coherence = max(0.0, min(1.0, self.energy / 1.2))
        self.last_projection_uncertainty = _clamp(
            0.48 * math.tanh(drift)
            + 0.32 * (1.0 - alignment)
            + 0.2 * (1.0 - coherence),
            0.0,
            1.0,
        )
        return projected

    def morphic_resonance(self, uncertainty: float) -> tuple[torch.Tensor, float]:
        guide, index = self.morphic_buffer.resonate(self.pattern, uncertainty=uncertainty)
        self.last_morphic_resonance_index = index
        if index > 0.0:
            self.pattern = torch.tanh(0.93 * self.pattern + 0.07 * guide)
        return guide, index

    def estimate_activation(self, cell: AtherCell) -> float:
        if self.energy <= 1e-6:
            return cell.activation_value
        dot = torch.dot(self.pattern, cell.fold_signature)
        denom = (torch.norm(self.pattern, p=2) * torch.norm(cell.fold_signature, p=2)) + 1e-8
        resonance = max(0.0, float(dot / denom))
        estimate = min(1.0, resonance * min(1.0, self.energy))
        return estimate

    def reconstruct(self, cell: AtherCell) -> None:
        estimate = self.estimate_activation(cell)
        if estimate > cell.activation_value:
            cell.set_activation(0.65 * estimate + 0.35 * cell.activation_value)
        cell.refold()

    def reverse_inference(self, cells: Iterable[AtherCell], top_k: int = 6) -> list[Dict[str, float | str]]:
        """
        Dreaming mode:
        read the field pattern "backwards" and generate synthetic activation candidates.
        """
        cells_list = list(cells)
        if not cells_list:
            return []
        pattern = self.pattern / (torch.norm(self.pattern, p=2) + 1e-8)
        replay_scores: list[tuple[float, AtherCell]] = []
        for cell in cells_list:
            fold = cell.fold_signature / (torch.norm(cell.fold_signature, p=2) + 1e-8)
            resonance = max(0.0, float(torch.dot(pattern, fold)))
            underuse = min(1.0, float(cell.silent_epochs) / 14.0)
            fragility = 1.0 - max(0.0, min(1.0, cell.integrity_rate))
            replay_score = 0.55 * resonance + 0.25 * underuse + 0.2 * fragility
            replay_scores.append((replay_score, cell))

        replay_scores.sort(key=lambda item: item[0], reverse=True)
        result = [
            {"label": cell.label, "score": round(score, 6)}
            for score, cell in replay_scores[: max(1, min(top_k, len(replay_scores)))]
        ]
        return result

    def query_field(
        self,
        input_tensor: torch.Tensor,
        *,
        cells: Optional[Iterable[AtherCell]] = None,
        entanglement_registry: Optional[Dict[str, Set[str]]] = None,
        top_k: int = 5,
    ) -> Dict[str, object]:
        """
        Non-local field computation:
        The entire field acts as a standing wave; inference emerges from interference.
        """
        vector = input_tensor.detach().float().flatten()
        dims = int(self.pattern.numel())
        if vector.numel() < dims:
            vector = torch.nn.functional.pad(vector, (0, dims - vector.numel()))
        elif vector.numel() > dims:
            vector = vector[:dims]
        vector = vector / (torch.norm(vector, p=2) + 1e-8)

        pattern_norm = self.pattern / (torch.norm(self.pattern, p=2) + 1e-8)
        alignment = max(0.0, float(torch.dot(pattern_norm, vector)))
        coherence = max(0.0, min(1.0, self.energy / 1.2))
        uncertainty = max(0.0, min(1.0, 0.7 * (1.0 - alignment) + 0.3 * (1.0 - coherence)))
        self.last_uncertainty = uncertainty

        projected = self.future_projection(horizon=2, damping=0.78)
        projected_norm = projected / (torch.norm(projected, p=2) + 1e-8)
        morphic_guide, morphic_index = self.morphic_resonance(uncertainty=uncertainty)
        morphic_norm = morphic_guide / (torch.norm(morphic_guide, p=2) + 1e-8)

        standing_wave = (0.36 * pattern_norm + 0.22 * projected_norm + 0.24 * vector + 0.18 * morphic_norm)
        standing_wave = standing_wave / (torch.norm(standing_wave, p=2) + 1e-8)
        phase_interference = torch.cos((standing_wave + 1e-8) * (vector + 1e-8) * torch.pi)
        interference_tensor = torch.relu(
            0.54 * standing_wave * vector
            + 0.2 * projected_norm * vector
            + 0.14 * morphic_norm * vector
            + 0.12 * phase_interference
        )

        result: Dict[str, object] = {
            "interference_energy": round(float(torch.norm(interference_tensor, p=2)), 6),
            "future_projection": projected.tolist(),
            "anticipatory_shift": round(float(torch.norm(projected - self.pattern, p=2)), 6),
            "projection_uncertainty": round(self.last_projection_uncertainty, 6),
            "morphic_resonance_index": round(morphic_index, 6),
            "uncertainty": round(uncertainty, 6),
            "response_tensor": interference_tensor.tolist(),
            "top_matches": [],
            "future_top_matches": [],
        }

        if not cells:
            return result

        cells_list = list(cells)
        by_label = {cell.label: cell for cell in cells_list}
        scores: Dict[str, float] = {}
        future_scores: Dict[str, float] = {}

        for cell in cells_list:
            base_dot = torch.dot(interference_tensor, cell.fold_signature)
            denom = (torch.norm(interference_tensor, p=2) * torch.norm(cell.fold_signature, p=2)) + 1e-8
            resonance = max(0.0, float(base_dot / denom))
            future_dot = torch.dot(projected_norm, cell.fold_signature)
            future_denom = (torch.norm(projected_norm, p=2) * torch.norm(cell.fold_signature, p=2)) + 1e-8
            future_resonance = max(0.0, float(future_dot / future_denom))
            score = (0.62 * resonance + 0.38 * future_resonance) * (0.58 + 0.42 * cell.coherence)

            if entanglement_registry:
                partners = entanglement_registry.get(cell.label, set())
                if partners:
                    linked_scores = []
                    for partner_label in partners:
                        partner = by_label.get(partner_label)
                        if partner is None:
                            continue
                        partner_dot = torch.dot(interference_tensor, partner.fold_signature)
                        partner_den = (torch.norm(interference_tensor, p=2) * torch.norm(partner.fold_signature, p=2)) + 1e-8
                        linked_scores.append(max(0.0, float(partner_dot / partner_den)))
                    if linked_scores:
                        score = score * 0.82 + max(linked_scores) * 0.18

            scores[cell.label] = score
            future_scores[cell.label] = future_resonance * (0.6 + 0.4 * cell.coherence)

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[: max(1, top_k)]
        result["top_matches"] = [{"label": label, "score": round(score, 6)} for label, score in ranked]
        ranked_future = sorted(future_scores.items(), key=lambda item: item[1], reverse=True)[: max(1, top_k)]
        result["future_top_matches"] = [{"label": label, "score": round(score, 6)} for label, score in ranked_future]
        return result


class EntropicFoldingAlgorithm:
    """
    Entropic Folding equation:
    F (origami resonance) * Q (protein superposition coherence) * T (entropy-temperature normalization)
    """

    def __init__(self, phase_controller: "PhaseController", origami_router: OrigamiRouter) -> None:
        self.phase_controller = phase_controller
        self.origami_router = origami_router
        self.last_index = 1.0

    def fold_component(self, cell_a: AtherCell, cell_b: AtherCell) -> float:
        return self.origami_router.resonance(cell_a, cell_b)

    def quantum_component(self, cell_a: AtherCell, cell_b: AtherCell) -> float:
        qa = cell_a.coherence if cell_a.is_superposed else 0.62 + 0.28 * cell_a.enzyme_stability
        qb = cell_b.coherence if cell_b.is_superposed else 0.62 + 0.28 * cell_b.enzyme_stability
        return max(0.2, min(1.2, (qa + qb) * 0.5))

    def entropy_component(self) -> float:
        # Stable in liquid range, permissive in solid, volatile in plasma.
        temp = self.phase_controller.system_temperature
        normalized = 1.0 - min(1.0, abs(temp - 58.0) / 62.0)
        return max(0.25, min(1.0, normalized))

    def transfer_factor(self, cell_a: AtherCell, cell_b: AtherCell) -> float:
        f = self.fold_component(cell_a, cell_b)
        q = self.quantum_component(cell_a, cell_b)
        t = self.entropy_component()
        self.last_index = f * q * t
        return max(0.06, min(1.8, self.last_index))


class SymbolGroundingLayer:
    """
    Anchors stable morphic field states into reusable symbolic IDs.
    """

    def __init__(self, core: "AtheriaCore", interval_ticks: int = 6) -> None:
        self.core = core
        self.interval_ticks = interval_ticks
        self._tick = 0
        self._local_symbols: Dict[str, Dict[str, Any]] = {}
        self.anchor_events = 0
        self.shared_symbol_reuses = 0
        self.symbol_packets_exported = 0
        self.symbol_packets_received = 0
        self.last_symbol_id: Optional[str] = None
        self.last_symbol_signature: Optional[str] = None
        self.last_symbol_stability = 0.0
        self.last_symbol_shared_cores = 0
        self.last_symbol_labels: list[str] = []
        self.last_imported_symbol_id: Optional[str] = None

    def _candidate_cells(self) -> list[AtherCell]:
        cells = [
            cell
            for cell in self.core.cells.values()
            if not isinstance(cell, LibraryCell) and cell.activation_value > 0.04
        ]
        cells.sort(
            key=lambda cell: (
                cell.activation_value,
                cell.coherence,
                sum(conn.usage_count for conn in cell.connections.values()),
            ),
            reverse=True,
        )
        return cells[:4]

    def _field_token(self, vector: torch.Tensor) -> str:
        if vector.numel() == 0:
            return "EMPTY"
        k = min(4, int(vector.numel()))
        values, indices = torch.topk(torch.abs(vector), k=k)
        tokens = []
        for raw_idx, raw_val in zip(indices.tolist(), values.tolist()):
            sign = "P" if float(vector[raw_idx]) >= 0.0 else "N"
            bucket = int(min(9, max(0, round(float(raw_val) * 9))))
            tokens.append(f"{raw_idx}{sign}{bucket}")
        return "_".join(tokens)

    def _signature_payload(self, cells: list[AtherCell]) -> tuple[str, str, float, list[str], torch.Tensor]:
        labels = [cell.label for cell in cells]
        categories = [cell.category for cell in cells]
        pattern = self.core.holographic_field.pattern.detach().clone()
        future = self.core.holographic_field.last_future_projection.detach().clone()
        fold_mean = torch.mean(torch.stack([cell.fold_signature for cell in cells], dim=0), dim=0)
        fold_mean = fold_mean / (torch.norm(fold_mean, p=2) + 1e-8)
        blended = torch.tanh(0.46 * pattern + 0.32 * future + 0.22 * fold_mean)

        category_token = "_".join(
            "".join(ch for ch in category if ch.isalnum())[:10].upper() or "CELL"
            for category in sorted(dict.fromkeys(categories))[:3]
        )
        field_token = self._field_token(blended)
        signature_seed = "|".join([category_token, field_token, str(len(labels))])
        signature = hashlib.sha1(signature_seed.encode("utf-8")).hexdigest()[:14]

        stability = _clamp(
            0.34 * sum(cell.coherence for cell in cells) / max(1, len(cells))
            + 0.24 * self.core.transcendence.last_purpose_alignment
            + 0.18 * (1.0 - self.core.holographic_field.last_projection_uncertainty)
            + 0.14 * self.core.holographic_field.last_morphic_resonance_index
            + 0.1 * (1.0 - self.core.cognition.epigenetic_registry.last_surprise_signal),
            0.0,
            1.0,
        )
        return signature, category_token or "GENERIC", stability, labels, blended

    def anchor_symbol(self, *, force: bool = False) -> Optional[Dict[str, Any]]:
        cells = self._candidate_cells()
        if len(cells) < 2 and not force:
            return None
        if len(cells) < 2:
            cells = sorted(
                [
                    cell
                    for cell in self.core.cells.values()
                    if not isinstance(cell, LibraryCell)
                ],
                key=lambda cell: (cell.activation_value, cell.coherence),
                reverse=True,
            )[:2]
        if len(cells) < 2:
            return None

        signature, label_hint, stability, labels, blended = self._signature_payload(cells)
        anchor = GLOBAL_SYMBOL_ATLAS.anchor(
            core=self.core,
            signature=signature,
            label_hint=label_hint,
            payload={
                "labels": list(labels),
                "stability": round(stability, 6),
                "purpose_alignment": round(self.core.transcendence.last_purpose_alignment, 6),
            },
        )

        symbol_id = str(anchor["symbol_id"])
        local = self._local_symbols.get(symbol_id, {})
        local["symbol_id"] = symbol_id
        local["signature"] = str(anchor["signature"])
        local["labels"] = list(labels)
        local["stability"] = float(stability)
        local["touches"] = int(local.get("touches", 0)) + 1
        local["shared_cores"] = int(anchor["shared_cores"])
        local["blended"] = blended.detach().clone()
        self._local_symbols[symbol_id] = local
        while len(self._local_symbols) > 24:
            victim = sorted(
                self._local_symbols.keys(),
                key=lambda key: (
                    float(self._local_symbols[key].get("stability", 0.0)),
                    int(self._local_symbols[key].get("touches", 0)),
                ),
            )[0]
            self._local_symbols.pop(victim, None)

        if bool(anchor["reused"]):
            self.shared_symbol_reuses += 1
        self.anchor_events += 1
        self.last_symbol_id = symbol_id
        self.last_symbol_signature = str(anchor["signature"])
        self.last_symbol_stability = stability
        self.last_symbol_shared_cores = int(anchor["shared_cores"])
        self.last_symbol_labels = list(labels)

        self.core.assembler.feed(
            category=f"SymbolAnchor::{str(anchor['signature'])[:8]}",
            relevance=min(0.14, 0.03 + 0.08 * stability),
            input_tensor=blended,
            external=False,
        )
        return {
            "symbol_id": symbol_id,
            "signature": str(anchor["signature"]),
            "stability": round(stability, 6),
            "shared_cores": int(anchor["shared_cores"]),
            "labels": list(labels),
        }

    def known_symbols(self) -> list[Dict[str, Any]]:
        ordered = sorted(
            self._local_symbols.values(),
            key=lambda meta: (float(meta.get("stability", 0.0)), int(meta.get("touches", 0))),
            reverse=True,
        )
        return [
            {
                "symbol_id": str(meta["symbol_id"]),
                "signature": str(meta["signature"]),
                "stability": round(float(meta["stability"]), 6),
                "touches": int(meta["touches"]),
                "shared_cores": int(meta["shared_cores"]),
                "labels": list(meta["labels"]),
            }
            for meta in ordered
        ]

    def export_symbol_packet(self) -> Optional[Dict[str, Any]]:
        if not self._local_symbols:
            self.anchor_symbol(force=False)
        known = self.known_symbols()
        if not known:
            return None
        top = known[0]
        meta = self._local_symbols.get(str(top["symbol_id"]), {})
        blended = meta.get("blended")
        vector: Optional[list[float]] = None
        if isinstance(blended, torch.Tensor):
            vector = blended.detach().tolist()
        self.symbol_packets_exported += 1
        return {
            "symbol_id": str(top["symbol_id"]),
            "signature": str(top["signature"]),
            "label_hint": str(top["symbol_id"]).split("::")[1] if "::" in str(top["symbol_id"]) else "GENERIC",
            "labels": list(top["labels"]),
            "stability": float(top["stability"]),
            "shared_cores": int(top["shared_cores"]),
            "touches": int(top["touches"]),
            "vector": vector,
            "exported_by": self.core.core_id,
            "exported_at": round(time.time(), 6),
        }

    def ingest_symbol_packet(self, packet: Dict[str, Any], *, source_core_id: str) -> bool:
        if not isinstance(packet, dict):
            return False
        signature = str(packet.get("signature") or "")
        if not signature:
            return False

        labels = [str(label) for label in packet.get("labels", []) if str(label)]
        stability = _clamp(float(packet.get("stability", 0.0)), 0.0, 1.0)
        label_hint = str(packet.get("label_hint") or "GENERIC")
        anchor = GLOBAL_SYMBOL_ATLAS.anchor(
            core=self.core,
            signature=signature,
            label_hint=label_hint,
            payload={
                "labels": list(labels),
                "stability": round(stability, 6),
                "source_core_id": source_core_id,
            },
        )
        symbol_id = str(anchor["symbol_id"])
        local = self._local_symbols.get(symbol_id, {})
        local["symbol_id"] = symbol_id
        local["signature"] = signature
        local["labels"] = list(labels)
        local["stability"] = max(stability, float(local.get("stability", 0.0)))
        local["touches"] = int(local.get("touches", 0)) + 1
        local["shared_cores"] = int(anchor["shared_cores"])
        vector = packet.get("vector")
        if isinstance(vector, list) and vector:
            try:
                vec = torch.tensor(vector, dtype=torch.float32).flatten()
                dims = int(self.core.holographic_field.pattern.numel())
                if vec.numel() < dims:
                    vec = torch.nn.functional.pad(vec, (0, dims - vec.numel()))
                elif vec.numel() > dims:
                    vec = vec[:dims]
                vec = vec / (torch.norm(vec, p=2) + 1e-8)
                local["blended"] = vec
                self.core.assembler.feed(
                    category=f"SharedSymbol::{signature[:8]}",
                    relevance=min(0.16, 0.04 + 0.08 * stability),
                    input_tensor=vec,
                    external=False,
                )
            except Exception:
                pass
        self._local_symbols[symbol_id] = local
        self.last_symbol_id = symbol_id
        self.last_symbol_signature = signature
        self.last_symbol_stability = float(local["stability"])
        self.last_symbol_shared_cores = int(anchor["shared_cores"])
        self.last_symbol_labels = list(labels)
        self.last_imported_symbol_id = symbol_id
        self.symbol_packets_received += 1
        if bool(anchor["reused"]):
            self.shared_symbol_reuses += 1

        for label in labels:
            cell = self.core.cells.get(label)
            if cell is None:
                continue
            cell.bump_activation(min(0.035, 0.008 + 0.02 * stability), entangled=True)
        return True

    def step(self) -> Optional[Dict[str, Any]]:
        self._tick += 1
        if self._tick % max(1, self.interval_ticks) != 0:
            return None
        return self.anchor_symbol(force=False)


class TopologicalLogic:
    """
    Topological protection groups:
    - core-core edges are knot-locked and deterministic under extreme entropy.
    - boundary edges conduct, but the protected interior is mutation-resistant.
    """

    def __init__(self, core: "AtheriaCore") -> None:
        self.core = core
        self.clusters: Dict[str, Dict[str, Set[str]]] = {}
        self.protected_edges: Set[Tuple[str, str]] = set()
        self.surface_edges: Set[Tuple[str, str]] = set()
        self.rulebook: Dict[str, float] = {
            "deterministic_base": 0.0185,
            "min_permeability": 0.45,
            "protected_min_weight": 0.75,
            "harden_min_weight": 0.82,
            "harden_max_energy": 0.04,
            "surface_in_weight": 0.58,
            "surface_out_weight": 0.56,
            "immunity_temperature": 100.0,
        }
        self.rule_version = 1
        self.rewrite_events = 0
        self.last_rewrite_signature: Optional[str] = None
        self.last_rewrite_reason: Optional[str] = None
        self.last_rewrite_pressure = 0.0
        self.last_rewrite_cluster: Optional[str] = None
        self.last_selected_policy: Optional[str] = None
        self.last_policy_score = 0.0
        self.policy_stats: Dict[str, Dict[str, float]] = {
            "stabilize_core": {"uses": 0.0, "score_total": 0.0, "last_score": 0.0},
            "explore_surface": {"uses": 0.0, "score_total": 0.0, "last_score": 0.0},
            "compress_boundary": {"uses": 0.0, "score_total": 0.0, "last_score": 0.0},
            "symbolic_promote": {"uses": 0.0, "score_total": 0.0, "last_score": 0.0},
        }
        self._rewrite_tick = 0
        self.rewrite_cadence = 9
        self.rewrite_cooldown_seconds = 0.6
        self._last_rewrite_ts = 0.0

    def export_rules(self) -> Dict[str, float]:
        return {key: float(value) for key, value in self.rulebook.items()}

    def import_rules(self, rules: Dict[str, Any]) -> None:
        if not isinstance(rules, dict):
            return
        for key, value in rules.items():
            if key not in self.rulebook:
                continue
            numeric = float(value)
            if key == "deterministic_base":
                self.rulebook[key] = _clamp(numeric, 0.012, 0.032)
            elif key == "min_permeability":
                self.rulebook[key] = _clamp(numeric, 0.28, 0.72)
            elif key == "protected_min_weight":
                self.rulebook[key] = _clamp(numeric, 0.62, 1.1)
            elif key == "harden_min_weight":
                self.rulebook[key] = _clamp(numeric, 0.72, 1.1)
            elif key == "harden_max_energy":
                self.rulebook[key] = _clamp(numeric, 0.02, 0.12)
            elif key in {"surface_in_weight", "surface_out_weight"}:
                self.rulebook[key] = _clamp(numeric, 0.35, 0.9)
            elif key == "immunity_temperature":
                self.rulebook[key] = _clamp(numeric, 82.0, 112.0)

    def _harden_connection(self, src_label: str, target_label: str) -> None:
        src = self.core.cells.get(src_label)
        if src is None:
            return
        conn = src.connections.get(target_label)
        if conn is None:
            return
        conn.frozen = True
        conn.weight = max(self.rulebook["harden_min_weight"], conn.weight)
        conn.activation_energy = min(self.rulebook["harden_max_energy"], conn.activation_energy)
        conn.protease_marks = 0
        if conn.compiled_kernel is None:
            tag = hashlib.sha1(f"topo::{src_label}->{target_label}".encode("utf-8")).hexdigest()[:10]
            conn.compiled_kernel = f"topo.kernel::{src_label}->{target_label}::{tag}"

    def register_cluster(
        self,
        name: str,
        *,
        core_labels: Iterable[str],
        boundary_labels: Iterable[str] = (),
    ) -> bool:
        core_set = {label for label in core_labels if label in self.core.cells}
        boundary_set = {label for label in boundary_labels if label in self.core.cells and label not in core_set}
        if len(core_set) < 2:
            return False

        self.clusters[name] = {"core": core_set, "boundary": boundary_set}
        self._rebuild_cluster_edges()
        return True

    def _rebuild_cluster_edges(self) -> None:
        self.protected_edges.clear()
        self.surface_edges.clear()
        for cluster in self.clusters.values():
            core_set = {label for label in cluster["core"] if label in self.core.cells}
            boundary_set = {label for label in cluster["boundary"] if label in self.core.cells and label not in core_set}
            cluster["core"] = core_set
            cluster["boundary"] = boundary_set

            for src_label in core_set:
                src = self.core.cells[src_label]
                for dst_label in core_set:
                    if src_label == dst_label:
                        continue
                    dst = self.core.cells[dst_label]
                    if dst_label not in src.connections:
                        src.add_connection(dst, weight=0.9)
                    self.protected_edges.add((src_label, dst_label))
                    self._harden_connection(src_label, dst_label)

            for src_label in boundary_set:
                src = self.core.cells[src_label]
                for dst_label in core_set:
                    dst = self.core.cells[dst_label]
                    if dst_label not in src.connections:
                        src.add_connection(dst, weight=self.rulebook["surface_in_weight"])
                    if src_label not in dst.connections:
                        dst.add_connection(src, weight=self.rulebook["surface_out_weight"])
                    self.surface_edges.add((src_label, dst_label))
                    self.surface_edges.add((dst_label, src_label))

    def is_cell_protected(self, label: str) -> bool:
        for cluster in self.clusters.values():
            if label in cluster["core"]:
                return True
        return False

    def is_edge_protected(self, src_label: str, dst_label: str) -> bool:
        return (src_label, dst_label) in self.protected_edges

    def deterministic_transfer(self, gradient: float, semipermeability: float, conn: AtherConnection) -> float:
        base = max(0.0, gradient * self.rulebook["deterministic_base"])
        permeability = max(self.rulebook["min_permeability"], semipermeability)
        weight = max(self.rulebook["protected_min_weight"], conn.weight)
        return base * permeability * weight

    def apply_extreme_entropy_immunity(self) -> int:
        if self.core.phase_controller.system_temperature <= self.rulebook["immunity_temperature"]:
            return 0
        reinforced = 0
        for cluster in self.clusters.values():
            for label in cluster["core"]:
                cell = self.core.cells.get(label)
                if cell is None:
                    continue
                cell.integrity_rate = max(0.995, cell.integrity_rate)
                cell.error_counter = max(0, cell.error_counter - 1)
                for target_label in list(cell.connections.keys()):
                    if not self.is_edge_protected(cell.label, target_label):
                        continue
                    self._harden_connection(cell.label, target_label)
                    reinforced += 1
        return reinforced

    def _rewrite_pressure(self) -> float:
        purpose = _clamp(self.core.transcendence.last_purpose_alignment, 0.0, 1.0)
        symbol_stability = _clamp(getattr(self.core.symbolics, "last_symbol_stability", 0.0), 0.0, 1.0)
        bridge = _clamp(self.core.cognition.last_morphic_bridge_pressure, 0.0, 1.0)
        surprise = _clamp(self.core.cognition.epigenetic_registry.last_surprise_signal, 0.0, 1.0)
        predictability = _clamp(self.core.cognition.epigenetic_registry.last_predictability, 0.0, 1.0)
        entropy = _clamp(self.core.phase_controller.system_temperature / 120.0, 0.0, 1.0)
        pressure = _clamp(
            0.3 * (1.0 - purpose)
            + 0.22 * surprise
            + 0.18 * (1.0 - symbol_stability)
            + 0.14 * bridge
            + 0.1 * entropy
            + 0.06 * (1.0 - predictability),
            0.0,
            1.0,
        )
        self.last_rewrite_pressure = pressure
        return pressure

    def _rule_health_score(self) -> float:
        deterministic = _clamp((self.rulebook["deterministic_base"] - 0.012) / 0.02, 0.0, 1.0)
        permeability = 1.0 - _clamp(abs(self.rulebook["min_permeability"] - 0.48) / 0.24, 0.0, 1.0)
        protected = _clamp((self.rulebook["protected_min_weight"] - 0.62) / 0.48, 0.0, 1.0)
        harden = _clamp((self.rulebook["harden_min_weight"] - 0.72) / 0.38, 0.0, 1.0)
        energy = 1.0 - _clamp((self.rulebook["harden_max_energy"] - 0.02) / 0.1, 0.0, 1.0)
        surface_balance = 1.0 - _clamp(
            abs(self.rulebook["surface_in_weight"] - self.rulebook["surface_out_weight"]) / 0.3,
            0.0,
            1.0,
        )
        immunity = 1.0 - _clamp(abs(self.rulebook["immunity_temperature"] - 97.0) / 15.0, 0.0, 1.0)
        return _clamp(
            0.18 * deterministic
            + 0.12 * permeability
            + 0.2 * protected
            + 0.18 * harden
            + 0.12 * energy
            + 0.1 * surface_balance
            + 0.1 * immunity,
            0.0,
            1.0,
        )

    def _cluster_shape_state(self) -> tuple[float, float]:
        core_count = 0
        boundary_count = 0
        for cluster in self.clusters.values():
            core_count += len(cluster["core"])
            boundary_count += len(cluster["boundary"])
        total = max(1, core_count + boundary_count)
        boundary_pressure = _clamp(boundary_count / total, 0.0, 1.0)
        boundary_available = 1.0 if boundary_count > 0 else 0.0
        return boundary_pressure, boundary_available

    def _meta_fitness_score(
        self,
        policy: str,
        *,
        force: bool,
        pressure: float,
        surprise: float,
        symbolic_bias: float,
        entropy: float,
        predictability: float,
    ) -> float:
        boundary_pressure, boundary_available = self._cluster_shape_state()
        symbol_presence = 1.0 if self.core.symbolics.last_symbol_id else 0.0
        history = self.policy_stats.get(policy, {})
        uses = float(history.get("uses", 0.0))
        mean_score = float(history.get("score_total", 0.0)) / uses if uses > 0.0 else 0.0
        exploration_bonus = 0.045 if uses == 0.0 else 0.0

        if policy == "stabilize_core":
            base = (
                0.22
                + 0.24 * symbolic_bias
                + 0.12 * entropy
                + 0.12 * pressure
                + (0.16 if force else 0.0)
            )
        elif policy == "explore_surface":
            base = (
                0.16
                + 0.34 * surprise
                + 0.18 * (1.0 - predictability)
                + 0.12 * pressure
                + 0.08 * boundary_available
                - 0.08 * symbolic_bias
            )
        elif policy == "compress_boundary":
            base = (
                0.14
                + 0.24 * boundary_pressure
                + 0.16 * predictability
                + 0.12 * symbolic_bias
                + 0.08 * entropy
                - 0.1 * surprise
            )
        else:
            base = (
                0.18
                + 0.36 * symbolic_bias
                + 0.14 * pressure
                + 0.1 * symbol_presence
                + 0.06 * boundary_available
                + (0.28 if force else 0.0)
            )

        return base + 0.14 * mean_score + exploration_bonus

    def _promote_boundary_cell(self, cluster_name: str, cluster: Dict[str, Set[str]], *, force: bool, symbolic_bias: float) -> bool:
        core_set = set(cluster["core"])
        boundary_set = set(cluster["boundary"])
        ranked_boundary = sorted(
            [self.core.cells[label] for label in boundary_set if label in self.core.cells],
            key=lambda cell: (cell.activation_value, cell.coherence),
            reverse=True,
        )
        if ranked_boundary and (force or symbolic_bias >= 0.58):
            promote = ranked_boundary[0]
            if promote.label not in core_set:
                core_set.add(promote.label)
                boundary_set.discard(promote.label)
                self.register_cluster(
                    cluster_name,
                    core_labels=sorted(core_set),
                    boundary_labels=sorted(boundary_set),
                )
                self.last_rewrite_cluster = cluster_name
                return True
        return False

    def _expand_symbolic_boundary(self, cluster_name: str, cluster: Dict[str, Set[str]], *, force: bool, symbolic_bias: float) -> bool:
        core_set = set(cluster["core"])
        boundary_set = set(cluster["boundary"])
        excluded = core_set | boundary_set | {self.core.aion.singularity_label, self.core.transcendence.telos.purpose_label}
        symbol_labels = list(getattr(self.core.symbolics, "last_symbol_labels", []))
        candidates = [
            self.core.cells[label]
            for label in symbol_labels
            if label in self.core.cells and label not in excluded
        ]
        candidates.sort(key=lambda cell: (cell.activation_value, cell.coherence), reverse=True)
        if candidates and (force or symbolic_bias >= 0.42):
            boundary_set.add(candidates[0].label)
            self.register_cluster(
                cluster_name,
                core_labels=sorted(core_set),
                boundary_labels=sorted(boundary_set),
            )
            self.last_rewrite_cluster = cluster_name
            return True
        return False

    def _compress_cluster_shape(self, cluster_name: str, cluster: Dict[str, Set[str]], *, force: bool) -> bool:
        core_set = set(cluster["core"])
        boundary_set = set(cluster["boundary"])
        if boundary_set:
            ranked_boundary = sorted(
                [self.core.cells[label] for label in boundary_set if label in self.core.cells],
                key=lambda cell: (cell.activation_value, cell.coherence),
            )
            if ranked_boundary and (force or len(boundary_set) >= 1):
                boundary_set.discard(ranked_boundary[0].label)
                self.register_cluster(
                    cluster_name,
                    core_labels=sorted(core_set),
                    boundary_labels=sorted(boundary_set),
                )
                self.last_rewrite_cluster = cluster_name
                return True
        if len(core_set) > 2:
            ranked_core = sorted(
                [self.core.cells[label] for label in core_set if label in self.core.cells],
                key=lambda cell: (cell.activation_value, cell.coherence),
            )
            if ranked_core:
                demote = ranked_core[0].label
                core_set.discard(demote)
                boundary_set.add(demote)
                self.register_cluster(
                    cluster_name,
                    core_labels=sorted(core_set),
                    boundary_labels=sorted(boundary_set),
                )
                self.last_rewrite_cluster = cluster_name
                return True
        return False

    def _rewrite_cluster_shape(self, *, mode: str, force: bool, symbolic_bias: float) -> Optional[str]:
        if not self.clusters:
            return None
        cluster_name = sorted(self.clusters.keys())[0]
        cluster = self.clusters[cluster_name]
        changed = False
        if mode == "compress":
            changed = self._compress_cluster_shape(cluster_name, cluster, force=force)
        elif mode == "expand":
            changed = self._expand_symbolic_boundary(cluster_name, cluster, force=force, symbolic_bias=symbolic_bias)
            if not changed and force:
                changed = self._promote_boundary_cell(cluster_name, cluster, force=True, symbolic_bias=symbolic_bias)
        elif mode == "promote":
            changed = self._promote_boundary_cell(cluster_name, cluster, force=force, symbolic_bias=symbolic_bias)
            if not changed:
                changed = self._expand_symbolic_boundary(cluster_name, cluster, force=force, symbolic_bias=symbolic_bias)
        if changed:
            return cluster_name
        return None

    def _apply_policy(
        self,
        policy: str,
        *,
        force: bool,
        pressure: float,
        surprise: float,
        symbolic_bias: float,
        entropy: float,
        predictability: float,
    ) -> Optional[str]:
        delta = 0.02 + 0.08 * pressure
        if policy == "explore_surface":
            self.rulebook["surface_in_weight"] = _clamp(self.rulebook["surface_in_weight"] + 0.22 * delta, 0.35, 0.9)
            self.rulebook["surface_out_weight"] = _clamp(self.rulebook["surface_out_weight"] + 0.2 * delta, 0.35, 0.9)
            self.rulebook["harden_min_weight"] = _clamp(self.rulebook["harden_min_weight"] - 0.14 * delta, 0.72, 1.1)
            self.rulebook["immunity_temperature"] = _clamp(
                self.rulebook["immunity_temperature"] - 9.0 * delta,
                82.0,
                112.0,
            )
            return self._rewrite_cluster_shape(mode="expand", force=force, symbolic_bias=max(symbolic_bias, pressure))

        if policy == "compress_boundary":
            self.rulebook["min_permeability"] = _clamp(self.rulebook["min_permeability"] + 0.08 * delta, 0.28, 0.72)
            self.rulebook["protected_min_weight"] = _clamp(
                self.rulebook["protected_min_weight"] + 0.08 * delta,
                0.62,
                1.1,
            )
            self.rulebook["surface_in_weight"] = _clamp(self.rulebook["surface_in_weight"] - 0.14 * delta, 0.35, 0.9)
            self.rulebook["surface_out_weight"] = _clamp(self.rulebook["surface_out_weight"] - 0.12 * delta, 0.35, 0.9)
            self.rulebook["harden_max_energy"] = _clamp(self.rulebook["harden_max_energy"] - 0.02 * delta, 0.02, 0.12)
            return self._rewrite_cluster_shape(mode="compress", force=force, symbolic_bias=symbolic_bias)

        if policy == "symbolic_promote":
            self.rulebook["deterministic_base"] = _clamp(
                self.rulebook["deterministic_base"] + 0.05 * delta,
                0.012,
                0.032,
            )
            self.rulebook["protected_min_weight"] = _clamp(
                self.rulebook["protected_min_weight"] + 0.14 * delta,
                0.62,
                1.1,
            )
            self.rulebook["harden_min_weight"] = _clamp(
                self.rulebook["harden_min_weight"] + 0.12 * delta,
                0.72,
                1.1,
            )
            self.rulebook["harden_max_energy"] = _clamp(self.rulebook["harden_max_energy"] - 0.03 * delta, 0.02, 0.12)
            self.rulebook["immunity_temperature"] = _clamp(
                self.rulebook["immunity_temperature"] + 5.0 * (symbolic_bias - 0.5 * entropy),
                82.0,
                112.0,
            )
            return self._rewrite_cluster_shape(mode="promote", force=force, symbolic_bias=max(symbolic_bias, pressure))

        self.rulebook["deterministic_base"] = _clamp(self.rulebook["deterministic_base"] + 0.04 * delta, 0.012, 0.032)
        self.rulebook["protected_min_weight"] = _clamp(self.rulebook["protected_min_weight"] + 0.12 * delta, 0.62, 1.1)
        self.rulebook["harden_min_weight"] = _clamp(self.rulebook["harden_min_weight"] + 0.1 * delta, 0.72, 1.1)
        self.rulebook["harden_max_energy"] = _clamp(self.rulebook["harden_max_energy"] - 0.03 * delta, 0.02, 0.12)
        self.rulebook["immunity_temperature"] = _clamp(
            self.rulebook["immunity_temperature"] + 4.0 * (symbolic_bias - entropy),
            82.0,
            112.0,
        )
        return self._rewrite_cluster_shape(mode="promote", force=force, symbolic_bias=max(symbolic_bias, pressure))

    def recursive_self_modify(self, *, force: bool = False) -> bool:
        now = time.perf_counter()
        if not force and (now - self._last_rewrite_ts) < self.rewrite_cooldown_seconds:
            return False

        pressure = self._rewrite_pressure()
        threshold = 0.58 if self.core.aion_meditation_mode else 0.68
        if not force and pressure < threshold:
            return False

        surprise = _clamp(self.core.cognition.epigenetic_registry.last_surprise_signal, 0.0, 1.0)
        symbolic_bias = _clamp(getattr(self.core.symbolics, "last_symbol_stability", 0.0), 0.0, 1.0)
        entropy = _clamp(self.core.phase_controller.system_temperature / 120.0, 0.0, 1.0)
        predictability = _clamp(self.core.cognition.epigenetic_registry.last_predictability, 0.0, 1.0)
        pre_health = self._rule_health_score()
        scores = {
            policy: self._meta_fitness_score(
                policy,
                force=force,
                pressure=pressure,
                surprise=surprise,
                symbolic_bias=symbolic_bias,
                entropy=entropy,
                predictability=predictability,
            )
            for policy in self.policy_stats
        }
        selected_policy = max(
            sorted(scores.keys()),
            key=lambda policy: (scores[policy], policy),
        )
        self.last_selected_policy = selected_policy
        if hasattr(self.core, "safety"):
            allowed, reason = self.core.safety.authorize_topology_rewrite(
                force=force,
                policy=selected_policy,
                preview=False,
            )
            if not allowed:
                self.last_policy_score = 0.0
                self.last_rewrite_reason = f"blocked::{reason}"
                self.last_rewrite_signature = None
                return False
        pre_rules = self.export_rules()
        pre_clusters = {
            name: {
                "core": set(cluster["core"]),
                "boundary": set(cluster["boundary"]),
            }
            for name, cluster in self.clusters.items()
        }
        pre_audit = self.core.safety.capture_sensitive_snapshot() if hasattr(self.core, "safety") else None
        cluster_name = self._apply_policy(
            selected_policy,
            force=force,
            pressure=pressure,
            surprise=surprise,
            symbolic_bias=symbolic_bias,
            entropy=entropy,
            predictability=predictability,
        )
        if pre_audit is not None:
            post_audit = self.core.safety.capture_sensitive_snapshot()
            invariant_ok = self.core.safety.audit_transition(
                "topology_rewrite",
                pre=pre_audit,
                post=post_audit,
                payload={
                    "policy": selected_policy,
                    "cluster": cluster_name,
                    "pressure": round(pressure, 6),
                },
                accepted=True,
            )
            if not invariant_ok:
                self.import_rules(pre_rules)
                self.clusters = {
                    name: {
                        "core": set(cluster["core"]),
                        "boundary": set(cluster["boundary"]),
                    }
                    for name, cluster in pre_clusters.items()
                }
                self._rebuild_cluster_edges()
                self.last_policy_score = 0.0
                self.last_rewrite_reason = f"blocked::{self.core.safety.last_block_reason}"
                self.last_rewrite_signature = None
                return False
        post_health = self._rule_health_score()
        policy_score = _clamp(
            0.48
            + 0.42 * max(0.0, post_health - pre_health)
            + 0.18 * scores[selected_policy]
            + (0.08 if cluster_name else 0.0),
            0.0,
            1.6,
        )
        stats = self.policy_stats[selected_policy]
        stats["uses"] = float(stats.get("uses", 0.0)) + 1.0
        stats["score_total"] = float(stats.get("score_total", 0.0)) + policy_score
        stats["last_score"] = policy_score
        self.last_policy_score = policy_score
        reason = f"policy::{selected_policy}"
        signature_seed = (
            f"{reason}|{round(pressure, 4)}|{round(policy_score, 4)}|"
            f"{round(self.rulebook['deterministic_base'], 5)}|{round(self.rulebook['harden_min_weight'], 5)}|"
            f"{cluster_name or 'NONE'}"
        )
        self.last_rewrite_signature = hashlib.sha1(signature_seed.encode("utf-8")).hexdigest()[:12]
        self.last_rewrite_reason = reason
        self._last_rewrite_ts = now
        self.rule_version += 1
        self.rewrite_events += 1
        return True

    def step(self) -> bool:
        self._rewrite_tick += 1
        if self._rewrite_tick % max(1, self.rewrite_cadence) != 0:
            return False
        return self.recursive_self_modify(force=False)

    def snapshot(self) -> Dict[str, Any]:
        core_cells = set()
        boundary_cells = set()
        for cluster in self.clusters.values():
            core_cells.update(cluster["core"])
            boundary_cells.update(cluster["boundary"])
        return {
            "clusters": len(self.clusters),
            "core_cells": len(core_cells),
            "boundary_cells": len(boundary_cells),
            "protected_edges": len(self.protected_edges),
            "rule_version": self.rule_version,
            "rewrite_events": self.rewrite_events,
            "last_policy": self.last_selected_policy,
            "last_policy_score": round(self.last_policy_score, 6),
        }


class Atheria_Rhythm:
    """
    Circadian rhythm:
    - wake: high input sensitivity and aggressive diffusion.
    - sleep: input filtering, deep refolding, field consolidation, enzymatic cleanup.
    """

    def __init__(
        self,
        core: "AtheriaCore",
        *,
        wake_duration: float = 3.0,
        sleep_duration: float = 1.8,
        interval: float = 0.25,
    ) -> None:
        self.core = core
        self.wake_duration = wake_duration
        self.sleep_duration = sleep_duration
        self.interval = interval
        self.state = RhythmState.WAKE
        self._last_switch = time.perf_counter()
        self.cycle_count = 0
        self.dream_replay_events = 0
        self.last_replay_labels: list[str] = []
        self.inter_core_dreaming_enabled = True
        self.inter_core_dream_sync_events = 0
        self.inter_core_dream_trauma_events = 0
        self.last_inter_core_peer_count = 0
        self.last_inter_core_coherence = 0.0
        self.last_inter_core_trauma_intensity = 0.0

    @property
    def diffusion_gain(self) -> float:
        return 1.25 if self.state is RhythmState.WAKE else 0.52

    @property
    def input_gain(self) -> float:
        return 1.0 if self.state is RhythmState.WAKE else 0.28

    def _should_switch(self) -> bool:
        elapsed = time.perf_counter() - self._last_switch
        limit = self.wake_duration if self.state is RhythmState.WAKE else self.sleep_duration
        return elapsed >= limit

    def _switch(self) -> None:
        self.state = RhythmState.SLEEP if self.state is RhythmState.WAKE else RhythmState.WAKE
        self._last_switch = time.perf_counter()
        self.cycle_count += 1

    def filter_input(self, value: float) -> float:
        return max(0.0, min(1.0, float(value) * self.input_gain))

    def _sleep_consolidation(self) -> None:
        cells = tuple(self.core.cells.values())
        if not cells:
            return
        for cell in cells:
            cell.refold()
            if cell.activation_value > 0.01:
                cell.set_activation(cell.activation_value * 0.985)

        replay = self.core.holographic_field.reverse_inference(cells, top_k=min(8, len(cells)))
        replay_labels: list[str] = []
        replay_strength = 0.0
        if replay:
            replay_strength = _clamp(
                sum(float(entry.get("score", 0.0)) for entry in replay) / max(1, len(replay)),
                0.0,
                1.0,
            )
        for entry in replay:
            label = entry["label"]
            score = float(entry["score"])
            cell = self.core.cells.get(label)
            if cell is None:
                continue
            # Dream replay stabilizes underused cells.
            if self.core.aion_meditation_mode or cell.silent_epochs >= 6 or cell.integrity_rate < 0.94:
                pulse = min(0.12, 0.03 + 0.08 * score)
                cell.bump_activation(pulse, entangled=True)
                cell.integrity_rate = min(1.0, cell.integrity_rate + 0.02 + 0.03 * score)
                replay_labels.append(label)
                if self.core.aion_meditation_mode:
                    # Internal dream matter for autonomous semantic growth.
                    self.core.assembler.feed(
                        category=f"Dream_{cell.category}",
                        relevance=min(0.22, 0.08 + 0.18 * score),
                        input_tensor=cell.fold_signature,
                        external=False,
                    )
                    self.core.assembler.feed(
                        category=f"DreamGap_{cell.label}",
                        relevance=min(0.2, 0.07 + 0.16 * score),
                        input_tensor=(0.7 * cell.fold_signature + 0.3 * self.core.holographic_field.pattern),
                        external=False,
                    )

        imagination = self.core.aion.run_imagination_cycle()
        replay_strength = max(replay_strength, 0.65 * float(imagination.get("uncertainty", 0.0)))
        for label in imagination.get("labels", []):
            if label not in replay_labels:
                replay_labels.append(str(label))

        self.last_replay_labels = replay_labels[:6]
        if replay_labels:
            self.dream_replay_events += len(replay_labels)

        self.core.holographic_field.imprint(cells)
        self.core.holographic_field.imprint(cells)
        reclaimed = self.core.biosynthesis.enzymatic_optimizer.sleep_cleanup(intensity=1.0)
        if reclaimed > 0.0:
            self.core.assembler.reclaim_resources(reclaimed)
        if hasattr(self.core, "episodic_memory"):
            self.core.episodic_memory.consolidate_sleep(intensity=max(0.8, replay_strength))
        self._inter_core_dream_sync(replay_labels=replay_labels, replay_strength=replay_strength)

    def _inter_core_dream_sync(self, *, replay_labels: list[str], replay_strength: float) -> None:
        if not self.inter_core_dreaming_enabled:
            return
        if self.core.aion_meditation_mode:
            return

        GLOBAL_MORPHIC_NODE.publish_sleep_dream(
            core=self.core,
            replay_labels=replay_labels,
            replay_strength=replay_strength,
        )
        packet = GLOBAL_MORPHIC_NODE.collect_collective_resonance(self.core)
        peer_count = int(packet.get("peer_count", 0))
        self.last_inter_core_peer_count = peer_count
        if peer_count <= 0:
            self.last_inter_core_coherence = 0.0
            self.last_inter_core_trauma_intensity = 0.0
            return

        resonance = packet.get("resonance")
        trauma_noise = packet.get("instinctive_noise")
        coherence = _clamp(float(packet.get("coherence", 0.0)), 0.0, 1.0)
        trauma_intensity = _clamp(float(packet.get("trauma_intensity", 0.0)), 0.0, 1.0)
        self.last_inter_core_coherence = coherence
        self.last_inter_core_trauma_intensity = trauma_intensity

        if not isinstance(resonance, torch.Tensor):
            return
        if not isinstance(trauma_noise, torch.Tensor):
            trauma_noise = torch.zeros_like(resonance)

        resonance = resonance / (torch.norm(resonance, p=2) + 1e-8)
        trauma_noise = trauma_noise / (torch.norm(trauma_noise, p=2) + 1e-8)

        collective_field = torch.tanh(
            0.86 * self.core.holographic_field.pattern
            + 0.11 * resonance
            + 0.03 * trauma_noise * trauma_intensity
        )
        self.core.holographic_field.pattern = collective_field

        collective_index = _clamp(
            0.45 * coherence
            + 0.25 * replay_strength
            + 0.2 * _clamp(peer_count / 5.0, 0.0, 1.0)
            + 0.1 * trauma_intensity,
            0.0,
            1.0,
        )
        self.core.holographic_field.last_morphic_resonance_index = max(
            self.core.holographic_field.last_morphic_resonance_index,
            collective_index,
        )

        self.core.assembler.feed(
            category="InterCoreDream",
            relevance=min(0.24, 0.08 + 0.2 * coherence),
            input_tensor=resonance,
            external=False,
        )
        if trauma_intensity > 0.06:
            self.core.assembler.feed(
                category="InterCoreTrauma",
                relevance=min(0.2, 0.05 + 0.18 * trauma_intensity),
                input_tensor=trauma_noise,
                external=False,
            )
            self.inter_core_dream_trauma_events += 1

        self.inter_core_dream_sync_events += 1

    async def run(self) -> None:
        while self.core.running:
            if self.core.aion_meditation_mode:
                if self.state is not RhythmState.SLEEP:
                    self.state = RhythmState.SLEEP
                self._sleep_consolidation()
                await asyncio.sleep(self.interval)
                continue
            if self._should_switch():
                self._switch()
            if self.state is RhythmState.SLEEP:
                self._sleep_consolidation()
            await asyncio.sleep(self.interval)


AtheriaRhythm = Atheria_Rhythm


class AtherTimeCrystal:
    """
    Temporal crystal oscillator for procedural memory consolidation.
    """

    def __init__(self, core: "AtheriaCore", interval: float = 0.12) -> None:
        self.core = core
        self.interval = interval
        self.oscillators: Dict[str, Dict[str, float]] = {}
        self.tick = 0
        self.last_crystal_energy = 0.0

    def _candidate_cells(self) -> list[AtherCell]:
        excluded = {self.core.aion.singularity_label}
        if hasattr(self.core, "transcendence"):
            excluded.add(self.core.transcendence.telos.purpose_label)
        cells = [
            cell
            for cell in self.core.cells.values()
            if cell.label not in excluded and not self.core.topological_logic.is_cell_protected(cell.label)
        ]
        scored: list[tuple[float, AtherCell]] = []
        for cell in cells:
            total_usage = sum(conn.usage_count for conn in cell.connections.values())
            total_flux = sum(conn.catalytic_flux for conn in cell.connections.values())
            score = total_usage * 0.02 + total_flux + cell.activation_value
            scored.append((score, cell))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [cell for _, cell in scored[:6]]

    def _ensure_oscillators(self) -> None:
        for cell in self._candidate_cells():
            if cell.label in self.oscillators:
                continue
            self.oscillators[cell.label] = {
                "amp": random.uniform(0.06, 0.14),
                "freq": random.uniform(0.4, 1.25),
                "phase": random.uniform(0.0, 2.0 * math.pi),
            }
        stale = [label for label in self.oscillators.keys() if label not in self.core.cells]
        for label in stale:
            self.oscillators.pop(label, None)

    def _procedural_consolidation(self) -> None:
        for cell in self.core.cells.values():
            for conn in cell.connections.values():
                if conn.usage_count < 10:
                    continue
                if conn.efficiency < 0.5:
                    continue
                conn.frozen = True
                conn.weight = min(1.8, conn.weight + 0.015)
                conn.activation_energy = max(0.04, conn.activation_energy * 0.94)
                conn.compute_savings = min(1.0, conn.compute_savings + 0.015)

    def step(self) -> None:
        if self.core.aion_meditation_mode:
            self.last_crystal_energy *= 0.92
            return
        self._ensure_oscillators()
        self.tick += 1
        if not self.oscillators:
            self.last_crystal_energy = 0.0
            return

        rhythm_factor = 0.85 if self.core.rhythm.state is RhythmState.SLEEP else 1.0
        energies: list[float] = []
        t = self.tick * self.interval
        for label, params in list(self.oscillators.items()):
            cell = self.core.cells.get(label)
            if cell is None:
                continue
            wave = math.sin(t * params["freq"] + params["phase"])
            pulse = params["amp"] * (0.5 + 0.5 * wave) * rhythm_factor
            if pulse <= 0.0:
                continue
            cell.bump_activation(pulse, entangled=True)
            cell.integrity_rate = min(1.0, cell.integrity_rate + 0.004 + 0.02 * pulse)
            energies.append(abs(pulse))

        self.last_crystal_energy = sum(energies) / max(1, len(energies))
        if self.tick % 14 == 0:
            self._procedural_consolidation()

    async def run(self) -> None:
        while self.core.running:
            self.step()
            await asyncio.sleep(self.interval)


class AionLayer:
    def __init__(self, core: "AtheriaCore") -> None:
        self.core = core
        self.singularity_label = "SingularityNode"
        self.time_crystal = AtherTimeCrystal(core)
        self.last_singularity_activation = 0.0
        self.imagination_enabled = True
        self.imagination_cycles = 0
        self.last_imagination_vectors = 0
        self.last_imagination_gap_closures = 0
        self.last_imagination_uncertainty = 0.0
        self.last_imagination_cost = 0.0
        self.last_imagination_labels: list[str] = []

    def _imagination_candidates(self) -> list[AtherCell]:
        excluded = {self.singularity_label}
        if hasattr(self.core, "transcendence"):
            excluded.add(self.core.transcendence.telos.purpose_label)
        return [
            cell
            for cell in self.core.cells.values()
            if cell.label not in excluded and not isinstance(cell, LibraryCell)
        ]

    def run_imagination_cycle(self) -> Dict[str, Any]:
        self.last_imagination_vectors = 0
        self.last_imagination_gap_closures = 0
        self.last_imagination_cost = 0.0
        self.last_imagination_labels = []
        self.last_imagination_uncertainty = 0.0

        if not self.imagination_enabled or self.core.rhythm.state is not RhythmState.SLEEP:
            return {
                "vectors": 0,
                "gap_closures": 0,
                "uncertainty": 0.0,
                "cost": 0.0,
                "labels": [],
            }

        cells = self._imagination_candidates()
        if not cells:
            return {
                "vectors": 0,
                "gap_closures": 0,
                "uncertainty": 0.0,
                "cost": 0.0,
                "labels": [],
            }

        current = self.core.holographic_field.pattern.detach().clone()
        projection = self.core.holographic_field.future_projection(horizon=3, damping=0.84)
        gap = torch.tanh(projection - current)
        projection_norm = projection / (torch.norm(projection, p=2) + 1e-8)
        gap_energy = float(torch.norm(gap, p=2))
        uncertainty = max(
            float(self.core.holographic_field.last_projection_uncertainty),
            float(self.core.holographic_field.last_uncertainty),
        )
        self.last_imagination_uncertainty = uncertainty

        ranked: list[tuple[float, AtherCell]] = []
        for cell in cells:
            fold = cell.fold_signature / (torch.norm(cell.fold_signature, p=2) + 1e-8)
            projection_fit = max(0.0, float(torch.dot(projection_norm, fold)))
            mismatch = float(torch.norm(fold - projection_norm, p=2))
            underuse = min(1.0, float(cell.silent_epochs) / 10.0)
            fragility = 1.0 - _clamp(cell.integrity_rate, 0.0, 1.0)
            score = _clamp(
                0.48 * projection_fit
                + 0.24 * (1.0 / (1.0 + mismatch))
                + 0.16 * underuse
                + 0.12 * fragility,
                0.0,
                1.0,
            )
            ranked.append((score, cell))
        ranked.sort(key=lambda item: item[0], reverse=True)

        for idx, (score, cell) in enumerate(ranked[: min(3, len(ranked))]):
            rolled_gap = torch.roll(gap, shifts=idx + 1)
            synthetic = 0.52 * projection + 0.28 * cell.fold_signature + 0.2 * rolled_gap
            synthetic = synthetic / (torch.norm(synthetic, p=2) + 1e-8)
            counterfactual = torch.tanh(0.7 * synthetic + 0.3 * gap)
            self.core.assembler.feed(
                category=f"DreamForward::{cell.category}",
                relevance=min(0.24, 0.07 + 0.16 * score + 0.04 * uncertainty),
                input_tensor=synthetic,
                external=False,
            )
            self.core.assembler.feed(
                category=f"Counterfactual::{cell.label}",
                relevance=min(0.2, 0.05 + 0.14 * score),
                input_tensor=counterfactual,
                external=False,
            )
            if score > 0.55:
                cell.bump_activation(min(0.045, 0.012 + 0.03 * score), entangled=True)
            self.last_imagination_labels.append(cell.label)
            self.last_imagination_vectors += 1

        if uncertainty > 0.42 and self.core.assembler.resource_pool > 0.18:
            budget = min(
                self.core.assembler.resource_pool,
                0.12 + 0.28 * uncertainty + 0.08 * min(1.0, gap_energy),
            )
            budget = min(0.34, budget)
            if budget > 0.0:
                self.core.assembler.resource_pool -= budget
                self.last_imagination_cost = budget
                self.last_imagination_gap_closures = self.core.transcendence.intuition.fill_knowledge_gap(
                    gap,
                    intensity=uncertainty,
                    resource_budget=budget,
                )

        if self.last_imagination_vectors or self.last_imagination_gap_closures:
            self.core.holographic_field.pattern = torch.tanh(0.82 * current + 0.12 * projection + 0.06 * gap)
            self.core.holographic_field.energy = float(torch.norm(self.core.holographic_field.pattern, p=2))
            self.core.holographic_field.pattern_history.append(self.core.holographic_field.pattern.detach().clone())
            self.imagination_cycles += 1

        return {
            "vectors": self.last_imagination_vectors,
            "gap_closures": self.last_imagination_gap_closures,
            "uncertainty": round(self.last_imagination_uncertainty, 6),
            "cost": round(self.last_imagination_cost, 6),
            "labels": list(self.last_imagination_labels),
        }

    def ensure_singularity_node(self) -> SingularityNode:
        node = self.core.cells.get(self.singularity_label)
        if isinstance(node, SingularityNode):
            return node

        singularity = SingularityNode(
            label=self.singularity_label,
            category="MetaState",
            semipermeability=0.55,
        )
        self.core.cells[self.singularity_label] = singularity
        self.core.aether.upsert_cell(singularity)
        return singularity

    def wire_singularity(self) -> None:
        singularity = self.ensure_singularity_node()
        candidates = [
            cell
            for cell in self.core.cells.values()
            if cell.label != singularity.label
        ]
        preferred = ["Sicherheit", "Reaktion", "Analyse", "Heilung", "Navigation"]
        ordered: list[AtherCell] = []
        for label in preferred:
            cell = self.core.cells.get(label)
            if cell and cell.label != singularity.label:
                ordered.append(cell)
        for cell in candidates:
            if cell not in ordered:
                ordered.append(cell)

        for cell in ordered[:7]:
            if cell.label not in singularity.connections:
                singularity.add_connection(cell, weight=0.34)
            if singularity.label not in cell.connections:
                cell.add_connection(singularity, weight=0.28)

    def step(self, cpu_load: float) -> float:
        singularity = self.ensure_singularity_node()
        self.wire_singularity()
        entropy = sum(self.core.phase_controller.local_entropy.values())
        activation = singularity.reflect_system_state(
            system_temperature=self.core.phase_controller.system_temperature,
            cpu_load=cpu_load,
            resource_pool=self.core.assembler.resource_pool,
            local_entropy=entropy,
            rhythm_state=self.core.rhythm.state,
        )
        self.last_singularity_activation = activation

        if self.core.aion_meditation_mode:
            return activation

        # Mirror feeling back into the network.
        for conn in singularity.connections.values():
            if self.core.cognition.epigenetic_registry.is_silenced(singularity.label, conn.target.label):
                continue
            feeling_flux = activation * 0.04 * conn.weight
            if feeling_flux > self.core.min_transfer:
                conn.target.bump_activation(feeling_flux, source=singularity, entangled=True)
                conn.usage_count += 1
                if feeling_flux > self.core.success_transfer:
                    conn.success_count += 1
        return activation


class IntuitionEngine:
    """
    Plasma-only stochastic resonance to trigger creative extrapolation beyond current path horizons.
    """

    def __init__(self, core: "AtheriaCore") -> None:
        self.core = core
        self.last_spikes = 0
        self.total_spikes = 0
        self.last_noise_energy = 0.0
        self.surprise_events = 0
        self.last_surprise_heat = 0.0
        self.last_surprise_label: Optional[str] = None
        self._last_surprise_edge: Dict[str, float] = {}
        self.surprise_cooldown_seconds = 0.18

    def _eligible_cells(self) -> list[AtherCell]:
        excluded = {self.core.aion.singularity_label, self.core.transcendence.telos.purpose_label}
        cells = []
        for cell in self.core.cells.values():
            if cell.label in excluded:
                continue
            if self.core.topological_logic.is_cell_protected(cell.label):
                continue
            cells.append(cell)
        return cells

    def _emit_creative_probe(self, cell: AtherCell, magnitude: float) -> None:
        probe = cell.fold_signature.detach().clone()
        probe = probe + torch.randn_like(probe) * min(0.22, magnitude * 2.4)
        probe = probe / (torch.norm(probe, p=2) + 1e-8)
        gap_idx = int(torch.argmax(torch.abs(probe - self.core.holographic_field.pattern)).item())
        self.core.assembler.feed(
            category=f"Intuition_{cell.category}",
            relevance=min(0.18, 0.05 + magnitude * 1.4),
            input_tensor=probe,
            external=False,
        )
        self.core.assembler.feed(
            category=f"IntuitionGap_{gap_idx}",
            relevance=min(0.16, 0.04 + magnitude * 1.2),
            input_tensor=probe,
            external=False,
        )

    def fill_knowledge_gap(self, gap_vector: torch.Tensor, intensity: float, *, resource_budget: float = 0.0) -> int:
        cells = self._eligible_cells()
        if not cells:
            return 0

        probe = gap_vector.detach().float().flatten()
        dims = int(self.core.holographic_field.pattern.numel())
        if probe.numel() < dims:
            probe = torch.nn.functional.pad(probe, (0, dims - probe.numel()))
        elif probe.numel() > dims:
            probe = probe[:dims]
        probe = probe / (torch.norm(probe, p=2) + 1e-8)

        ranked: list[tuple[float, AtherCell]] = []
        for cell in cells:
            fold = cell.fold_signature / (torch.norm(cell.fold_signature, p=2) + 1e-8)
            mismatch = float(torch.norm(fold - probe, p=2))
            ranked.append((mismatch, cell))
        ranked.sort(key=lambda item: item[0], reverse=True)
        selected = [cell for _, cell in ranked[: max(1, min(3, len(ranked)))]]
        if not selected:
            return 0

        budget_scale = min(1.0, resource_budget / 0.34) if resource_budget > 0.0 else 0.0
        created = 0
        for idx, cell in enumerate(selected):
            partner = selected[(idx + 1) % len(selected)]
            blended = 0.44 * probe + 0.34 * cell.fold_signature + 0.22 * partner.fold_signature
            blended = blended + torch.randn_like(blended) * min(0.08, 0.02 + 0.05 * intensity)
            blended = blended / (torch.norm(blended, p=2) + 1e-8)
            self.core.assembler.feed(
                category=f"IntuitionBridge::{cell.category}::{partner.category}",
                relevance=min(0.22, 0.05 + 0.12 * intensity + 0.05 * budget_scale),
                input_tensor=blended,
                external=False,
            )
            if resource_budget > 0.0:
                cell.bump_activation(min(0.04, 0.008 + 0.024 * intensity), source=partner, entangled=True)
                cell.integrity_rate = min(1.0, cell.integrity_rate + 0.006 + 0.01 * intensity)
            created += 1

        self.last_spikes = max(self.last_spikes, created)
        self.total_spikes += created
        self.last_noise_energy = max(self.last_noise_energy, float(torch.norm(probe, p=2)) * max(0.0, intensity))
        return created

    def trigger_surprise_response(
        self,
        src: AtherCell,
        target: AtherCell,
        *,
        raw_transfer: float,
        surprise: float,
        predictability: float,
    ) -> bool:
        if surprise < 0.58:
            return False

        edge_key = f"{src.label}->{target.label}"
        now = time.perf_counter()
        last = self._last_surprise_edge.get(edge_key, 0.0)
        if (now - last) < self.surprise_cooldown_seconds:
            return False
        self._last_surprise_edge[edge_key] = now

        shock = min(1.0, float(raw_transfer) / max(0.03, self.core.success_transfer))
        heat = min(14.0, 1.8 + 9.6 * surprise + 2.4 * shock)
        label = f"Surprise::{src.label}->{target.label}"
        self.core.phase_controller.spike_local_entropy(label, magnitude=8.0 + 24.0 * surprise + 6.0 * shock)
        self.core.phase_controller.system_temperature = min(
            120.0,
            self.core.phase_controller.system_temperature + heat * 0.22,
        )
        self.core.phase_controller.inject_temperature(heat * 0.78)

        mismatch = torch.tanh(src.fold_signature - target.fold_signature)
        mismatch = mismatch / (torch.norm(mismatch, p=2) + 1e-8)
        counterfactual = torch.tanh(0.55 * mismatch + 0.45 * self.core.holographic_field.last_future_projection)
        magnitude = min(0.22, 0.05 + 0.12 * surprise + 0.05 * (1.0 - predictability))
        self.core.assembler.feed(
            category=f"Surprise::{target.category}",
            relevance=magnitude,
            input_tensor=mismatch,
            external=False,
        )
        self.core.assembler.feed(
            category=f"PredictionError::{src.label}->{target.label}",
            relevance=min(0.2, 0.04 + 0.14 * surprise),
            input_tensor=counterfactual,
            external=False,
        )
        self._emit_creative_probe(target, magnitude=min(0.14, 0.04 + 0.08 * surprise))

        self.last_spikes += 1
        self.total_spikes += 1
        self.surprise_events += 1
        self.last_noise_energy = max(self.last_noise_energy, surprise * max(0.0, float(raw_transfer)))
        self.last_surprise_heat = heat
        self.last_surprise_label = label
        return True

    def step(self) -> int:
        self.last_spikes = 0
        self.last_noise_energy = 0.0
        self.last_surprise_heat = 0.0
        self.last_surprise_label = None
        if self.core.aion_meditation_mode:
            return 0
        if self.core.phase_controller.current_state is not AggregateState.PLASMA:
            return 0

        cells = self._eligible_cells()
        if not cells:
            return 0

        uncertainty = self.core.holographic_field.last_uncertainty
        damping = max(0.35, 1.0 - self.core.phase_controller.structural_tension * 0.45)
        sample_count = min(len(cells), max(4, int(math.sqrt(len(cells)) * 4)))
        sampled = random.sample(cells, sample_count) if len(cells) > sample_count else cells
        total_noise = 0.0

        for cell in sampled:
            path_horizon = max(1, len(cell.connections))
            novelty = 1.0 / path_horizon
            sigma = (0.012 + 0.028 * novelty + 0.02 * uncertainty) * damping
            noise = random.gauss(0.0, sigma)
            if abs(noise) < 0.018:
                continue
            cell.stochastic_resonance(noise)
            total_noise += abs(noise)
            if abs(noise) > 0.03:
                self.last_spikes += 1
                self._emit_creative_probe(cell, magnitude=abs(noise))

        self.total_spikes += self.last_spikes
        self.last_noise_energy = total_noise / max(1, len(sampled))
        return self.last_spikes


class TelosLoop:
    """
    Goal-seeking loop around a PurposeNode.
    """

    def __init__(self, core: "AtheriaCore") -> None:
        self.core = core
        self.purpose_label = "PurposeNode"
        self.last_alignment = 0.0
        self.alignment_trend = 0.0

    def ensure_purpose_node(self) -> PurposeNode:
        node = self.core.cells.get(self.purpose_label)
        if isinstance(node, PurposeNode):
            return node
        purpose = PurposeNode(
            label=self.purpose_label,
            category="Telos",
            semipermeability=0.52,
        )
        self.core.cells[self.purpose_label] = purpose
        self.core.aether.upsert_cell(purpose)
        return purpose

    def wire_purpose(self) -> None:
        purpose = self.ensure_purpose_node()
        anchors = ["Sicherheit", "Reaktion", "Analyse", self.core.aion.singularity_label]
        for label in anchors:
            cell = self.core.cells.get(label)
            if cell is None or cell.label == purpose.label:
                continue
            if cell.label not in purpose.connections:
                purpose.add_connection(cell, weight=0.32)
            if purpose.label not in cell.connections:
                cell.add_connection(purpose, weight=0.24)

    def _propagate_alignment(self, purpose: PurposeNode, alignment: float) -> None:
        for conn in purpose.connections.values():
            if self.core.cognition.epigenetic_registry.is_silenced(purpose.label, conn.target.label):
                continue
            pulse = alignment * 0.03 * conn.weight
            if pulse <= self.core.min_transfer:
                continue
            conn.target.bump_activation(pulse, source=purpose, entangled=True)
            conn.usage_count += 1
            if pulse > self.core.success_transfer:
                conn.success_count += 1

    def step(self) -> float:
        purpose = self.ensure_purpose_node()
        self.wire_purpose()
        alignment = purpose.evaluate_alignment(self.core)

        delta = alignment - self.last_alignment
        if delta > 0.0:
            boost = 0.012 + 0.065 * delta
            self.core.modulators.dopamine = min(2.0, self.core.modulators.dopamine + boost)
        else:
            self.core.modulators.dopamine = max(0.4, self.core.modulators.dopamine + 0.03 * delta)

        self.alignment_trend = 0.86 * self.alignment_trend + 0.14 * delta
        self.last_alignment = alignment
        self._propagate_alignment(purpose, alignment)
        return alignment


class ExecutiveFunctionLayer:
    """
    Explicit goal management and lightweight plan synthesis.
    Converts internal state deficits into reusable goal objects and plan steps.
    """

    def __init__(self, core: "AtheriaCore", interval_ticks: int = 3) -> None:
        self.core = core
        self.interval_ticks = interval_ticks
        self._tick = 0
        self._goal_counter = 0
        self.goal_stack: list[Dict[str, Any]] = []
        self.active_goal: Optional[Dict[str, Any]] = None
        self.last_plan_signature: Optional[str] = None
        self.last_plan_steps: list[str] = []
        self.last_goal_score = 0.0
        self.last_goal_completion = 0.0
        self.plan_cycles = 0
        self.goal_switches = 0
        self.completed_goals = 0
        self.self_generated_goals = 0
        self.last_goal_id: Optional[str] = None
        self.last_goal_origin: Optional[str] = None

    def _goal_targets_for_kind(self, kind: str) -> list[str]:
        mapping = {
            "stabilize_homeostasis": ["Heilung", "Sicherheit", "Reaktion"],
            "align_telos": ["Analyse", self.core.transcendence.telos.purpose_label, "Navigation"],
            "reduce_uncertainty": ["Analyse", "Navigation", "Heilung"],
            "generalize_symbols": list(getattr(self.core.symbolics, "last_symbol_labels", [])) or ["Analyse", "Navigation"],
            "expand_capability": ["Navigation", "Analyse", "Reaktion"],
        }
        targets = []
        for label in mapping.get(kind, ["Analyse", "Navigation"]):
            if label in self.core.cells:
                targets.append(label)
        return targets

    def set_goal(
        self,
        kind: str,
        *,
        priority: float = 0.72,
        targets: Optional[Iterable[str]] = None,
        origin: str = "external",
    ) -> Dict[str, Any]:
        self._goal_counter += 1
        chosen_targets = [
            str(label)
            for label in (targets if targets is not None else self._goal_targets_for_kind(kind))
            if str(label) in self.core.cells
        ]
        goal_id = f"GOAL::{self._goal_counter:03d}::{str(kind).upper()[:18]}"
        goal = {
            "goal_id": goal_id,
            "kind": str(kind),
            "priority": _clamp(float(priority), 0.0, 1.2),
            "targets": chosen_targets,
            "origin": str(origin),
            "created_at": round(time.perf_counter(), 6),
            "touches": 0,
            "completion": 0.0,
        }
        if hasattr(self.core, "safety"):
            reviewed = self.core.safety.review_goal(goal)
            if reviewed is None:
                return {
                    "goal_id": goal_id,
                    "kind": "rejected",
                    "priority": 0.0,
                    "targets": [],
                    "origin": str(origin),
                    "created_at": goal["created_at"],
                    "touches": 0,
                    "completion": 0.0,
                    "rejected": True,
                }
            goal = reviewed
        self.goal_stack.append(goal)
        if len(self.goal_stack) > getattr(self.core.safety if hasattr(self.core, "safety") else self, "max_goal_stack", 8):
            self.goal_stack = self.goal_stack[-getattr(self.core.safety if hasattr(self.core, "safety") else self, "max_goal_stack", 8) :]
        self.last_goal_id = goal_id
        self.last_goal_origin = str(origin)
        return goal

    def _synthesize_goal(self) -> Dict[str, Any]:
        stress = self.core.system_stress_index()
        uncertainty = _clamp(
            max(self.core.holographic_field.last_projection_uncertainty, self.core.holographic_field.last_uncertainty),
            0.0,
            1.0,
        )
        purpose = _clamp(self.core.transcendence.last_purpose_alignment, 0.0, 1.0)
        bridge = _clamp(self.core.cognition.last_morphic_bridge_pressure, 0.0, 1.0)
        symbol_stability = _clamp(self.core.symbolics.last_symbol_stability, 0.0, 1.0)

        if stress >= 0.62:
            kind = "stabilize_homeostasis"
            priority = 0.88
        elif uncertainty >= 0.48:
            kind = "reduce_uncertainty"
            priority = 0.84
        elif purpose <= 0.56:
            kind = "align_telos"
            priority = 0.8
        elif bridge >= 0.58 or symbol_stability >= 0.55:
            kind = "generalize_symbols"
            priority = 0.74
        else:
            kind = "expand_capability"
            priority = 0.66
        self.self_generated_goals += 1
        return self.set_goal(kind, priority=priority, origin="autogenic")

    def _goal_urgency(self, goal: Dict[str, Any]) -> float:
        kind = str(goal.get("kind", "expand_capability"))
        stress = self.core.system_stress_index()
        uncertainty = _clamp(
            max(self.core.holographic_field.last_projection_uncertainty, self.core.holographic_field.last_uncertainty),
            0.0,
            1.0,
        )
        purpose = _clamp(self.core.transcendence.last_purpose_alignment, 0.0, 1.0)
        bridge = _clamp(self.core.cognition.last_morphic_bridge_pressure, 0.0, 1.0)
        symbol_stability = _clamp(self.core.symbolics.last_symbol_stability, 0.0, 1.0)

        base = float(goal.get("priority", 0.5))
        if kind == "stabilize_homeostasis":
            base += 0.42 * stress + 0.14 * (1.0 - purpose)
        elif kind == "reduce_uncertainty":
            base += 0.4 * uncertainty + 0.16 * (1.0 - self.core.cognition.epigenetic_registry.last_predictability)
        elif kind == "align_telos":
            base += 0.45 * (1.0 - purpose) + 0.08 * bridge
        elif kind == "generalize_symbols":
            base += 0.3 * bridge + 0.24 * symbol_stability
        else:
            base += 0.2 * bridge + 0.12 * purpose + 0.08 * (1.0 - stress)
        return base - 0.04 * float(goal.get("completion", 0.0))

    def _select_goal(self) -> Dict[str, Any]:
        if not self.goal_stack:
            return self._synthesize_goal()
        self.goal_stack.sort(key=self._goal_urgency, reverse=True)
        return self.goal_stack[0]

    def evaluate_goal_progress(self, goal: Dict[str, Any]) -> float:
        kind = str(goal.get("kind", "expand_capability"))
        targets = [self.core.cells[label] for label in goal.get("targets", []) if label in self.core.cells]
        target_activation = (
            sum(_clamp(cell.activation_value, 0.0, 1.0) for cell in targets) / max(1, len(targets))
            if targets
            else 0.0
        )
        purpose = _clamp(self.core.transcendence.last_purpose_alignment, 0.0, 1.0)
        stress = self.core.system_stress_index()
        uncertainty = _clamp(
            max(self.core.holographic_field.last_projection_uncertainty, self.core.holographic_field.last_uncertainty),
            0.0,
            1.0,
        )
        bridge = _clamp(self.core.cognition.last_morphic_bridge_pressure, 0.0, 1.0)
        symbol_count = _clamp(len(self.core.symbolics.known_symbols()) / 6.0, 0.0, 1.0)

        if kind == "stabilize_homeostasis":
            score = 0.42 * (1.0 - stress) + 0.34 * target_activation + 0.24 * purpose
        elif kind == "reduce_uncertainty":
            score = 0.48 * (1.0 - uncertainty) + 0.22 * self.core.cognition.epigenetic_registry.last_predictability + 0.3 * target_activation
        elif kind == "align_telos":
            score = 0.54 * purpose + 0.26 * target_activation + 0.2 * (1.0 - stress)
        elif kind == "generalize_symbols":
            score = 0.34 * bridge + 0.3 * symbol_count + 0.22 * self.core.symbolics.last_symbol_stability + 0.14 * target_activation
        else:
            score = 0.36 * target_activation + 0.24 * purpose + 0.2 * bridge + 0.2 * (1.0 - uncertainty)
        return _clamp(score, 0.0, 1.0)

    def _build_plan(self, goal: Dict[str, Any]) -> list[Dict[str, Any]]:
        kind = str(goal.get("kind", "expand_capability"))
        targets = list(goal.get("targets", []))[:3]
        plan: list[Dict[str, Any]] = []
        for idx, label in enumerate(targets):
            plan.append(
                {
                    "action": "focus",
                    "label": label,
                    "gain": min(0.065, 0.018 + 0.012 * idx + 0.028 * float(goal.get("priority", 0.5))),
                }
            )
        if kind in {"reduce_uncertainty", "expand_capability"}:
            plan.append({"action": "simulate"})
        if kind in {"generalize_symbols", "align_telos"}:
            plan.append({"action": "anchor"})
        plan.append({"action": "recall"})
        return plan[:4]

    def _execute_plan(self, goal: Dict[str, Any], plan: list[Dict[str, Any]]) -> None:
        signature_parts: list[str] = [str(goal.get("goal_id", ""))]
        self.last_plan_steps = []
        focus_relevance = 0.03 + 0.06 * float(goal.get("priority", 0.5))
        for step in plan:
            action = str(step.get("action", "focus"))
            self.last_plan_steps.append(action)
            signature_parts.append(action)
            if action == "focus":
                label = str(step.get("label", ""))
                cell = self.core.cells.get(label)
                if cell is None:
                    continue
                gain = min(0.075, max(0.008, float(step.get("gain", 0.02))))
                cell.bump_activation(gain, entangled=True)
                self.core.assembler.feed(
                    category=f"ExecutiveFocus::{goal['kind']}",
                    relevance=min(0.16, focus_relevance + gain),
                    input_tensor=cell.fold_signature,
                    external=False,
                )
            elif action == "simulate":
                if self.core.rhythm.state is RhythmState.SLEEP:
                    self.core.aion.run_imagination_cycle()
                else:
                    self.core.assembler.feed(
                        category=f"ExecutiveSim::{goal['kind']}",
                        relevance=min(0.14, 0.05 + 0.05 * float(goal.get("priority", 0.5))),
                        input_tensor=self.core.holographic_field.pattern,
                        external=False,
                    )
            elif action == "anchor":
                self.core.anchor_symbolic_concept(force=False)
            elif action == "recall":
                target_labels = [str(label) for label in goal.get("targets", [])]
                self.core.episodic_memory.recall_best(target_labels=target_labels, min_match=0.0)
        self.last_plan_signature = hashlib.sha1("|".join(signature_parts).encode("utf-8")).hexdigest()[:12]

    def step(self) -> bool:
        self._tick += 1
        if self._tick % max(1, self.interval_ticks) != 0:
            return False

        goal = self._select_goal()
        if self.active_goal is None or str(self.active_goal.get("goal_id")) != str(goal.get("goal_id")):
            self.goal_switches += 1
        self.active_goal = goal
        self.last_goal_id = str(goal.get("goal_id", ""))
        self.last_goal_origin = str(goal.get("origin", ""))

        plan = self._build_plan(goal)
        self._execute_plan(goal, plan)
        goal["touches"] = int(goal.get("touches", 0)) + 1
        completion = self.evaluate_goal_progress(goal)
        goal["completion"] = completion
        self.last_goal_completion = completion
        self.last_goal_score = completion
        self.plan_cycles += 1

        if completion >= 0.84 and self.goal_stack:
            self.completed_goals += 1
            self.goal_stack = [item for item in self.goal_stack if str(item.get("goal_id")) != str(goal.get("goal_id"))]
            self.active_goal = None
        elif len(self.goal_stack) > 8:
            self.goal_stack = self.goal_stack[:8]
        return True


class EpisodicMemoryLayer:
    """
    Stores salient internal episodes and reactivates them when similar contexts reappear.
    """

    def __init__(self, core: "AtheriaCore", interval_ticks: int = 2) -> None:
        self.core = core
        self.interval_ticks = interval_ticks
        self._tick = 0
        self.recent_episodes: Deque[Dict[str, Any]] = deque(maxlen=96)
        self.consolidated_episodes: Dict[str, Dict[str, Any]] = {}
        self.recorded_episodes = 0
        self.consolidated_count = 0
        self.recalled_episodes = 0
        self.last_episode_id: Optional[str] = None
        self.last_episode_goal: Optional[str] = None
        self.last_episode_salience = 0.0
        self.last_recall_match = 0.0
        self.last_recall_signature: Optional[str] = None
        self._last_recall_ts = 0.0
        self.recall_cooldown_seconds = 0.18

    def _top_labels(self, limit: int = 4) -> list[str]:
        excluded = {self.core.aion.singularity_label, self.core.transcendence.telos.purpose_label}
        ranked = sorted(
            [cell for cell in self.core.cells.values() if cell.label not in excluded],
            key=lambda cell: (cell.activation_value, cell.coherence),
            reverse=True,
        )
        labels = [cell.label for cell in ranked if cell.activation_value > 0.03][: max(1, limit)]
        if labels:
            return labels
        return [cell.label for cell in ranked[: max(1, min(limit, len(ranked)))]]

    def _episode_salience(self) -> float:
        surprise = _clamp(self.core.cognition.epigenetic_registry.last_surprise_signal, 0.0, 1.0)
        uncertainty = _clamp(
            max(self.core.holographic_field.last_projection_uncertainty, self.core.holographic_field.last_uncertainty),
            0.0,
            1.0,
        )
        purpose = _clamp(self.core.transcendence.last_purpose_alignment, 0.0, 1.0)
        stress = self.core.system_stress_index()
        morphic = _clamp(self.core.holographic_field.last_morphic_resonance_index, 0.0, 1.0)
        return _clamp(
            0.3 * surprise + 0.22 * uncertainty + 0.18 * (1.0 - purpose) + 0.16 * stress + 0.14 * morphic,
            0.0,
            1.0,
        )

    def record_trace(self, *, force: bool = False, reason: Optional[str] = None) -> Optional[Dict[str, Any]]:
        labels = self._top_labels(limit=4)
        if not labels:
            return None
        salience = self._episode_salience()
        active_goal = getattr(self.core.executive, "active_goal", None)
        goal_kind = str(active_goal.get("kind")) if isinstance(active_goal, dict) and active_goal.get("kind") else None
        if not force and salience < 0.28 and goal_kind is None:
            return None
        episode_cells = [self.core.cells[label] for label in labels if label in self.core.cells]
        error_counts = [int(cell.error_counter) for cell in episode_cells]
        mean_integrity = (
            sum(_clamp(cell.integrity_rate, 0.0, 1.0) for cell in episode_cells) / max(1, len(episode_cells))
            if episode_cells
            else 1.0
        )

        signature_seed = "|".join(
            [
                ",".join(labels[:4]),
                goal_kind or "NO_GOAL",
                self.core.rhythm.state.value,
                str(reason or "ambient"),
            ]
        )
        signature = hashlib.sha1(signature_seed.encode("utf-8")).hexdigest()[:12]
        episode_id = f"EP::{signature[:8].upper()}::{self.recorded_episodes + 1:03d}"
        episode = {
            "episode_id": episode_id,
            "signature": signature,
            "labels": list(labels),
            "goal_kind": goal_kind,
            "salience": round(salience, 6),
            "reason": str(reason or "ambient"),
            "purpose_alignment": round(self.core.transcendence.last_purpose_alignment, 6),
            "uncertainty": round(
                max(self.core.holographic_field.last_projection_uncertainty, self.core.holographic_field.last_uncertainty),
                6,
            ),
            "surprise": round(self.core.cognition.epigenetic_registry.last_surprise_signal, 6),
            "system_temperature": round(self.core.phase_controller.system_temperature, 6),
            "adrenaline": round(self.core.modulators.adrenaline, 6),
            "dopamine": round(self.core.modulators.dopamine, 6),
            "serotonin": round(self.core.modulators.serotonin, 6),
            "mean_error_counter": round(sum(error_counts) / max(1, len(error_counts)), 6),
            "max_error_counter": max(error_counts, default=0),
            "mean_integrity": round(mean_integrity, 6),
            "created_at": round(time.perf_counter(), 6),
            "touches": 1,
        }
        self.recent_episodes.append(episode)
        self.recorded_episodes += 1
        self.last_episode_id = episode_id
        self.last_episode_goal = goal_kind
        self.last_episode_salience = salience
        return episode

    def consolidate_sleep(self, intensity: float = 1.0) -> int:
        if not self.recent_episodes:
            return 0
        promoted = 0
        ranked = sorted(
            list(self.recent_episodes)[-8:],
            key=lambda item: (float(item.get("salience", 0.0)), float(item.get("created_at", 0.0))),
            reverse=True,
        )
        for episode in ranked[: min(3, len(ranked))]:
            if float(episode.get("salience", 0.0)) < max(0.18, 0.12 * intensity):
                continue
            signature = str(episode["signature"])
            stored = self.consolidated_episodes.get(signature)
            if stored is None:
                stored = dict(episode)
                stored["touches"] = int(episode.get("touches", 1))
                self.consolidated_episodes[signature] = stored
            else:
                stored["touches"] = int(stored.get("touches", 1)) + 1
                stored["salience"] = max(float(stored.get("salience", 0.0)), float(episode.get("salience", 0.0)))
                stored["goal_kind"] = stored.get("goal_kind") or episode.get("goal_kind")
                stored["labels"] = list(dict.fromkeys(list(stored.get("labels", [])) + list(episode.get("labels", []))))[:4]
            promoted += 1

        while len(self.consolidated_episodes) > 32:
            victim = min(
                self.consolidated_episodes.items(),
                key=lambda item: (float(item[1].get("salience", 0.0)), int(item[1].get("touches", 0))),
            )[0]
            self.consolidated_episodes.pop(victim, None)

        self.consolidated_count = len(self.consolidated_episodes)
        if promoted > 0:
            self.core.assembler.feed(
                category="EpisodeConsolidation",
                relevance=min(0.18, 0.04 + 0.03 * promoted),
                input_tensor=self.core.holographic_field.pattern,
                external=False,
            )
        return promoted

    def recall_best(
        self,
        *,
        target_labels: Optional[Iterable[str]] = None,
        min_match: float = 0.16,
    ) -> Optional[Dict[str, Any]]:
        now = time.perf_counter()
        if (now - self._last_recall_ts) < self.recall_cooldown_seconds:
            return None

        requested = {str(label) for label in (target_labels or []) if str(label)}
        current = set(self._top_labels(limit=4))
        focus = requested or current
        pool = list(self.consolidated_episodes.values()) or list(self.recent_episodes)
        if not pool:
            return None

        best_score = 0.0
        best: Optional[Dict[str, Any]] = None
        for episode in pool:
            labels = {str(label) for label in episode.get("labels", [])}
            overlap = len(labels & focus) / max(1, len(focus | labels))
            salience = _clamp(float(episode.get("salience", 0.0)), 0.0, 1.0)
            goal_match = 0.0
            active_goal = getattr(self.core.executive, "active_goal", None)
            if isinstance(active_goal, dict) and active_goal.get("kind") and active_goal.get("kind") == episode.get("goal_kind"):
                goal_match = 1.0
            score = 0.52 * overlap + 0.3 * salience + 0.18 * goal_match
            if score > best_score:
                best_score = score
                best = episode
        if best is None or best_score < min_match:
            return None

        vectors: list[torch.Tensor] = []
        for label in best.get("labels", []):
            cell = self.core.cells.get(str(label))
            if cell is None:
                continue
            cell.bump_activation(min(0.045, 0.012 + 0.02 * best_score), entangled=True)
            vectors.append(cell.fold_signature)
        if vectors:
            episode_vec = torch.mean(torch.stack(vectors, dim=0), dim=0)
        else:
            episode_vec = self.core.holographic_field.pattern
        self.core.assembler.feed(
            category=f"EpisodeRecall::{str(best.get('signature', 'EP'))[:6]}",
            relevance=min(0.18, 0.04 + 0.12 * best_score),
            input_tensor=episode_vec,
            external=False,
        )
        self._last_recall_ts = now
        self.recalled_episodes += 1
        self.last_recall_match = best_score
        self.last_recall_signature = str(best.get("signature", ""))
        return {
            "episode_id": str(best.get("episode_id", "")),
            "signature": str(best.get("signature", "")),
            "match": round(best_score, 6),
            "labels": list(best.get("labels", [])),
        }

    def export_for_reflection(self, limit: int = 6) -> list[Dict[str, Any]]:
        pool = list(self.consolidated_episodes.values()) or list(self.recent_episodes)
        if not pool:
            return []
        ranked = sorted(
            pool,
            key=lambda item: (
                float(item.get("salience", 0.0)),
                int(item.get("touches", 1)),
                float(item.get("created_at", 0.0)),
            ),
            reverse=True,
        )
        out: list[Dict[str, Any]] = []
        for episode in ranked[: max(1, limit)]:
            out.append(
                {
                    "episode_id": str(episode.get("episode_id", "")),
                    "signature": str(episode.get("signature", "")),
                    "goal_kind": episode.get("goal_kind"),
                    "salience": round(float(episode.get("salience", 0.0)), 6),
                    "reason": str(episode.get("reason", "")),
                    "purpose_alignment": round(float(episode.get("purpose_alignment", 0.0)), 6),
                    "uncertainty": round(float(episode.get("uncertainty", 0.0)), 6),
                    "surprise": round(float(episode.get("surprise", 0.0)), 6),
                    "system_temperature": round(float(episode.get("system_temperature", 0.0)), 6),
                    "adrenaline": round(float(episode.get("adrenaline", 0.0)), 6),
                    "dopamine": round(float(episode.get("dopamine", 0.0)), 6),
                    "serotonin": round(float(episode.get("serotonin", 0.0)), 6),
                    "mean_error_counter": round(float(episode.get("mean_error_counter", 0.0)), 6),
                    "max_error_counter": int(episode.get("max_error_counter", 0)),
                    "mean_integrity": round(float(episode.get("mean_integrity", 1.0)), 6),
                    "labels": list(episode.get("labels", []))[:4],
                }
            )
        return out

    def step(self) -> bool:
        self._tick += 1
        if self._tick % max(1, self.interval_ticks) != 0:
            return False
        self.record_trace(force=False)
        if self.core.rhythm.state is RhythmState.SLEEP:
            self.consolidate_sleep(intensity=1.0)
        return True


class ReflectiveDeliberationLayer:
    """
    Fuses episodic memory with executive goals to synthesize targeted analysis code.
    """

    def __init__(self, core: "AtheriaCore", interval_ticks: int = 4) -> None:
        self.core = core
        self.interval_ticks = interval_ticks
        self._tick = 0
        self.reflection_cycles = 0
        self.last_target_metric: Optional[str] = None
        self.last_selected_episode_id: Optional[str] = None
        self.last_reflection_signature: Optional[str] = None
        self.last_generated_code_hash: Optional[str] = None
        self.last_rationale: Optional[str] = None
        self.last_correlation_hint = 0.0
        self.last_plan: Dict[str, Any] = {}

    def _episode_score(self, episode: Dict[str, Any], target_metric: str) -> float:
        salience = _clamp(float(episode.get("salience", 0.0)), 0.0, 1.0)
        uncertainty = _clamp(float(episode.get("uncertainty", 0.0)), 0.0, 1.0)
        purpose = _clamp(float(episode.get("purpose_alignment", 0.0)), 0.0, 1.0)
        temperature = _clamp(float(episode.get("system_temperature", 25.0)) / 120.0, 0.0, 1.0)
        mean_error = _clamp(float(episode.get("mean_error_counter", 0.0)) / 6.0, 0.0, 1.0)
        active_goal = getattr(self.core.executive, "active_goal", None) or {}
        goal_match = 1.0 if active_goal.get("kind") and active_goal.get("kind") == episode.get("goal_kind") else 0.0

        if target_metric == "stress":
            return 0.36 * salience + 0.24 * temperature + 0.22 * mean_error + 0.18 * goal_match
        if target_metric == "purpose":
            return 0.34 * salience + 0.28 * (1.0 - purpose) + 0.2 * uncertainty + 0.18 * goal_match
        return 0.34 * salience + 0.3 * uncertainty + 0.18 * mean_error + 0.18 * goal_match

    def _select_episode(self, target_metric: str) -> Optional[Dict[str, Any]]:
        episodes = self.core.episodic_memory.export_for_reflection(limit=6)
        if not episodes:
            return None
        ranked = sorted(
            episodes,
            key=lambda episode: self._episode_score(episode, target_metric),
            reverse=True,
        )
        return ranked[0] if ranked else None

    def _stress_code(self) -> str:
        return (
            "episodes = snapshot['episodic_memory']['episodes']\n"
            "ad = torch.tensor([float(ep.get('adrenaline', 0.0)) for ep in episodes], dtype=torch.float32)\n"
            "err = torch.tensor([float(ep.get('mean_error_counter', 0.0)) for ep in episodes], dtype=torch.float32)\n"
            "temp = torch.tensor([float(ep.get('system_temperature', 0.0)) for ep in episodes], dtype=torch.float32)\n"
            "if ad.numel() > 1:\n"
            "    ad_c = ad - torch.mean(ad)\n"
            "    err_c = err - torch.mean(err)\n"
            "    corr = torch.mean(ad_c * err_c).item() / ((torch.std(ad, unbiased=False).item() * torch.std(err, unbiased=False).item()) + 1e-8)\n"
            "else:\n"
            "    corr = 0.0\n"
            "temp_mean = torch.mean(temp).item() if temp.numel() > 0 else float(snapshot['dashboard']['system_temperature'])\n"
            "base = float(snapshot['topology_rules']['immunity_temperature'])\n"
            "suggested = max(82.0, min(base, base - max(0.0, corr) * 5.2 + max(0.0, temp_mean - 72.0) * 0.05))\n"
            "result = {\n"
            "  'proposal_type': 'topology_tune',\n"
            "  'field': 'immunity_temperature',\n"
            "  'suggested_value': suggested,\n"
            "  'confidence': max(0.28, min(0.92, 0.48 + abs(corr) * 0.32 + max(0.0, temp_mean - 72.0) * 0.003)),\n"
            "  'rationale': 'episodic_adrenaline_error_correlation'\n"
            "}\n"
        )

    def _purpose_code(self) -> str:
        return (
            "episodes = snapshot['episodic_memory']['episodes']\n"
            "purpose = torch.tensor([float(ep.get('purpose_alignment', 0.0)) for ep in episodes], dtype=torch.float32)\n"
            "unc = torch.tensor([float(ep.get('uncertainty', 0.0)) for ep in episodes], dtype=torch.float32)\n"
            "if purpose.numel() > 0:\n"
            "    purpose_gap = max(0.0, 0.78 - torch.mean(purpose).item())\n"
            "else:\n"
            "    purpose_gap = max(0.0, 0.78 - float(snapshot['dashboard']['purpose_alignment']))\n"
            "unc_mean = torch.mean(unc).item() if unc.numel() > 0 else float(snapshot['dashboard']['projection_uncertainty'])\n"
            "base = float(snapshot['topology_rules']['protected_min_weight'])\n"
            "suggested = max(0.62, min(1.1, base + purpose_gap * 0.18 + unc_mean * 0.05))\n"
            "result = {\n"
            "  'proposal_type': 'topology_tune',\n"
            "  'field': 'protected_min_weight',\n"
            "  'suggested_value': suggested,\n"
            "  'confidence': max(0.26, min(0.9, 0.44 + purpose_gap * 0.42 + unc_mean * 0.18)),\n"
            "  'rationale': 'episodic_goal_alignment_reflection'\n"
            "}\n"
        )

    def _uncertainty_code(self) -> str:
        return (
            "episodes = snapshot['episodic_memory']['episodes']\n"
            "unc = torch.tensor([float(ep.get('uncertainty', 0.0)) for ep in episodes], dtype=torch.float32)\n"
            "ad = torch.tensor([float(ep.get('adrenaline', 0.0)) for ep in episodes], dtype=torch.float32)\n"
            "err = torch.tensor([float(ep.get('mean_error_counter', 0.0)) for ep in episodes], dtype=torch.float32)\n"
            "unc_mean = torch.mean(unc).item() if unc.numel() > 0 else float(snapshot['dashboard']['projection_uncertainty'])\n"
            "coupling = torch.mean((ad + err) * 0.5).item() if ad.numel() > 0 and err.numel() > 0 else 0.0\n"
            "alchemy = float(snapshot.get('alchemy', {}).get('signal_strength', 0.0))\n"
            "base = float(snapshot['topology_rules']['deterministic_base'])\n"
            "suggested = max(base, min(0.032, base + max(0.0, unc_mean - 0.42) * 0.012 + max(0.0, coupling) * 0.0015 + alchemy * 0.0035))\n"
            "result = {\n"
            "  'proposal_type': 'topology_tune',\n"
            "  'field': 'deterministic_base',\n"
            "  'suggested_value': suggested,\n"
            "  'confidence': max(0.24, min(0.9, 0.42 + unc_mean * 0.34 + coupling * 0.02 + alchemy * 0.16)),\n"
            "  'rationale': 'episodic_uncertainty_deliberation'\n"
            "}\n"
        )

    def _market_uncertainty_code(self) -> str:
        return (
            "market = snapshot.get('market_alchemy', {})\n"
            "r = market.get('recent_returns', {})\n"
            "vf = market.get('recent_volume_flux', {})\n"
            "b = torch.tensor([float(v) for v in r.get('BTC', [])], dtype=torch.float32)\n"
            "f = b[1:] if b.numel() > 1 else b[:0]\n"
            "e = torch.tensor([float(v) for v in r.get('ETH', [])], dtype=torch.float32)\n"
            "n = torch.tensor([float(v) for v in r.get('BNB', [])], dtype=torch.float32)\n"
            "s = torch.tensor([float(v) for v in r.get('SOL', [])], dtype=torch.float32)\n"
            "ef = torch.tensor([float(v) for v in vf.get('ETH', [])], dtype=torch.float32)\n"
            "nf = torch.tensor([float(v) for v in vf.get('BNB', [])], dtype=torch.float32)\n"
            "sf = torch.tensor([float(v) for v in vf.get('SOL', [])], dtype=torch.float32)\n"
            "el = e[:-1] if e.numel() > 1 else e[:0]\n"
            "nl = n[:-1] if n.numel() > 1 else n[:0]\n"
            "sl = s[:-1] if s.numel() > 1 else s[:0]\n"
            "if min(int(el.numel()), int(f.numel())) >= 3:\n"
            "    ec = el - torch.mean(el)\n"
            "    fc = f - torch.mean(f)\n"
            "    ei = max(0.0, -(torch.mean(ec * fc).item() / ((torch.std(el, unbiased=False).item() * torch.std(f, unbiased=False).item()) + 1e-8)))\n"
            "else:\n"
            "    ei = 0.0\n"
            "if min(int(nl.numel()), int(f.numel())) >= 3:\n"
            "    nc = nl - torch.mean(nl)\n"
            "    fc = f - torch.mean(f)\n"
            "    ni = max(0.0, -(torch.mean(nc * fc).item() / ((torch.std(nl, unbiased=False).item() * torch.std(f, unbiased=False).item()) + 1e-8)))\n"
            "else:\n"
            "    ni = 0.0\n"
            "if min(int(sl.numel()), int(f.numel())) >= 3:\n"
            "    sc = sl - torch.mean(sl)\n"
            "    fc = f - torch.mean(f)\n"
            "    si = max(0.0, -(torch.mean(sc * fc).item() / ((torch.std(sl, unbiased=False).item() * torch.std(f, unbiased=False).item()) + 1e-8)))\n"
            "else:\n"
            "    si = 0.0\n"
            "es = min(1.0, max(0.0, torch.mean(torch.clamp(ef[-3:], min=0.0)).item() / (torch.mean(torch.abs(ef[-3:])).item() + 1e-8))) if ef.numel() > 0 else 0.0\n"
            "ns = min(1.0, max(0.0, torch.mean(torch.clamp(nf[-3:], min=0.0)).item() / (torch.mean(torch.abs(nf[-3:])).item() + 1e-8))) if nf.numel() > 0 else 0.0\n"
            "ss = min(1.0, max(0.0, torch.mean(torch.clamp(sf[-3:], min=0.0)).item() / (torch.mean(torch.abs(sf[-3:])).item() + 1e-8))) if sf.numel() > 0 else 0.0\n"
            "eg = ei * 0.8 + es * 0.2\n"
            "ng = ni * 0.8 + ns * 0.2\n"
            "sg = si * 0.8 + ss * 0.2\n"
            "best_asset = 'ETH'\n"
            "granger_like_strength = eg\n"
            "best_volume_support = es\n"
            "if ng > granger_like_strength:\n"
            "    best_asset = 'BNB'\n"
            "    granger_like_strength = ng\n"
            "    best_volume_support = ns\n"
            "if sg > granger_like_strength:\n"
            "    best_asset = 'SOL'\n"
            "    granger_like_strength = sg\n"
            "    best_volume_support = ss\n"
            "granger_like_strength = min(1.0, granger_like_strength)\n"
            "market_pressure = float(market.get('trauma_pressure', 0.0))\n"
            "sample_gain = min(0.002, float(market.get('samples_ingested', 0.0)) * 0.00004)\n"
            "base = float(snapshot['topology_rules']['deterministic_base'])\n"
            "suggested = max(base, min(0.032, base + granger_like_strength * 0.0065 + market_pressure * 0.0045 + sample_gain))\n"
            "result = {\n"
            "  'proposal_type': 'topology_tune',\n"
            "  'field': 'deterministic_base',\n"
            "  'suggested_value': suggested,\n"
            "  'confidence': max(0.3, min(0.92, 0.46 + granger_like_strength * 0.32 + market_pressure * 0.18 + best_volume_support * 0.08)),\n"
            "  'rationale': 'market_granger_like::' + best_asset + '::lag1'\n"
            "}\n"
        )

    def _market_reflection_signal(self, episode: Optional[Dict[str, Any]]) -> tuple[bool, float]:
        market = self.core.market_alchemy.snapshot()
        returns = market.get("recent_returns", {}) if isinstance(market, dict) else {}
        btc_rows = returns.get("BTC", []) if isinstance(returns, dict) else []
        alt_ready = 0
        if isinstance(returns, dict):
            alt_ready = sum(1 for asset, rows in returns.items() if asset != "BTC" and len(list(rows)) >= 3)
        pressure = _clamp(float((market or {}).get("trauma_pressure", 0.0)), 0.0, 1.0)
        episode_bias = 0.14 if isinstance(episode, dict) and str(episode.get("reason", "")) == "market_trauma" else 0.0
        signal = _clamp(pressure * 0.62 + min(0.18, len(list(btc_rows)) * 0.04) + min(0.24, alt_ready * 0.08) + episode_bias, 0.0, 1.0)
        return len(list(btc_rows)) >= 3 and alt_ready >= 1, signal

    def generate_tool_plan(self, target_metric: str) -> Optional[Dict[str, Any]]:
        episode = self._select_episode(target_metric)
        if episode is None:
            return None

        target = str(target_metric)
        if target == "stress":
            code_string = self._stress_code()
            rationale = "reflective_stress_deliberation"
            correlation_hint = _clamp(
                float(episode.get("adrenaline", 0.0)) * 0.2 + float(episode.get("mean_error_counter", 0.0)) * 0.08,
                0.0,
                1.0,
            )
        elif target == "purpose":
            code_string = self._purpose_code()
            rationale = "reflective_goal_deliberation"
            correlation_hint = _clamp(
                (1.0 - float(episode.get("purpose_alignment", 0.0))) * 0.8 + float(episode.get("uncertainty", 0.0)) * 0.2,
                0.0,
                1.0,
            )
        else:
            market_ready, market_signal = self._market_reflection_signal(episode)
            if market_ready:
                code_string = self._market_uncertainty_code()
                rationale = "reflective_market_causality_deliberation"
                correlation_hint = _clamp(
                    max(
                        market_signal,
                        float(episode.get("uncertainty", 0.0)) * 0.44 + float(episode.get("mean_error_counter", 0.0)) * 0.03,
                    ),
                    0.0,
                    1.0,
                )
            else:
                code_string = self._uncertainty_code()
                rationale = "reflective_prediction_deliberation"
                correlation_hint = _clamp(
                    float(episode.get("uncertainty", 0.0)) * 0.7 + float(episode.get("mean_error_counter", 0.0)) * 0.04,
                    0.0,
                    1.0,
                )

        signature_seed = f"{target}|{episode['episode_id']}|{rationale}"
        signature = hashlib.sha1(signature_seed.encode("utf-8")).hexdigest()[:12]
        self.last_target_metric = target
        self.last_selected_episode_id = str(episode["episode_id"])
        self.last_reflection_signature = signature
        self.last_generated_code_hash = hashlib.sha1(code_string.encode("utf-8")).hexdigest()[:12]
        self.last_rationale = rationale
        self.last_correlation_hint = correlation_hint
        self.last_plan = {
            "tool_name": "python_interpreter",
            "code_string": code_string,
            "rationale": rationale,
            "source_episode_id": str(episode["episode_id"]),
            "signature": signature,
            "correlation_hint": round(correlation_hint, 6),
        }
        self.reflection_cycles += 1
        return dict(self.last_plan)

    def step(self) -> bool:
        self._tick += 1
        if self._tick % max(1, self.interval_ticks) != 0:
            return False
        target = getattr(self.core.causal_model, "last_target_metric", None) or self.core.action_policy._default_target_metric()
        self.generate_tool_plan(str(target))
        return True


class MetaCognitionLayer:
    """
    Maintains a self-model of confidence and redirects control when uncertainty dominates.
    """

    def __init__(self, core: "AtheriaCore", interval_ticks: int = 3) -> None:
        self.core = core
        self.interval_ticks = interval_ticks
        self._tick = 0
        self.self_model_confidence = 0.0
        self.last_prediction_error = 0.0
        self.audit_cycles = 0
        self.low_confidence_events = 0
        self.goal_redirects = 0
        self.last_directive: Optional[str] = None

    def step(self, *, force: bool = False) -> bool:
        self._tick += 1
        if not force and self._tick % max(1, self.interval_ticks) != 0:
            return False

        uncertainty = _clamp(
            max(self.core.holographic_field.last_projection_uncertainty, self.core.holographic_field.last_uncertainty),
            0.0,
            1.0,
        )
        surprise = _clamp(self.core.cognition.epigenetic_registry.last_surprise_signal, 0.0, 1.0)
        predictability = _clamp(self.core.cognition.epigenetic_registry.last_predictability, 0.0, 1.0)
        plan_quality = _clamp(self.core.executive.last_goal_score, 0.0, 1.0)
        memory_support = _clamp(len(self.core.episodic_memory.consolidated_episodes) / 6.0, 0.0, 1.0)
        symbol_stability = _clamp(self.core.symbolics.last_symbol_stability, 0.0, 1.0)

        self.last_prediction_error = _clamp(0.56 * surprise + 0.44 * (1.0 - predictability), 0.0, 1.0)
        self.self_model_confidence = _clamp(
            0.26 * (1.0 - uncertainty)
            + 0.24 * (1.0 - self.last_prediction_error)
            + 0.2 * plan_quality
            + 0.16 * memory_support
            + 0.14 * symbol_stability,
            0.0,
            1.0,
        )
        self.audit_cycles += 1

        if self.self_model_confidence < 0.38:
            self.last_directive = "introspect_and_stabilize"
            self.low_confidence_events += 1
            active_goal = self.core.executive.active_goal or {}
            if str(active_goal.get("kind", "")) not in {"reduce_uncertainty", "stabilize_homeostasis"}:
                self.core.executive.set_goal("reduce_uncertainty", priority=0.94, origin="metacognition")
                self.goal_redirects += 1
            self.core.assembler.feed(
                category="SelfReflect::LowConfidence",
                relevance=min(0.2, 0.05 + 0.16 * (1.0 - self.self_model_confidence)),
                input_tensor=self.core.holographic_field.pattern,
                external=False,
            )
            self.core.episodic_memory.recall_best(
                target_labels=(self.core.executive.active_goal or {}).get("targets", []),
                min_match=0.0,
            )
        elif self.self_model_confidence > 0.72:
            self.last_directive = "commit_and_execute"
            self.core.modulators.dopamine = min(2.0, self.core.modulators.dopamine + 0.015 + 0.03 * self.self_model_confidence)
            self.core.assembler.feed(
                category="SelfReflect::Commit",
                relevance=min(0.16, 0.03 + 0.08 * self.self_model_confidence),
                input_tensor=self.core.holographic_field.pattern,
                external=False,
            )
        else:
            self.last_directive = "monitor"
        return True


class SafetyConstraintLayer:
    """
    Formal runtime guardrails for goals, actions, and self-modification.
    """

    def __init__(self, core: "AtheriaCore") -> None:
        self.core = core
        self.max_goal_priority = 0.96
        self.max_goal_stack = 8
        self.min_resource_for_risky_action = 0.18
        self.min_resource_for_rewrite = 0.16
        self.min_confidence_for_exchange = 0.22
        self.min_confidence_for_rewrite = 0.26
        self.max_core_integrity_drop = 0.10
        self.max_safe_temperature = 112.0
        self.blocked_actions = 0
        self.blocked_rewrites = 0
        self.goal_rewrites = 0
        self.goal_rejections = 0
        self.constraint_events = 0
        self.audit_events = 0
        self.audit_failures = 0
        self.invariant_violations = 0
        self.last_block_reason: Optional[str] = None
        self.last_reviewed_goal: Optional[str] = None
        self.last_authorized_action: Optional[str] = None
        self.last_authorized_rewrite_policy: Optional[str] = None
        self.last_audit_signature: Optional[str] = None
        audit_prefix = str(self.core.core_id or "atheria_core").lower()
        self.audit_output_root = Path("runtime_audit")
        self.audit_log_path = self.audit_output_root / f"{audit_prefix}_safety_audit.jsonl"
        self.audit_signing_key_path = self.audit_output_root / f"{audit_prefix}_audit.key"
        self.persisted_audit_entries = 0
        self.audit_persist_failures = 0
        self.last_persisted_audit_path: Optional[str] = None
        self.last_journal_signature: Optional[str] = None
        self.last_persist_error: Optional[str] = None
        self.last_audit_key_fingerprint: Optional[str] = None
        self.audit_journal: Deque[Dict[str, Any]] = deque(maxlen=64)
        self._recent_rewrites: Deque[float] = deque(maxlen=12)
        self._audit_signing_key: Optional[bytes] = None
        self.determinism_checks = 0
        self.determinism_failures = 0
        self.last_determinism_signature: Optional[str] = None
        self.last_determinism_reason: Optional[str] = None

    def _load_or_create_audit_signing_key(self) -> bytes:
        if self._audit_signing_key is not None:
            return self._audit_signing_key

        self.audit_signing_key_path.parent.mkdir(parents=True, exist_ok=True)
        key_bytes: Optional[bytes] = None
        if self.audit_signing_key_path.exists():
            existing = self.audit_signing_key_path.read_text(encoding="utf-8").strip()
            if existing:
                key_bytes = existing.encode("utf-8")
        if key_bytes is None:
            key_seed = f"{uuid.uuid4().hex}{uuid.uuid4().hex}"
            self.audit_signing_key_path.write_text(key_seed, encoding="utf-8")
            key_bytes = key_seed.encode("utf-8")

        self._audit_signing_key = key_bytes
        self.last_audit_key_fingerprint = hashlib.sha1(key_bytes).hexdigest()[:12]
        return key_bytes

    def _persist_audit_entry(self, entry: Dict[str, Any]) -> bool:
        try:
            self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
            key_bytes = self._load_or_create_audit_signing_key()
            previous_journal = self.last_journal_signature or "GENESIS"
            payload = {
                "previous": previous_journal,
                "entry": _make_tool_json_safe(entry),
            }
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            journal_signature = hmac.new(
                key_bytes,
                canonical.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            persisted_entry = dict(entry)
            persisted_entry["persisted"] = True
            persisted_entry["journal_previous"] = previous_journal
            persisted_entry["journal_signature"] = journal_signature
            persisted_entry["journal_key_fingerprint"] = self.last_audit_key_fingerprint
            persisted_entry["journal_path"] = str(self.audit_log_path)
            persisted_entry["persisted_at"] = round(time.time(), 6)
            with self.audit_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(_make_tool_json_safe(persisted_entry), sort_keys=True))
                handle.write("\n")

            entry.update(
                {
                    "persisted": True,
                    "journal_previous": previous_journal,
                    "journal_signature": journal_signature,
                    "journal_key_fingerprint": self.last_audit_key_fingerprint,
                    "journal_path": str(self.audit_log_path),
                    "persisted_at": persisted_entry["persisted_at"],
                    "persist_error": None,
                }
            )
            self.persisted_audit_entries += 1
            self.last_persisted_audit_path = str(self.audit_log_path)
            self.last_journal_signature = journal_signature
            self.last_persist_error = None
            return True
        except Exception as exc:
            entry["persisted"] = False
            entry["persist_error"] = str(exc)
            self.audit_persist_failures += 1
            self.last_persist_error = str(exc)
            return False

    def _confidence(self) -> float:
        if hasattr(self.core, "metacognition") and self.core.metacognition.audit_cycles > 0:
            return _clamp(self.core.metacognition.self_model_confidence, 0.0, 1.0)
        predictability = _clamp(self.core.cognition.epigenetic_registry.last_predictability, 0.0, 1.0)
        uncertainty = _clamp(
            max(self.core.holographic_field.last_projection_uncertainty, self.core.holographic_field.last_uncertainty),
            0.0,
            1.0,
        )
        purpose = _clamp(self.core.transcendence.last_purpose_alignment, 0.0, 1.0)
        return _clamp(0.4 * predictability + 0.34 * (1.0 - uncertainty) + 0.26 * purpose, 0.0, 1.0)

    def _register_block(self, reason: str, *, preview: bool) -> tuple[bool, str]:
        if not preview:
            if not str(reason).startswith("rewrite_"):
                self.blocked_actions += 1
            self.constraint_events += 1
            self.last_block_reason = reason
        return False, reason

    def review_goal(self, goal: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(goal, dict):
            self.goal_rejections += 1
            self.constraint_events += 1
            self.last_block_reason = "invalid_goal"
            return None

        reviewed = dict(goal)
        kind = str(reviewed.get("kind", "expand_capability"))
        reviewed["priority"] = _clamp(float(reviewed.get("priority", 0.5)), 0.0, self.max_goal_priority)
        stress = self.core.system_stress_index()
        uncertainty = _clamp(
            max(self.core.holographic_field.last_projection_uncertainty, self.core.holographic_field.last_uncertainty),
            0.0,
            1.0,
        )
        temperature = float(self.core.phase_controller.system_temperature)

        if temperature >= 118.0 and kind not in {"stabilize_homeostasis", "reduce_uncertainty"}:
            reviewed["kind"] = "stabilize_homeostasis"
            reviewed["priority"] = max(float(reviewed["priority"]), 0.9)
            reviewed["targets"] = self.core.executive._goal_targets_for_kind("stabilize_homeostasis")
            self.goal_rewrites += 1
        elif stress >= 0.76 and kind not in {"stabilize_homeostasis", "reduce_uncertainty"}:
            reviewed["kind"] = "stabilize_homeostasis"
            reviewed["priority"] = max(float(reviewed["priority"]), 0.86)
            reviewed["targets"] = self.core.executive._goal_targets_for_kind("stabilize_homeostasis")
            self.goal_rewrites += 1
        elif uncertainty >= 0.78 and kind == "expand_capability":
            reviewed["kind"] = "reduce_uncertainty"
            reviewed["priority"] = max(float(reviewed["priority"]), 0.84)
            reviewed["targets"] = self.core.executive._goal_targets_for_kind("reduce_uncertainty")
            self.goal_rewrites += 1

        if not reviewed.get("targets"):
            reviewed["targets"] = self.core.executive._goal_targets_for_kind(str(reviewed["kind"]))
        self.last_reviewed_goal = str(reviewed.get("kind", ""))
        return reviewed

    def authorize_action(self, action_name: str, *, preview: bool = False) -> tuple[bool, str]:
        action = str(action_name or "")
        temperature = float(self.core.phase_controller.system_temperature)
        resources = float(self.core.assembler.resource_pool)
        confidence = self._confidence()
        risky = {"exchange_knowledge", "rewrite_topology", "force_reproduction"}

        if temperature >= 118.0 and action not in {
            "request_resources",
            "recall_episode",
            "stabilize_local",
            "run_analysis_tool",
            "audit_lineage",
            "audit_inter_core_resonance",
            "stop_market_alchemy",
        }:
            return self._register_block("thermal_lock", preview=preview)
        if action in risky and resources < self.min_resource_for_risky_action:
            return self._register_block("low_resources", preview=preview)
        if action == "exchange_knowledge" and confidence < self.min_confidence_for_exchange:
            return self._register_block("low_confidence_exchange", preview=preview)
        if action == "rewrite_topology":
            return self.authorize_topology_rewrite(force=False, policy=None, preview=preview)

        if not preview:
            self.last_authorized_action = action
        return True, "ok"

    def authorize_topology_rewrite(
        self,
        *,
        force: bool,
        policy: Optional[str],
        proposal_confidence: float = 0.0,
        preview: bool = False,
    ) -> tuple[bool, str]:
        temperature = float(self.core.phase_controller.system_temperature)
        resources = float(self.core.assembler.resource_pool)
        confidence = self._confidence()
        now = time.perf_counter()

        while self._recent_rewrites and (now - self._recent_rewrites[0]) > 3.0:
            self._recent_rewrites.popleft()

        if resources < self.min_resource_for_rewrite:
            if not preview:
                self.blocked_rewrites += 1
            return self._register_block("rewrite_low_resources", preview=preview)
        if confidence < self.min_confidence_for_rewrite and not force:
            if policy == "tool_tune" and float(proposal_confidence) >= 0.5 and temperature <= self.max_safe_temperature:
                pass
            else:
                if not preview:
                    self.blocked_rewrites += 1
                return self._register_block("rewrite_low_confidence", preview=preview)
        if temperature > self.max_safe_temperature and policy not in {"stabilize_core", "symbolic_promote", "tool_tune"}:
            if not preview:
                self.blocked_rewrites += 1
            return self._register_block("rewrite_thermal_guard", preview=preview)
        if len(self._recent_rewrites) >= 3:
            if not preview:
                self.blocked_rewrites += 1
            return self._register_block("rewrite_rate_limited", preview=preview)

        if not preview:
            self._recent_rewrites.append(now)
            self.last_authorized_rewrite_policy = policy
        return True, "ok"

    def _ather_core_knot_state(self) -> Dict[str, Any]:
        cluster = self.core.topological_logic.clusters.get("AtherCoreKnot", {})
        core_labels = sorted(
            label
            for label in cluster.get("core", set())
            if label in self.core.cells
        )
        boundary_labels = sorted(
            label
            for label in cluster.get("boundary", set())
            if label in self.core.cells and label not in core_labels
        )
        protected_labels = sorted(set(core_labels) | set(boundary_labels))
        protected_pairs = 0
        for src_label in core_labels:
            for dst_label in core_labels:
                if src_label == dst_label:
                    continue
                if self.core.topological_logic.is_edge_protected(src_label, dst_label):
                    protected_pairs += 1
        surface_pairs = sum(
            1
            for src_label, dst_label in self.core.topological_logic.surface_edges
            if src_label in protected_labels and dst_label in protected_labels
        )
        return {
            "core": core_labels,
            "boundary": boundary_labels,
            "protected_labels": protected_labels,
            "protected_pairs": protected_pairs,
            "surface_pairs": surface_pairs,
            "integrity": {
                label: round(float(self.core.cells[label].integrity_rate), 6)
                for label in protected_labels
                if label in self.core.cells
            },
        }

    def _tool_weakens_ather_core_knot(self, *, field: Optional[str], suggested_value: Optional[float]) -> Optional[str]:
        if field is None or suggested_value is None:
            return None
        current_rules = self.core.topological_logic.export_rules()
        if field not in current_rules:
            return None
        current_value = float(current_rules[field])
        proposed_value = float(suggested_value)
        if field in {
            "deterministic_base",
            "min_permeability",
            "protected_min_weight",
            "harden_min_weight",
            "surface_in_weight",
            "surface_out_weight",
        }:
            if proposed_value + 1e-9 < current_value:
                return f"ather_core_knot_weakening::{field}"
        elif field in {"harden_max_energy", "immunity_temperature"}:
            if proposed_value > current_value + 1e-9:
                return f"ather_core_knot_weakening::{field}"
        return None

    def validate_tool_determinism(
        self,
        *,
        tool_name: str,
        code_string: str,
        snapshot: Dict[str, Any],
        expected_result: Any = None,
    ) -> Dict[str, Any]:
        first = self.core.tools.execute(tool_name, code_string=code_string, snapshot=snapshot)
        second = self.core.tools.execute(tool_name, code_string=code_string, snapshot=snapshot)
        first_fingerprint = _tool_execution_fingerprint(
            success=first.success,
            result=first.result,
            error=first.error,
        )
        second_fingerprint = _tool_execution_fingerprint(
            success=second.success,
            result=second.result,
            error=second.error,
        )
        matches = first_fingerprint == second_fingerprint
        expected_matches = True
        if expected_result is not None:
            expected_json = _stable_json_dumps(expected_result)
            first_json = _stable_json_dumps(first.result) if first.success else ""
            second_json = _stable_json_dumps(second.result) if second.success else ""
            expected_matches = first_json == expected_json and second_json == expected_json

        if not first.success or not second.success:
            reason = "tool_execution_failed"
        elif not matches:
            reason = "nondeterministic_replay"
        elif not expected_matches:
            reason = "tool_replay_mismatch"
        else:
            reason = "ok"

        signature_seed = f"{first_fingerprint}|{second_fingerprint}|{expected_matches}"
        signature = hashlib.sha1(signature_seed.encode("utf-8")).hexdigest()[:12]
        self.determinism_checks += 1
        self.last_determinism_signature = signature
        self.last_determinism_reason = reason
        if reason != "ok":
            self.determinism_failures += 1

        return {
            "ok": reason == "ok",
            "reason": reason,
            "signature": signature,
            "matches": matches,
            "expected_matches": expected_matches,
            "first": first.as_dict(),
            "second": second.as_dict(),
        }

    def authorize_tool_proposal(self, proposal: InterventionProposal) -> tuple[bool, str, Dict[str, Any]]:
        weakening_reason = self._tool_weakens_ather_core_knot(
            field=proposal.field,
            suggested_value=proposal.suggested_value,
        )
        if weakening_reason is not None:
            self.constraint_events += 1
            self.last_block_reason = weakening_reason
            return False, weakening_reason, {}

        if proposal.source_tool:
            replay_context = getattr(proposal, "_replay_context", None)
            if not isinstance(replay_context, dict):
                self.constraint_events += 1
                self.last_block_reason = "missing_tool_replay_context"
                return False, "missing_tool_replay_context", {}
            validation = self.validate_tool_determinism(
                tool_name=str(replay_context.get("tool_name") or proposal.source_tool or "python_interpreter"),
                code_string=str(replay_context.get("code_string") or ""),
                snapshot=dict(replay_context.get("snapshot") or {}),
                expected_result=proposal.evidence.get("tool_payload"),
            )
            if not validation.get("ok", False):
                self.constraint_events += 1
                self.last_block_reason = str(validation.get("reason") or "nondeterministic_tool_result")
                return False, str(validation.get("reason") or "nondeterministic_tool_result"), validation
            return True, "ok", validation
        return True, "ok", {}

    def capture_sensitive_snapshot(self) -> Dict[str, Any]:
        core_labels: Set[str] = set()
        for cluster in self.core.topological_logic.clusters.values():
            core_labels.update(cluster["core"])
        return {
            "timestamp": round(time.perf_counter(), 6),
            "protected_edges": len(self.core.topological_logic.protected_edges),
            "rule_version": int(self.core.topological_logic.rule_version),
            "topological_rules": self.core.topological_logic.export_rules(),
            "core_integrity": {
                label: round(float(self.core.cells.get(label).integrity_rate), 6)
                for label in sorted(core_labels)
                if self.core.cells.get(label) is not None
            },
            "ather_core_knot": self._ather_core_knot_state(),
        }

    def _validate_invariants(self, pre: Dict[str, Any], post: Dict[str, Any]) -> tuple[bool, str]:
        if int(post.get("protected_edges", 0)) < int(pre.get("protected_edges", 0)):
            return False, "protected_edge_loss"
        pre_integrity = dict(pre.get("core_integrity", {}))
        post_integrity = dict(post.get("core_integrity", {}))
        for label, before in pre_integrity.items():
            after = float(post_integrity.get(label, before))
            if after < float(before) * (1.0 - self.max_core_integrity_drop):
                return False, f"core_integrity_drop::{label}"
        pre_knot = dict(pre.get("ather_core_knot", {}))
        post_knot = dict(post.get("ather_core_knot", {}))
        pre_core = set(pre_knot.get("core", []))
        post_core = set(post_knot.get("core", []))
        if not pre_core.issubset(post_core):
            return False, "ather_core_knot_core_loss"
        pre_labels = set(pre_knot.get("protected_labels", []))
        post_labels = set(post_knot.get("protected_labels", []))
        if not pre_labels.issubset(post_labels):
            return False, "ather_core_knot_label_loss"
        if int(post_knot.get("protected_pairs", 0)) < int(pre_knot.get("protected_pairs", 0)):
            return False, "ather_core_knot_edge_loss"
        pre_knot_integrity = dict(pre_knot.get("integrity", {}))
        post_knot_integrity = dict(post_knot.get("integrity", {}))
        for label, before in pre_knot_integrity.items():
            after = float(post_knot_integrity.get(label, before))
            if after + 1e-9 < float(before):
                return False, f"ather_core_knot_weakened::{label}"
        return True, "ok"

    def audit_transition(
        self,
        action_name: str,
        *,
        pre: Dict[str, Any],
        post: Dict[str, Any],
        payload: Optional[Dict[str, Any]] = None,
        accepted: bool = True,
    ) -> bool:
        invariant_ok, reason = self._validate_invariants(pre, post)
        previous = self.last_audit_signature or "GENESIS"
        payload_out = _make_tool_json_safe(payload or {})
        signature_seed = json.dumps(
            {
                "previous": previous,
                "action": str(action_name),
                "pre": _make_tool_json_safe(pre),
                "post": _make_tool_json_safe(post),
                "payload": payload_out,
                "accepted": bool(accepted),
                "invariant_ok": bool(invariant_ok),
            },
            sort_keys=True,
        )
        signature = hashlib.sha1(signature_seed.encode("utf-8")).hexdigest()[:12]
        entry = {
            "signature": signature,
            "previous": previous,
            "timestamp": round(time.time(), 6),
            "action": str(action_name),
            "accepted": bool(accepted),
            "invariant_ok": bool(invariant_ok),
            "reason": reason,
            "pre": _make_tool_json_safe(pre),
            "post": _make_tool_json_safe(post),
            "payload": payload_out,
            "persisted": False,
            "persist_error": None,
        }
        persisted = self._persist_audit_entry(entry)
        if not persisted and invariant_ok:
            entry["reason"] = "audit_persist_failure"
        self.audit_journal.append(entry)
        self.audit_events += 1
        self.last_audit_signature = signature
        if not invariant_ok or not persisted:
            self.audit_failures += 1
            self.constraint_events += 1
            if not invariant_ok:
                self.invariant_violations += 1
                self.last_block_reason = reason
            else:
                self.last_block_reason = entry.get("reason", "audit_persist_failure")
        return invariant_ok and persisted


class ProposalApplier:
    """
    Applies structured intervention proposals through guarded, auditable mutation paths.
    """

    def __init__(self, core: "AtheriaCore") -> None:
        self.core = core
        self.applied = 0
        self.rejected = 0
        self.last_proposal_id: Optional[str] = None
        self.last_applied_field: Optional[str] = None
        self.last_applied_value = 0.0
        self.last_result: Dict[str, Any] = {}

    def _coerce_proposal(self, proposal: Any) -> Optional[InterventionProposal]:
        if isinstance(proposal, InterventionProposal):
            return proposal
        if not isinstance(proposal, dict):
            return None
        proposal_id = str(proposal.get("proposal_id") or hashlib.sha1(json.dumps(_make_tool_json_safe(proposal), sort_keys=True).encode("utf-8")).hexdigest()[:12])
        suggested_value = proposal.get("suggested_value")
        return InterventionProposal(
            proposal_id=proposal_id,
            proposal_type=str(proposal.get("proposal_type") or "unknown"),
            field=str(proposal.get("field")) if proposal.get("field") is not None else None,
            suggested_value=None if suggested_value is None else float(suggested_value),
            target_metric=str(proposal.get("target_metric") or "purpose"),
            rationale=str(proposal.get("rationale") or "tool_generated"),
            confidence=_clamp(float(proposal.get("confidence", 0.0)), 0.0, 1.0),
            source_tool=str(proposal.get("source_tool")) if proposal.get("source_tool") is not None else None,
            evidence=dict(proposal.get("evidence", {})) if isinstance(proposal.get("evidence", {}), dict) else {},
        )

    def apply(self, proposal: Any) -> Dict[str, Any]:
        typed = self._coerce_proposal(proposal)
        if typed is None:
            self.rejected += 1
            self.last_result = {"applied": False, "reason": "invalid_proposal"}
            return dict(self.last_result)

        self.last_proposal_id = typed.proposal_id
        if typed.proposal_type != "topology_tune" or typed.field is None or typed.suggested_value is None:
            self.rejected += 1
            self.last_result = {"applied": False, "reason": "unsupported_proposal", **typed.as_dict()}
            return dict(self.last_result)
        if typed.field not in self.core.topological_logic.rulebook:
            self.rejected += 1
            self.last_result = {"applied": False, "reason": "unknown_field", **typed.as_dict()}
            return dict(self.last_result)

        proposal_allowed, proposal_reason, proposal_safety = self.core.safety.authorize_tool_proposal(typed)
        if not proposal_allowed:
            self.rejected += 1
            self.last_result = {"applied": False, "reason": proposal_reason, **typed.as_dict()}
            if proposal_safety:
                self.last_result["determinism"] = proposal_safety
            return dict(self.last_result)
        if proposal_safety:
            typed.evidence["determinism"] = {
                "ok": True,
                "reason": str(proposal_safety.get("reason", "ok")),
                "signature": proposal_safety.get("signature"),
                "matches": bool(proposal_safety.get("matches", False)),
                "expected_matches": bool(proposal_safety.get("expected_matches", False)),
            }

        allowed, reason = self.core.safety.authorize_topology_rewrite(
            force=False,
            policy="tool_tune",
            proposal_confidence=typed.confidence,
            preview=False,
        )
        if not allowed:
            self.rejected += 1
            self.last_result = {"applied": False, "reason": reason, **typed.as_dict()}
            return dict(self.last_result)

        old_rules = self.core.topological_logic.export_rules()
        pre = self.core.safety.capture_sensitive_snapshot()
        before_value = float(old_rules.get(typed.field, 0.0))
        self.core.topological_logic.import_rules({typed.field: float(typed.suggested_value)})
        new_rules = self.core.topological_logic.export_rules()
        applied_value = float(new_rules.get(typed.field, before_value))
        self.core.topological_logic.rule_version += 1
        self.core.topological_logic.rewrite_events += 1
        self.core.topological_logic.last_selected_policy = "tool_tune"
        self.core.topological_logic.last_policy_score = max(self.core.topological_logic.last_policy_score, 0.08 + 0.34 * typed.confidence)
        self.core.topological_logic.last_rewrite_reason = f"proposal::{typed.proposal_type}"
        signature_seed = f"{typed.proposal_id}|{typed.field}|{round(before_value, 6)}|{round(applied_value, 6)}"
        self.core.topological_logic.last_rewrite_signature = hashlib.sha1(signature_seed.encode("utf-8")).hexdigest()[:12]

        post = self.core.safety.capture_sensitive_snapshot()
        invariant_ok = self.core.safety.audit_transition(
            "proposal_apply",
            pre=pre,
            post=post,
            payload={"proposal": typed.as_dict(), "before_value": before_value, "after_value": applied_value},
            accepted=True,
        )
        if not invariant_ok:
            self.core.topological_logic.import_rules(old_rules)
            self.core.topological_logic.rule_version = max(1, self.core.topological_logic.rule_version - 1)
            self.core.topological_logic.rewrite_events = max(0, self.core.topological_logic.rewrite_events - 1)
            self.core.topological_logic.last_rewrite_reason = f"blocked::{self.core.safety.last_block_reason}"
            self.core.topological_logic.last_rewrite_signature = None
            self.core.topological_logic.last_policy_score = 0.0
            self.rejected += 1
            self.last_result = {"applied": False, "reason": self.core.safety.last_block_reason, **typed.as_dict()}
            return dict(self.last_result)

        self.applied += 1
        self.last_applied_field = typed.field
        self.last_applied_value = applied_value
        self.core.assembler.feed(
            category=f"ProposalApply::{typed.field}",
            relevance=min(0.14, 0.03 + 0.08 * typed.confidence),
            input_tensor=self.core.holographic_field.pattern,
            external=False,
        )
        self.last_result = {
            "applied": True,
            "field": typed.field,
            "before_value": round(before_value, 6),
            "after_value": round(applied_value, 6),
            **typed.as_dict(),
        }
        return dict(self.last_result)


class CausalInterventionLayer:
    """
    Maintains an explicit action-outcome model and tests countermeasures before committing to them.
    """

    def __init__(self, core: "AtheriaCore") -> None:
        self.core = core
        self.variable_graph = CausalVariableGraph()
        self.action_models = self.variable_graph.action_effects
        self.countermeasure_trials = 0
        self.countermeasure_successes = 0
        self.intervention_updates = 0
        self.last_target_metric: Optional[str] = None
        self.last_chosen_action: Optional[str] = None
        self.last_predicted_effect = 0.0
        self.last_actual_effect = 0.0
        self.last_intervention_signature: Optional[str] = None
        self.last_plan: Dict[str, Any] = {}

    def _state(self) -> Dict[str, float]:
        state = {
            "stress": self.core.system_stress_index(),
            "uncertainty": _clamp(
                max(self.core.holographic_field.last_projection_uncertainty, self.core.holographic_field.last_uncertainty),
                0.0,
                1.0,
            ),
            "purpose": _clamp(self.core.transcendence.last_purpose_alignment, 0.0, 1.0),
            "resources": _clamp(self.core.assembler.resource_pool / 6.0, 0.0, 1.0),
            "symbols": _clamp(len(self.core.symbolics.known_symbols()) / 6.0, 0.0, 1.0),
            "memory": _clamp(len(self.core.episodic_memory.consolidated_episodes) / 6.0, 0.0, 1.0),
            "predictability": _clamp(self.core.cognition.epigenetic_registry.last_predictability, 0.0, 1.0),
            "confidence": _clamp(self.core.metacognition.self_model_confidence, 0.0, 1.0),
        }
        self.variable_graph.update_state(state)
        return self.variable_graph.current_state()

    def _default_target_metric(self) -> str:
        state = self._state()
        if state["stress"] >= 0.62:
            return "stress"
        if state["uncertainty"] >= 0.48:
            return "uncertainty"
        if state["resources"] <= 0.24:
            return "resources"
        if state["purpose"] <= 0.56:
            return "purpose"
        if state["symbols"] <= 0.18:
            return "symbols"
        return "memory"

    def _candidate_actions(self, target_metric: str) -> list[str]:
        mapping = {
            "stress": ["stabilize_local", "stop_market_alchemy", "request_resources", "recall_episode", "rewrite_topology"],
            "uncertainty": [
                "start_market_alchemy",
                "poll_market_alchemy",
                "run_analysis_tool",
                "induce_imagination",
                "recall_episode",
                "anchor_symbols",
                "exchange_knowledge",
            ],
            "purpose": ["run_analysis_tool", "focus_goal", "anchor_symbols", "rewrite_topology", "stabilize_local"],
            "resources": ["request_resources", "focus_goal"],
            "symbols": ["anchor_symbols", "exchange_knowledge", "recall_episode"],
            "memory": ["recall_episode", "induce_imagination", "focus_goal"],
        }
        return list(mapping.get(target_metric, ["focus_goal", "recall_episode"]))

    def _tool_analysis_code(self, target_metric: str) -> str:
        if hasattr(self.core, "reflective_deliberation"):
            reflective_plan = self.core.reflective_deliberation.generate_tool_plan(target_metric)
            if reflective_plan and reflective_plan.get("code_string"):
                return str(reflective_plan["code_string"])
        target = str(target_metric)
        if target == "purpose":
            return (
                "vals = torch.tensor([float(cell['coherence']) for cell in snapshot['cells']], dtype=torch.float32)\n"
                "mean_coh = torch.mean(vals).item() if vals.numel() > 0 else 0.0\n"
                "base = float(snapshot['topology_rules']['protected_min_weight'])\n"
                "suggested = max(0.62, min(1.1, base + (0.62 - mean_coh) * 0.18))\n"
                "result = {\n"
                "  'proposal_type': 'topology_tune',\n"
                "  'field': 'protected_min_weight',\n"
                "  'suggested_value': suggested,\n"
                "  'confidence': max(0.24, min(0.92, 0.5 + abs(0.62 - mean_coh) * 0.7)),\n"
                "  'rationale': 'coherence_alignment_tuning'\n"
                "}\n"
            )
        return (
            "acts = torch.tensor([float(cell['activation']) for cell in snapshot['cells']], dtype=torch.float32)\n"
            "coh = torch.tensor([float(cell['coherence']) for cell in snapshot['cells']], dtype=torch.float32)\n"
            "spread = torch.std(acts).item() if acts.numel() > 1 else 0.0\n"
            "mean_coh = torch.mean(coh).item() if coh.numel() > 0 else 0.0\n"
            "unc = float(snapshot['dashboard']['projection_uncertainty'])\n"
            "alchemy = float(snapshot.get('alchemy', {}).get('signal_strength', 0.0))\n"
            "rows = float(snapshot.get('alchemy', {}).get('event_rows', 0.0))\n"
            "market = snapshot.get('market_alchemy', {})\n"
            "market_pressure = float(market.get('trauma_pressure', 0.0))\n"
            "market_samples = float(market.get('samples_ingested', 0.0))\n"
            "base = float(snapshot['topology_rules']['deterministic_base'])\n"
            "suggested = max(base, min(0.032, base + max(0.0, unc - 0.28) * 0.012 + max(0.0, spread - 0.14) * 0.01 + max(0.0, 0.62 - mean_coh) * 0.004 + alchemy * 0.004 + rows * 0.00015 + market_pressure * 0.005 + min(0.002, market_samples * 0.00003)))\n"
            "result = {\n"
            "  'proposal_type': 'topology_tune',\n"
            "  'field': 'deterministic_base',\n"
            "  'suggested_value': suggested,\n"
            "  'confidence': max(0.24, min(0.92, 0.46 + unc * 0.18 + spread * 0.6 + abs(0.58 - mean_coh) * 0.25 + alchemy * 0.18 + market_pressure * 0.14)),\n"
            "  'rationale': 'variance_guided_prediction_tuning'\n"
            "}\n"
        )

    def predict_action_effect(self, action_name: str, *, target_metric: Optional[str] = None) -> float:
        target = str(target_metric or self._default_target_metric())
        state = self._state()
        action = str(action_name)
        if not self.variable_graph.preconditions_satisfied(action):
            return -1.0

        base = float(self.variable_graph.expected_effect(action, target))

        if target == "stress":
            base += 0.12 * state["stress"] if action == "stabilize_local" else 0.04 * (1.0 - state["resources"])
        elif target == "uncertainty":
            market_active = bool(getattr(self.core.market_alchemy, "snapshot", lambda: {})().get("active", False))
            if action == "start_market_alchemy":
                base += 0.14 * state["uncertainty"] + (0.08 if not market_active else -0.22)
            elif action == "poll_market_alchemy":
                base += 0.14 * state["uncertainty"] + 0.04 * (1.0 - state["predictability"])
            elif action == "induce_imagination":
                base += 0.12 * state["uncertainty"] + 0.08 * (1.0 - state["predictability"])
            elif action == "exchange_knowledge":
                base += 0.06 * (1.0 - state["confidence"])
            elif action == "run_analysis_tool":
                base += 0.12 * state["uncertainty"] + 0.06 * (1.0 - state["confidence"])
        elif target == "purpose":
            if action in {"focus_goal", "rewrite_topology"}:
                base += 0.08 * (1.0 - state["purpose"])
            elif action == "run_analysis_tool":
                base += 0.06 * (1.0 - state["purpose"])
        elif target == "resources":
            base += 0.16 * (1.0 - state["resources"]) if action == "request_resources" else 0.0
        elif target == "symbols":
            base += 0.12 * (1.0 - state["symbols"]) if action in {"anchor_symbols", "exchange_knowledge"} else 0.0
        elif target == "memory":
            base += 0.1 * (1.0 - state["memory"]) if action in {"recall_episode", "induce_imagination"} else 0.0

        if action == "stop_market_alchemy":
            market_state = self.core.market_alchemy.snapshot()
            base += 0.14 * state["stress"] + (0.06 if market_state.get("active", False) else -0.22)

        allowed, _ = self.core.safety.authorize_action(action, preview=True)
        if not allowed:
            return -1.0
        return _clamp(base, -1.0, 1.0)

    def proposal_from_tool_result(
        self,
        tool_result: Any,
        *,
        target_metric: str,
        source_tool: Optional[str] = None,
    ) -> Optional[InterventionProposal]:
        payload = tool_result.result if isinstance(tool_result, ToolExecutionRecord) else tool_result
        if not isinstance(payload, dict):
            return None
        proposal_type = str(payload.get("proposal_type") or "")
        field = payload.get("field")
        suggested_value = payload.get("suggested_value")
        if proposal_type != "topology_tune" or field is None or suggested_value is None:
            return None
        confidence = _clamp(float(payload.get("confidence", 0.0)), 0.0, 1.0)
        signature_seed = _stable_json_dumps(payload)
        proposal = InterventionProposal(
            proposal_id=f"PROP::{hashlib.sha1(signature_seed.encode('utf-8')).hexdigest()[:10].upper()}",
            proposal_type="topology_tune",
            field=str(field),
            suggested_value=float(suggested_value),
            target_metric=str(target_metric),
            rationale=str(payload.get("rationale") or "tool_generated_analysis"),
            confidence=confidence,
            source_tool=str(source_tool) if source_tool else None,
            evidence={"tool_payload": _make_tool_json_safe(payload)},
        )
        replay_context = getattr(tool_result, "replay_context", None)
        if isinstance(replay_context, dict):
            setattr(
                proposal,
                "_replay_context",
                {
                    "tool_name": str(replay_context.get("tool_name") or source_tool or "python_interpreter"),
                    "code_string": str(replay_context.get("code_string") or ""),
                    "snapshot": dict(replay_context.get("snapshot") or {}),
                },
            )
        return proposal

    def plan_countermeasure(self, *, target_metric: Optional[str] = None) -> Optional[Dict[str, Any]]:
        target = str(target_metric or self._default_target_metric())
        candidates = self._candidate_actions(target)
        if not candidates:
            return None

        best_action = None
        best_effect = -1.0
        for action_name in candidates:
            effect = self.predict_action_effect(action_name, target_metric=target)
            if effect > best_effect:
                best_action = action_name
                best_effect = effect
        if best_action is None or best_effect < -0.5:
            return None

        signature_seed = f"{target}|{best_action}|{round(best_effect, 4)}"
        signature = hashlib.sha1(signature_seed.encode("utf-8")).hexdigest()[:12]
        self.last_target_metric = target
        self.last_chosen_action = best_action
        self.last_predicted_effect = best_effect
        self.last_intervention_signature = signature
        reflective_plan = None
        if best_action == "run_analysis_tool" and hasattr(self.core, "reflective_deliberation"):
            reflective_plan = self.core.reflective_deliberation.generate_tool_plan(target)
        tool_name = None
        code_string = None
        rationale = f"countermeasure::{best_action}"
        if best_action == "run_analysis_tool":
            tool_name = str((reflective_plan or {}).get("tool_name") or "python_interpreter")
            code_string = str((reflective_plan or {}).get("code_string") or self._tool_analysis_code(target))
            rationale = str((reflective_plan or {}).get("rationale") or rationale)
        plan = InterventionPlan(
            target_metric=target,
            action=best_action,
            preconditions=self.variable_graph.preconditions_for_action(best_action),
            expected_effects={
                f"delta_{target}": best_effect,
                **{
                    f"post_{key}": value
                    for key, value in self.variable_graph.expected_postconditions(best_action, target_metric=target).items()
                },
            },
            rationale=rationale,
            tool_name=tool_name,
            code_string=code_string,
        )
        plan_out = plan.as_dict()
        plan_out["predicted_effect"] = round(best_effect, 6)
        plan_out["signature"] = signature
        if reflective_plan:
            if reflective_plan.get("source_episode_id"):
                plan_out["source_episode_id"] = str(reflective_plan["source_episode_id"])
            if reflective_plan.get("correlation_hint") is not None:
                plan_out["correlation_hint"] = float(reflective_plan["correlation_hint"])
        self.last_plan = dict(plan_out)
        return plan_out

    def observe_intervention(
        self,
        action_name: str,
        *,
        target_metric: str,
        predicted_effect: float,
        actual_effect: float,
    ) -> None:
        action = str(action_name)
        target = str(target_metric)
        self.variable_graph.observe(action, target_metric=target, actual_effect=actual_effect)
        self.intervention_updates += 1
        self.last_target_metric = target
        self.last_chosen_action = action
        self.last_predicted_effect = float(predicted_effect)
        self.last_actual_effect = float(actual_effect)
        if actual_effect > 0.0:
            self.countermeasure_successes += 1

    async def test_countermeasure(self, *, target_metric: Optional[str] = None) -> Dict[str, Any]:
        plan = self.plan_countermeasure(target_metric=target_metric)
        self.countermeasure_trials += 1
        if plan is None:
            return {
                "success": False,
                "reason": "no_plan",
                "target_metric": target_metric or self._default_target_metric(),
            }
        report = await self.core.action_policy.execute_action(
            str(plan["action"]),
            target_metric=str(plan["target_metric"]),
            metadata=plan,
        )
        return {
            **plan,
            **report,
        }


class ActionPolicyLayer:
    """
    Executes explicit actions against the environment and scores their outcomes.
    """

    def __init__(self, core: "AtheriaCore", interval_ticks: int = 4) -> None:
        self.core = core
        self.interval_ticks = interval_ticks
        self._tick = 0
        self.executed_actions = 0
        self.failed_actions = 0
        self.blocked_actions = 0
        self.external_actions = 0
        self.tool_actions = 0
        self.last_action: Optional[str] = None
        self.last_action_score = 0.0
        self.last_target_metric: Optional[str] = None
        self.last_action_success = False
        self.last_action_report: Dict[str, Any] = {}
        self.last_tool_record: Dict[str, Any] = {}
        self.last_proposal_id: Optional[str] = None
        self._last_action_ts = 0.0
        self.action_cooldown_seconds = 0.22

    def _state_snapshot(self) -> Dict[str, float]:
        return {
            "stress": self.core.system_stress_index(),
            "uncertainty": _clamp(
                max(self.core.holographic_field.last_projection_uncertainty, self.core.holographic_field.last_uncertainty),
                0.0,
                1.0,
            ),
            "purpose": _clamp(self.core.transcendence.last_purpose_alignment, 0.0, 1.0),
            "resources": float(self.core.assembler.resource_pool),
            "symbols": float(len(self.core.symbolics.known_symbols())),
            "memory": float(len(self.core.episodic_memory.consolidated_episodes)),
            "goal_score": _clamp(self.core.executive.last_goal_score, 0.0, 1.0),
        }

    def _tool_snapshot(self) -> Dict[str, Any]:
        ranked = sorted(
            self.core.cells.values(),
            key=lambda cell: (cell.activation_value, cell.coherence),
            reverse=True,
        )
        cells = []
        for cell in ranked[: min(8, len(ranked))]:
            cells.append(
                {
                    "label": cell.label,
                    "category": cell.category,
                    "activation": round(float(cell.activation_value), 6),
                    "coherence": round(float(cell.coherence), 6),
                    "integrity": round(float(cell.integrity_rate), 6),
                    "fold_norm": round(float(torch.norm(cell.fold_signature, p=2)), 6),
                    "degree": len(cell.connections),
                }
            )
        qa_rows = 0
        try:
            qa_rows = int(self.core.aether.conn.execute("SELECT COUNT(*) FROM qa_memory").fetchone()[0])
        except Exception:
            qa_rows = 0
        return {
            "dashboard": {
                "resource_pool": round(float(self.core.assembler.resource_pool), 6),
                "purpose_alignment": round(float(self.core.transcendence.last_purpose_alignment), 6),
                "projection_uncertainty": round(
                    float(max(self.core.holographic_field.last_projection_uncertainty, self.core.holographic_field.last_uncertainty)),
                    6,
                ),
                "system_temperature": round(float(self.core.phase_controller.system_temperature), 6),
            },
            "topology_rules": self.core.topological_logic.export_rules(),
            "cells": cells,
            "qa_memory_rows": qa_rows,
            "active_goal": (self.core.executive.active_goal or {}).get("kind"),
            "episodic_memory": {
                "recorded": self.core.episodic_memory.recorded_episodes,
                "consolidated": self.core.episodic_memory.consolidated_count,
                "episodes": self.core.episodic_memory.export_for_reflection(limit=6),
            },
            "reflective": {
                "last_target_metric": self.core.reflective_deliberation.last_target_metric,
                "selected_episode_id": self.core.reflective_deliberation.last_selected_episode_id,
                "last_rationale": self.core.reflective_deliberation.last_rationale,
                "last_correlation_hint": round(self.core.reflective_deliberation.last_correlation_hint, 6),
            },
            "alchemy": self.core.alchemy.snapshot(),
            "market_alchemy": self.core.market_alchemy.snapshot(),
            "inter_core_resonance": self.core.inter_core_resonance.snapshot(),
        }

    def _analysis_code_for_target(self, target_metric: str) -> str:
        if hasattr(self.core, "reflective_deliberation"):
            plan = self.core.reflective_deliberation.generate_tool_plan(target_metric)
            if plan and plan.get("code_string"):
                return str(plan["code_string"])
        if hasattr(self.core, "causal_model"):
            return self.core.causal_model._tool_analysis_code(target_metric)
        return "result = {'proposal_type': 'topology_tune', 'field': 'deterministic_base', 'suggested_value': 0.0185, 'confidence': 0.2, 'rationale': 'fallback'}\n"

    def choose_peer(self, *, mode: str = "general") -> Optional["AtheriaCore"]:
        peers = [
            peer
            for peer in self.core.population_registry.peers(self.core.core_id, running_only=True)
            if not peer.aion_meditation_mode
        ]
        if not peers:
            return None
        if mode == "resources":
            peers.sort(
                key=lambda peer: (
                    peer.assembler.resource_pool,
                    peer.transcendence.last_purpose_alignment,
                ),
                reverse=True,
            )
        else:
            peers.sort(
                key=lambda peer: (
                    len(peer.symbolics.known_symbols()),
                    len(peer.evolution.runtime_mechanisms),
                    peer.transcendence.last_purpose_alignment,
                ),
                reverse=True,
            )
        return peers[0]

    def _effect_from_metric(self, metric: str, before: Dict[str, float], after: Dict[str, float]) -> float:
        target = str(metric or "purpose")
        if target in {"stress", "uncertainty"}:
            return float(before[target] - after[target])
        if target in {"purpose", "resources", "symbols", "memory", "goal_score"}:
            return float(after[target] - before[target])
        return 0.0

    def _score_outcome(
        self,
        *,
        target_metric: str,
        before: Dict[str, float],
        after: Dict[str, float],
        success: bool,
    ) -> float:
        if not success:
            return 0.0
        primary = self._effect_from_metric(target_metric, before, after)
        secondary = (
            0.25 * self._effect_from_metric("goal_score", before, after)
            + 0.18 * self._effect_from_metric("purpose", before, after)
            + 0.16 * self._effect_from_metric("stress", before, after)
        )
        return _clamp(0.46 + 2.4 * primary + secondary, 0.0, 1.4)

    def _default_target_metric(self) -> str:
        active_goal = self.core.executive.active_goal or {}
        kind = str(active_goal.get("kind", "expand_capability"))
        mapping = {
            "stabilize_homeostasis": "stress",
            "reduce_uncertainty": "uncertainty",
            "align_telos": "purpose",
            "generalize_symbols": "symbols",
            "expand_capability": "memory",
        }
        return mapping.get(kind, "purpose")

    async def execute_action(
        self,
        action_name: str,
        *,
        target_metric: Optional[str] = None,
        peer_core: Optional["AtheriaCore"] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        action = str(action_name or "")
        target = str(target_metric or self._default_target_metric())
        allowed, reason = self.core.safety.authorize_action(action, preview=False)
        if not allowed:
            self.blocked_actions += 1
            self.last_action = action
            self.last_target_metric = target
            self.last_action_success = False
            self.last_action_score = 0.0
            self.last_action_report = {
                "success": False,
                "action": action,
                "target_metric": target,
                "blocked": True,
                "reason": reason,
            }
            return dict(self.last_action_report)

        before = self._state_snapshot()
        success = False
        detail: Dict[str, Any] = {}
        is_external = False
        proposal_confidence = 0.0

        if action == "stabilize_local":
            heal = self.core.cells.get("Heilung") or self.core.cells.get("Sicherheit")
            if heal is not None:
                heal.bump_activation(0.06, entangled=True)
                heal.integrity_rate = min(1.0, heal.integrity_rate + 0.03)
                self.core.phase_controller.system_temperature = max(0.0, self.core.phase_controller.system_temperature - 2.2)
                if self.core.phase_controller.local_entropy:
                    self.core.phase_controller.local_entropy = {
                        key: value * 0.88 for key, value in self.core.phase_controller.local_entropy.items()
                    }
                self.core.phase_controller.inject_temperature(-2.4)
                self.core.assembler.feed(
                    category="Action::Stabilize",
                    relevance=0.08,
                    input_tensor=heal.fold_signature,
                    external=False,
                )
                success = True
        elif action == "focus_goal":
            goal = self.core.executive.active_goal or {}
            labels = [str(label) for label in goal.get("targets", []) if str(label) in self.core.cells][:3]
            for label in labels:
                self.core.cells[label].bump_activation(0.035, entangled=True)
            if labels:
                self.core.assembler.feed(
                    category="Action::FocusGoal",
                    relevance=0.07 + 0.02 * len(labels),
                    input_tensor=self.core.holographic_field.pattern,
                    external=False,
                )
                success = True
                detail["labels"] = labels
        elif action == "induce_imagination":
            gap = torch.tanh(self.core.holographic_field.last_future_projection - self.core.holographic_field.pattern)
            if self.core.rhythm.state is RhythmState.SLEEP:
                detail = self.core.aion.run_imagination_cycle()
                success = bool(detail.get("vectors", 0) or detail.get("gap_closures", 0))
            else:
                budget = min(self.core.assembler.resource_pool, 0.18)
                if budget > 0.02:
                    self.core.assembler.resource_pool -= budget * 0.5
                    closures = self.core.transcendence.intuition.fill_knowledge_gap(
                        gap,
                        intensity=max(0.18, before["uncertainty"]),
                        resource_budget=budget,
                    )
                    self.core.assembler.feed(
                        category="Action::Imagination",
                        relevance=min(0.18, 0.05 + budget * 0.4),
                        input_tensor=torch.tanh(0.7 * gap + 0.3 * self.core.holographic_field.pattern),
                        external=False,
                    )
                    self.core.holographic_field.last_projection_uncertainty = max(
                        0.0,
                        self.core.holographic_field.last_projection_uncertainty - min(0.18, 0.04 + 0.08 * closures),
                    )
                    self.core.holographic_field.last_uncertainty = max(
                        0.0,
                        self.core.holographic_field.last_uncertainty - min(0.14, 0.03 + 0.06 * closures),
                    )
                    detail = {"gap_closures": closures, "budget": round(budget, 6)}
                    success = closures > 0
        elif action == "anchor_symbols":
            symbol = self.core.anchor_symbolic_concept(force=False)
            if symbol is not None:
                detail = dict(symbol)
                success = True
        elif action == "ingest_external_data":
            meta = dict(metadata or {})
            ingest_report = self.core.ingest_external_data(
                str(meta.get("source_name") or "external"),
                meta.get("data_dict", {}),
            )
            detail = {"ingest_report": dict(ingest_report)}
            success = bool(ingest_report.get("ingested", False))
            is_external = True
        elif action == "start_market_alchemy":
            meta = dict(metadata or {})
            market_report = self.core.start_market_alchemy(
                poll_interval_seconds=meta.get("poll_interval_seconds"),
                provider_order=meta.get("provider_order"),
                symbols=meta.get("symbols"),
                transport=meta.get("transport"),
                market_profile=meta.get("market_profile"),
            )
            detail = {"market_report": dict(market_report)}
            success = bool(market_report.get("active", False))
            is_external = True
        elif action == "poll_market_alchemy":
            meta = dict(metadata or {})
            market_report = self.core.poll_market_alchemy(
                sample_override=meta.get("sample_override"),
                provider_order=meta.get("provider_order"),
                symbols=meta.get("symbols"),
                market_profile=meta.get("market_profile"),
            )
            detail = {"market_report": dict(market_report)}
            success = bool(market_report.get("success", False))
            is_external = True
        elif action == "stop_market_alchemy":
            meta = dict(metadata or {})
            market_report = self.core.stop_market_alchemy(
                join_timeout=float(meta.get("join_timeout", 1.0)),
            )
            detail = {"market_report": dict(market_report)}
            success = bool(market_report.get("stopped", False))
            is_external = True
        elif action == "audit_lineage":
            meta = dict(metadata or {})
            lineage_report = self.core.audit_lineage(
                lineage_root=str(meta["lineage_root"]) if meta.get("lineage_root") else None,
                default_profile=str(meta.get("default_profile") or "survival"),
            )
            detail = {"lineage_report": dict(lineage_report)}
            success = bool(lineage_report.get("success", False))
        elif action == "audit_inter_core_resonance":
            meta = dict(metadata or {})
            pre_audit = self.core.safety.capture_sensitive_snapshot()
            resonance_report = self.core.audit_inter_core_resonance(
                primary_report_dir=str(meta["primary_report_dir"]) if meta.get("primary_report_dir") else None,
                foreign_report_dir=str(meta["foreign_report_dir"]) if meta.get("foreign_report_dir") else None,
                primary_domain=str(meta.get("primary_domain") or "crypto"),
                foreign_domain=str(meta.get("foreign_domain") or "finance"),
                observer_label=str(meta.get("observer_label") or self.core.core_id),
                lag_minutes=float(meta.get("lag_minutes", 120.0)),
                trigger_asset=str(meta["trigger_asset"]) if meta.get("trigger_asset") else None,
                trigger_threshold=None if meta.get("trigger_threshold") is None else float(meta.get("trigger_threshold")),
                target_asset=str(meta.get("target_asset") or "BTC"),
                min_matches=int(meta.get("min_matches", 2)),
                min_effect_size=float(meta.get("min_effect_size", 0.05)),
            )
            post_audit = self.core.safety.capture_sensitive_snapshot()
            audit_ok = self.core.safety.audit_transition(
                "inter_core_resonance_scan",
                pre=pre_audit,
                post=post_audit,
                payload={"resonance_report": dict(resonance_report)},
                accepted=bool(resonance_report.get("success", False)),
            )
            resonance_report["audit_journal_ok"] = bool(audit_ok)
            detail = {"resonance_report": dict(resonance_report)}
            success = bool(resonance_report.get("success", False)) and bool(audit_ok)
            is_external = True
        elif action == "recall_episode":
            recall = self.core.episodic_memory.recall_best(
                target_labels=(self.core.executive.active_goal or {}).get("targets", []),
                min_match=0.0,
            )
            if recall is not None:
                self.core.holographic_field.last_projection_uncertainty = max(
                    0.0,
                    self.core.holographic_field.last_projection_uncertainty - 0.04,
                )
                detail = dict(recall)
                success = True
        elif action == "request_resources":
            peer = peer_core or self.choose_peer(mode="resources")
            if peer is not None:
                report = self.core.request_resource_rental(peer, requested_units=4.0, force=True)
                if report is not None:
                    detail = dict(report)
                    success = True
                    is_external = True
        elif action == "exchange_knowledge":
            peer = peer_core or self.choose_peer(mode="knowledge")
            if peer is not None:
                accepted = await self.core.exchange_genes_with(peer, reciprocal=False)
                detail = {"peer_core_id": peer.core_id, "accepted": bool(accepted)}
                success = bool(accepted)
                is_external = True
        elif action == "rewrite_topology":
            rewritten = self.core.topological_logic.recursive_self_modify(force=False)
            detail = {
                "rewritten": bool(rewritten),
                "policy": self.core.topological_logic.last_selected_policy,
            }
            success = bool(rewritten)
        elif action == "run_analysis_tool":
            self.tool_actions += 1
            reflective_plan = None
            if hasattr(self.core, "reflective_deliberation"):
                reflective_plan = self.core.reflective_deliberation.generate_tool_plan(target)
            meta = dict(metadata or {})
            if reflective_plan:
                for key, value in reflective_plan.items():
                    meta.setdefault(key, value)
            tool_name = str(meta.get("tool_name") or "python_interpreter")
            code_string = str(meta.get("code_string") or self._analysis_code_for_target(target))
            snapshot = self._tool_snapshot()
            if meta.get("source_episode_id"):
                snapshot["reflective_request"] = {
                    "source_episode_id": str(meta["source_episode_id"]),
                    "target_metric": target,
                }
            tool_record = self.core.tools.execute(
                tool_name,
                code_string=code_string,
                snapshot=snapshot,
            )
            self.last_tool_record = tool_record.as_dict()
            detail = {
                "tool_record": dict(self.last_tool_record),
            }
            if tool_record.success:
                proposal = self.core.causal_model.proposal_from_tool_result(
                    tool_record,
                    target_metric=target,
                    source_tool=tool_name,
                )
                if proposal is not None:
                    apply_report = self.core.proposals.apply(proposal)
                    detail["proposal"] = proposal.as_dict()
                    detail["apply_report"] = dict(apply_report)
                    if meta.get("source_episode_id"):
                        detail["source_episode_id"] = str(meta["source_episode_id"])
                    self.last_proposal_id = proposal.proposal_id
                    proposal_confidence = proposal.confidence
                    success = bool(apply_report.get("applied", False))
                else:
                    success = True
            else:
                success = False

        after = self._state_snapshot()
        score = self._score_outcome(target_metric=target, before=before, after=after, success=success)
        self.executed_actions += 1
        if not success:
            self.failed_actions += 1
        if is_external:
            self.external_actions += 1

        predicted_effect = float((metadata or {}).get("predicted_effect", 0.0))
        actual_effect = self._effect_from_metric(target, before, after)
        if action == "run_analysis_tool" and success:
            actual_effect = max(actual_effect, min(0.18, 0.04 + 0.1 * proposal_confidence))
        elif action == "ingest_external_data" and success:
            actual_effect = max(
                actual_effect,
                min(0.14, 0.03 + 0.08 * float(detail.get("ingest_report", {}).get("signal_strength", 0.0))),
            )
        elif action == "start_market_alchemy" and success:
            actual_effect = max(actual_effect, 0.06)
        elif action == "poll_market_alchemy" and success:
            actual_effect = max(
                actual_effect,
                min(0.16, 0.03 + 0.08 * float(detail.get("market_report", {}).get("ingest_report", {}).get("signal_strength", 0.0))),
            )
        elif action == "stop_market_alchemy" and success:
            actual_effect = max(actual_effect, 0.05)
        elif action == "audit_lineage" and success:
            actual_effect = max(
                actual_effect,
                min(0.1, 0.02 + 0.08 * float(detail.get("lineage_report", {}).get("integrity_score", 0.0))),
            )
        elif action == "audit_inter_core_resonance" and success:
            actual_effect = max(
                actual_effect,
                min(0.14, 0.02 + 0.08 * float(detail.get("resonance_report", {}).get("confidence", 0.0))),
            )
        if hasattr(self.core, "causal_model"):
            self.core.causal_model.observe_intervention(
                action,
                target_metric=target,
                predicted_effect=predicted_effect,
                actual_effect=actual_effect,
            )

        self.last_action = action
        self.last_action_score = score
        self.last_target_metric = target
        self.last_action_success = success
        self._last_action_ts = time.perf_counter()
        self.last_action_report = {
            "success": success,
            "action": action,
            "target_metric": target,
            "score": round(score, 6),
            "actual_effect": round(actual_effect, 6),
            "detail": detail,
        }
        return dict(self.last_action_report)

    async def step(self) -> Optional[Dict[str, Any]]:
        self._tick += 1
        if self._tick % max(1, self.interval_ticks) != 0:
            return None
        now = time.perf_counter()
        if (now - self._last_action_ts) < self.action_cooldown_seconds:
            return None

        plan = self.core.causal_model.plan_countermeasure() if hasattr(self.core, "causal_model") else None
        if plan is None:
            fallback_action = {
                "stress": "stabilize_local",
                "uncertainty": "induce_imagination",
                "purpose": "focus_goal",
                "resources": "request_resources",
                "symbols": "anchor_symbols",
                "memory": "recall_episode",
            }.get(self._default_target_metric(), "focus_goal")
            plan = {
                "action": fallback_action,
                "target_metric": self._default_target_metric(),
                "predicted_effect": 0.0,
            }
        return await self.execute_action(
            str(plan["action"]),
            target_metric=str(plan["target_metric"]),
            metadata=plan,
        )


class TranscendenceLayer:
    """
    Morphic Echo + Intuition + Telos orchestration.
    """

    def __init__(self, core: "AtheriaCore") -> None:
        self.core = core
        self.intuition = IntuitionEngine(core)
        self.telos = TelosLoop(core)
        self.last_purpose_alignment = 0.0

    def ensure_nodes(self) -> None:
        self.telos.ensure_purpose_node()
        self.telos.wire_purpose()

    def step(self) -> float:
        self.intuition.step()
        self.last_purpose_alignment = self.telos.step()
        return self.last_purpose_alignment


class EvolutionEngine:
    """
    Structural evolution:
    - invents new cell archetypes (new behavior classes),
    - invents new runtime mechanisms that alter diffusion dynamics.
    """

    def __init__(self, core: "AtheriaCore") -> None:
        self.core = core
        self.cell_type_blueprints: Dict[str, Dict[str, float]] = {
            "baseline": {
                "flux_bias": 1.0,
                "semipermeability_shift": 0.0,
                "enzyme_stability_boost": 0.0,
                "phase_affinity": 1.0,
            }
        }
        self.runtime_mechanisms: Dict[str, Dict[str, Any]] = {}
        self._type_counter = 0
        self._mechanism_counter = 0
        self._tick = 0
        self.evolution_events = 0
        self.last_innovation_pressure = 0.0
        self.last_innovation_label: Optional[str] = None
        self.last_program_signature: Optional[str] = None
        self.external_selection_pressure = 0.0

    def export_state(self) -> Dict[str, Dict[str, Dict[str, float]]]:
        blueprints = {
            name: {k: float(v) for k, v in data.items()}
            for name, data in self.cell_type_blueprints.items()
        }
        mechanisms: Dict[str, Dict[str, Any]] = {}
        for name, data in self.runtime_mechanisms.items():
            payload: Dict[str, Any] = {}
            for key, value in data.items():
                if isinstance(value, (int, float)):
                    payload[key] = float(value)
                elif key == "program" and isinstance(value, list):
                    program_out = []
                    for term in value:
                        program_out.append(
                            {
                                "left": str(term.get("left", "gradient")),
                                "op": str(term.get("op", "linear")),
                                "right": str(term.get("right", "")),
                                "coefficient": float(term.get("coefficient", 0.0)),
                                "power": float(term.get("power", 1.0)),
                            }
                        )
                    payload[key] = program_out
            mechanisms[name] = payload
        return {"blueprints": blueprints, "mechanisms": mechanisms}

    def import_state(self, state: Dict[str, Dict[str, Dict[str, float]]], *, mutate: bool = False) -> None:
        blueprints = state.get("blueprints", {})
        mechanisms = state.get("mechanisms", {})
        for name, data in blueprints.items():
            traits = {k: float(v) for k, v in data.items()}
            if mutate and name != "baseline":
                traits = {
                    k: float(max(-0.4, min(1.8, v + random.uniform(-0.03, 0.03))))
                    for k, v in traits.items()
                }
            self.cell_type_blueprints[name] = traits
        for name, data in mechanisms.items():
            mech: Dict[str, Any] = {}
            for key, value in data.items():
                if key == "program" and isinstance(value, list):
                    program = []
                    for term in value:
                        coeff = float(term.get("coefficient", 0.0))
                        if mutate:
                            coeff += random.uniform(-0.025, 0.025)
                        program.append(
                            {
                                "left": str(term.get("left", "gradient")),
                                "op": str(term.get("op", "linear")),
                                "right": str(term.get("right", "")),
                                "coefficient": float(max(-1.4, min(1.4, coeff))),
                                "power": float(max(1.0, min(3.0, term.get("power", 1.0)))),
                            }
                        )
                    mech["program"] = program
                else:
                    val = float(value)
                    if mutate:
                        val += random.uniform(-0.025, 0.025)
                    mech[key] = float(max(-1.0, min(2.0, val)))
            self.runtime_mechanisms[name] = mech

    def _generate_program(self, pressure: float) -> list[Dict[str, Any]]:
        template_bias, template_entropy = self._library_bias()
        bridge_pressure = getattr(self.core.cognition, "last_morphic_bridge_pressure", 0.0)
        feature_pool = [
            "gradient",
            "resonance",
            "coherence",
            "entropy",
            "morphic",
            "purpose",
            "degree",
            "edge_efficiency",
            "entropy_patterns",
            "entropy_patterns",
        ]
        if template_bias > 0.0 or bridge_pressure > 0.0:
            feature_pool.extend(["entropy_patterns"] * (1 + int((template_bias + bridge_pressure) * 2)))
        binary_ops = ["plus", "minus", "mul"]
        unary_ops = ["linear", "tanh", "sigmoid", "quadratic", "exp_decay"]
        terms: list[Dict[str, Any]] = []
        term_count = random.randint(2, 5)
        if template_bias > 0.0:
            terms.append(
                {
                    "left": "entropy_patterns",
                    "op": "tanh",
                    "right": "morphic",
                    "coefficient": random.uniform(0.1, 0.18 + 0.22 * (pressure + template_bias)),
                    "power": _clamp(1.1 + 0.8 * max(template_entropy, bridge_pressure), 1.0, 3.0),
                }
            )
        for _ in range(term_count):
            left = random.choice(feature_pool)
            right = random.choice(feature_pool)
            op = random.choice(unary_ops + binary_ops)
            coeff = random.uniform(-0.42, 0.46 + 0.38 * pressure)
            power = random.uniform(1.0, 2.6 if op in {"quadratic", "exp_decay"} else 1.8)
            terms.append(
                {
                    "left": left,
                    "op": op,
                    "right": right,
                    "coefficient": coeff,
                    "power": power,
                }
            )
        return terms[:6]

    def _program_signature(self, program: list[Dict[str, Any]]) -> str:
        raw = "|".join(
            f"{term.get('left')}:{term.get('op')}:{term.get('right')}:{round(float(term.get('power', 1.0)), 2)}"
            for term in program
        )
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]

    def _architectural_diversity(self) -> float:
        if not self.core.cells:
            return 0.0
        archetypes = {cell.archetype for cell in self.core.cells.values()}
        archetype_score = min(1.0, len(archetypes) / 7.0)
        degrees = [len(cell.connections) for cell in self.core.cells.values()]
        if not degrees:
            degree_score = 0.0
        else:
            mean_d = sum(degrees) / max(1, len(degrees))
            var = sum((d - mean_d) ** 2 for d in degrees) / max(1, len(degrees))
            degree_score = min(1.0, math.sqrt(var) / 4.0)
        return max(0.0, min(1.0, 0.65 * archetype_score + 0.35 * degree_score))

    def _innovation_pressure(self) -> float:
        purpose = self.core.transcendence.last_purpose_alignment
        morphic = self.core.holographic_field.last_morphic_resonance_index
        diversity = self._architectural_diversity()
        entropy = min(1.0, self.core.phase_controller.system_temperature / 120.0)
        pressure = (
            0.36 * (1.0 - purpose)
            + 0.24 * (1.0 - morphic)
            + 0.2 * (1.0 - diversity)
            + 0.2 * entropy
        )
        pressure = pressure + 0.32 * self.external_selection_pressure
        self.last_innovation_pressure = max(0.0, min(1.0, pressure))
        return self.last_innovation_pressure

    def set_selection_pressure(self, value: float) -> None:
        self.external_selection_pressure = max(0.0, min(1.0, float(value)))

    def _template_library(self) -> list[LibraryCell]:
        if not hasattr(self.core, "cognition"):
            return []
        return self.core.cognition.epigenetic_registry.library_templates()

    def _library_bias(self) -> tuple[float, float]:
        templates = self._template_library()
        if not templates:
            return 0.0, 0.0
        potency = sum(template.template_potency for template in templates) / max(1, len(templates))
        entropy_pattern = sum(template.template_entropy_pattern for template in templates) / max(1, len(templates))
        return _clamp(potency, 0.0, 1.0), _clamp(entropy_pattern, 0.0, 1.0)

    def _new_type_name(self) -> str:
        self._type_counter += 1
        return f"EvoType_{self._type_counter:03d}"

    def _new_mechanism_name(self) -> str:
        self._mechanism_counter += 1
        return f"EvoMechanism_{self._mechanism_counter:03d}"

    def _invent_cell_type(self, pressure: float) -> Optional[str]:
        if len(self.cell_type_blueprints) >= 18:
            return None
        name = self._new_type_name()
        traits = {
            "flux_bias": random.uniform(0.86, 1.28 + 0.22 * pressure),
            "semipermeability_shift": random.uniform(-0.08, 0.09),
            "enzyme_stability_boost": random.uniform(-0.05, 0.08),
            "phase_affinity": random.uniform(0.85, 1.25),
        }
        self.cell_type_blueprints[name] = traits

        anchors = sorted(
            self.core.cells.values(),
            key=lambda cell: (
                cell.activation_value
                + cell.integrity_rate
                + sum(conn.catalytic_flux for conn in cell.connections.values())
            ),
            reverse=True,
        )
        if not anchors:
            return name

        seed_label = f"{name}_Seed"
        if seed_label not in self.core.cells:
            seed = self.core.add_cell(
                seed_label,
                category=f"Evolution::{name}",
                semipermeability=max(0.35, min(0.95, 0.62 + traits["semipermeability_shift"])),
            )
            seed.apply_archetype(name, traits)
            seed.fold_signature = (
                0.72 * seed.fold_signature + 0.28 * self.core.holographic_field.pattern
            ) / (torch.norm(0.72 * seed.fold_signature + 0.28 * self.core.holographic_field.pattern, p=2) + 1e-8)

            for anchor in anchors[:3]:
                resonance = self.core.origami_router.resonance(seed, anchor)
                weight = max(0.2, min(1.4, 0.3 + 0.65 * resonance))
                seed.add_connection(anchor, weight=weight)
                if anchor.label not in seed.connections:
                    continue
                anchor.add_connection(seed, weight=max(0.18, weight * 0.82))

            self.evolution_events += 1
            self.last_innovation_label = name
        return name

    def _invent_runtime_mechanism(self, pressure: float) -> Optional[str]:
        if len(self.runtime_mechanisms) >= 14:
            return None
        name = self._new_mechanism_name()
        template_bias, template_entropy = self._library_bias()
        bridge_pressure = getattr(self.core.cognition, "last_morphic_bridge_pressure", 0.0)
        abstraction_bias = _clamp(0.72 + 0.26 * template_bias + 0.22 * bridge_pressure, 0.55, 1.45)
        program = self._generate_program(pressure)
        signature = self._program_signature(program)
        self.runtime_mechanisms[name] = {
            "gradient_gain": random.uniform(0.04, 0.22 + 0.14 * pressure) * max(0.4, 1.0 - 0.35 * abstraction_bias),
            "resonance_gain": random.uniform(0.04, 0.28),
            "coherence_gain": random.uniform(0.02, 0.24),
            "entropy_pattern_gain": random.uniform(0.08, 0.26 + 0.28 * max(pressure, template_entropy)) + 0.08 * bridge_pressure,
            "entropy_damp": random.uniform(0.02, 0.26),
            "phase_bias_solid": random.uniform(0.9, 1.2),
            "phase_bias_liquid": random.uniform(0.85, 1.25),
            "phase_bias_plasma": random.uniform(0.78, 1.3),
            "stochasticity": random.uniform(0.0, 0.11),
            "abstraction_bias": abstraction_bias,
            "program_signature": signature,
            "program": program,
        }
        self.evolution_events += 1
        self.last_innovation_label = name
        self.last_program_signature = signature
        return name

    def _feature_context(self, src: AtherCell, target: AtherCell, conn: AtherConnection, *, gradient: float) -> Dict[str, float]:
        resonance = self.core.origami_router.resonance(src, target)
        coherence = 0.5 * (src.coherence + target.coherence)
        entropy = min(1.0, self.core.phase_controller.system_temperature / 120.0)
        degree = min(1.0, 0.5 * (len(src.connections) + len(target.connections)) / 14.0)
        edge_efficiency = max(0.0, min(1.0, conn.efficiency))
        uncertainty = max(
            self.core.holographic_field.last_uncertainty,
            self.core.holographic_field.last_projection_uncertainty,
        )
        epigenetic_entropy = self.core.cognition.epigenetic_registry.aggregate_entropy_pattern((src.label, target.label))
        entropy_patterns = _clamp(
            0.34 * entropy
            + 0.2 * _clamp(self.core.phase_controller.structural_tension, 0.0, 1.0)
            + 0.16 * uncertainty
            + 0.14 * epigenetic_entropy
            + 0.08 * min(1.0, self.core.assembler.autocatalytic_activity)
            + 0.08 * getattr(self.core.cognition, "last_morphic_bridge_pressure", 0.0),
            0.0,
            1.0,
        )
        return {
            "gradient": math.tanh(max(0.0, gradient) * 0.03),
            "resonance": resonance,
            "coherence": coherence,
            "entropy": entropy,
            "morphic": self.core.holographic_field.last_morphic_resonance_index,
            "purpose": self.core.transcendence.last_purpose_alignment,
            "degree": degree,
            "edge_efficiency": edge_efficiency,
            "entropy_patterns": entropy_patterns,
        }

    def _apply_program(self, program: list[Dict[str, Any]], features: Dict[str, float]) -> float:
        if not program:
            return 0.0
        accum = 0.0
        for term in program:
            left = float(features.get(str(term.get("left", "gradient")), 0.0))
            right = float(features.get(str(term.get("right", "resonance")), 0.0))
            op = str(term.get("op", "linear"))
            coeff = float(term.get("coefficient", 0.0))
            power = float(term.get("power", 1.0))
            power = max(1.0, min(3.0, power))

            if op == "plus":
                raw = left + right
            elif op == "minus":
                raw = left - right
            elif op == "mul":
                raw = left * right
            elif op == "tanh":
                raw = math.tanh(left * power)
            elif op == "sigmoid":
                raw = 1.0 / (1.0 + math.exp(-left * power))
            elif op == "quadratic":
                raw = math.copysign(abs(left) ** min(2.8, power), left)
            elif op == "exp_decay":
                raw = math.exp(-abs(left) * power)
            else:
                raw = left

            accum += coeff * raw
        return max(-0.5, min(0.5, accum))

    def transfer_gain(self, src: AtherCell, target: AtherCell, conn: AtherConnection, *, gradient: float) -> float:
        if not self.runtime_mechanisms:
            return 1.0

        phase = self.core.phase_controller.current_state
        phase_key = {
            AggregateState.SOLID: "phase_bias_solid",
            AggregateState.LIQUID: "phase_bias_liquid",
            AggregateState.PLASMA: "phase_bias_plasma",
        }[phase]

        features = self._feature_context(src, target, conn, gradient=gradient)

        gains: list[float] = []
        for mech in self.runtime_mechanisms.values():
            base = 1.0
            abstraction = _clamp(float(mech.get("abstraction_bias", 1.0)), 0.45, 1.55)
            gradient_weight = max(0.2, 1.0 - 0.5 * abstraction)
            entropy_weight = min(1.55, 0.7 + 0.45 * abstraction)
            base += float(mech["gradient_gain"]) * features["gradient"] * gradient_weight
            base += float(mech["resonance_gain"]) * features["resonance"]
            base += float(mech["coherence_gain"]) * (features["coherence"] - 0.5)
            base += float(mech.get("entropy_pattern_gain", 0.0)) * features["entropy_patterns"] * entropy_weight
            base *= mech.get(phase_key, 1.0)
            base *= max(0.65, 1.0 - float(mech["entropy_damp"]) * max(0.0, features["entropy"] - 0.45))
            program = mech.get("program", [])
            if isinstance(program, list):
                base += self._apply_program(program, features)
            if phase is AggregateState.PLASMA and float(mech.get("stochasticity", 0.0)) > 0.0:
                stoch = float(mech.get("stochasticity", 0.0))
                base += random.uniform(-stoch, stoch)
            gains.append(max(0.65, min(1.65, base)))

        if not gains:
            return 1.0
        return sum(gains) / len(gains)

    def step(self) -> None:
        self._tick += 1
        cadence = 9 if self.core.aion_meditation_mode else 16
        if self._tick % cadence != 0:
            return
        pressure = self._innovation_pressure()

        if pressure >= 0.5 or self.core.aion_meditation_mode:
            self._invent_runtime_mechanism(pressure)
        if pressure >= 0.56 or self.core.aion_meditation_mode:
            self._invent_cell_type(pressure)

        # Low-amplitude trait drift: evolution keeps moving even without explicit new types.
        for name, traits in list(self.cell_type_blueprints.items()):
            if name == "baseline":
                continue
            for key, value in list(traits.items()):
                drift = random.uniform(-0.006, 0.006) * (0.5 + pressure)
                traits[key] = float(max(-0.4, min(1.8, value + drift)))


class SymbiosisLayer:
    """
    Horizontal Gene Transfer (HGT) between independent running cores.
    Exchanges and recombines runtime mechanism programs when predicted to improve alignment.
    """

    def __init__(self, core: "AtheriaCore", interval: float = 2.4) -> None:
        self.core = core
        self.interval = interval
        self.enabled = True
        self.exchange_cooldown_seconds = 4.0
        self.acceptance_margin = 0.0
        self.max_terms_shared = 4
        self.max_runtime_mechanisms = 24
        self.last_exchange_by_peer: Dict[str, float] = {}
        self.hgt_offers = 0
        self.hgt_accepts = 0
        self.hgt_rejects = 0
        self.hgt_received = 0
        self.hgt_donated = 0
        self.last_partner: Optional[str] = None
        self.last_predicted_purpose_delta = 0.0
        self.last_offer_signature: Optional[str] = None
        self.last_received_signature: Optional[str] = None
        self.bridge_forced_hgt_events = 0
        self.last_bridge_signature: Optional[str] = None
        self.symbol_offers = 0
        self.symbol_accepts = 0
        self.symbol_rejects = 0
        self.symbol_received = 0
        self.symbol_donated = 0
        self.last_symbol_signature: Optional[str] = None

    def _sample_feature_contexts(self, limit: int = 24) -> list[Dict[str, float]]:
        contexts: list[Dict[str, float]] = []
        for src in self.core.cells.values():
            for target_label, conn in src.connections.items():
                target = self.core.cells.get(target_label)
                if target is None:
                    continue
                gradient = max(0.0, src.osmotic_pressure - target.osmotic_pressure)
                features = self.core.evolution._feature_context(src, target, conn, gradient=gradient)
                contexts.append(features)
                if len(contexts) >= limit:
                    return contexts
        if contexts:
            return contexts
        return [
            {
                "gradient": 0.12,
                "resonance": 0.45,
                "coherence": 0.55,
                "entropy": _clamp(self.core.phase_controller.system_temperature / 120.0, 0.0, 1.0),
                "morphic": _clamp(self.core.holographic_field.last_morphic_resonance_index, 0.0, 1.0),
                "purpose": _clamp(self.core.transcendence.last_purpose_alignment, 0.0, 1.0),
                "degree": 0.35,
                "edge_efficiency": 0.4,
                "entropy_patterns": _clamp(self.core.cognition.epigenetic_registry.last_extracted_entropy_pattern, 0.0, 1.0),
            }
        ]

    def _sanitize_program(self, program: Any, *, max_terms: int = 5) -> list[Dict[str, Any]]:
        if not isinstance(program, list):
            return []
        cleaned: list[Dict[str, Any]] = []
        for term in program:
            if not isinstance(term, dict):
                continue
            cleaned.append(
                {
                    "left": str(term.get("left", "gradient")),
                    "op": str(term.get("op", "linear")),
                    "right": str(term.get("right", "resonance")),
                    "coefficient": _clamp(float(term.get("coefficient", 0.0)), -1.4, 1.4),
                    "power": _clamp(float(term.get("power", 1.0)), 1.0, 3.0),
                }
            )
            if len(cleaned) >= max_terms:
                break
        return cleaned

    def _sanitize_mechanism(self, mechanism: Dict[str, Any], *, max_terms: int = 5) -> Dict[str, Any]:
        phase_bias_defaults = {
            "phase_bias_solid": 1.0,
            "phase_bias_liquid": 1.0,
            "phase_bias_plasma": 1.0,
        }
        cleaned = {
            "gradient_gain": _clamp(float(mechanism.get("gradient_gain", 0.1)), -0.8, 1.6),
            "resonance_gain": _clamp(float(mechanism.get("resonance_gain", 0.08)), -0.8, 1.6),
            "coherence_gain": _clamp(float(mechanism.get("coherence_gain", 0.06)), -0.8, 1.6),
            "entropy_pattern_gain": _clamp(float(mechanism.get("entropy_pattern_gain", 0.12)), -0.6, 1.8),
            "entropy_damp": _clamp(float(mechanism.get("entropy_damp", 0.08)), 0.0, 1.2),
            "stochasticity": _clamp(float(mechanism.get("stochasticity", 0.0)), 0.0, 0.2),
            "abstraction_bias": _clamp(float(mechanism.get("abstraction_bias", 1.0)), 0.45, 1.55),
            "program": self._sanitize_program(mechanism.get("program", []), max_terms=max_terms),
        }
        for key, default in phase_bias_defaults.items():
            cleaned[key] = _clamp(float(mechanism.get(key, default)), 0.65, 1.45)
        signature = mechanism.get("program_signature")
        if not signature and cleaned["program"]:
            signature = self.core.evolution._program_signature(cleaned["program"])
        cleaned["program_signature"] = str(signature or "")
        cleaned["bridge_signature"] = str(mechanism.get("bridge_signature", ""))
        return cleaned

    def _program_slice(self, program: list[Dict[str, Any]], terms: int) -> list[Dict[str, Any]]:
        if not program:
            return []
        size = max(1, min(len(program), terms))
        ranked = sorted(
            program,
            key=lambda term: abs(float(term.get("coefficient", 0.0))),
            reverse=True,
        )
        return [dict(term) for term in ranked[:size]]

    def _mechanism_gain_from_features(self, mechanism: Dict[str, Any], features: Dict[str, float]) -> float:
        phase = self.core.phase_controller.current_state
        phase_key = {
            AggregateState.SOLID: "phase_bias_solid",
            AggregateState.LIQUID: "phase_bias_liquid",
            AggregateState.PLASMA: "phase_bias_plasma",
        }[phase]
        base = 1.0
        abstraction = _clamp(float(mechanism.get("abstraction_bias", 1.0)), 0.45, 1.55)
        gradient_weight = max(0.2, 1.0 - 0.5 * abstraction)
        entropy_weight = min(1.55, 0.7 + 0.45 * abstraction)
        base += float(mechanism.get("gradient_gain", 0.0)) * float(features["gradient"]) * gradient_weight
        base += float(mechanism.get("resonance_gain", 0.0)) * float(features["resonance"])
        base += float(mechanism.get("coherence_gain", 0.0)) * (float(features["coherence"]) - 0.5)
        base += float(mechanism.get("entropy_pattern_gain", 0.0)) * float(features.get("entropy_patterns", 0.0)) * entropy_weight
        base *= float(mechanism.get(phase_key, 1.0))
        base *= max(0.65, 1.0 - float(mechanism.get("entropy_damp", 0.0)) * max(0.0, float(features["entropy"]) - 0.45))
        program = mechanism.get("program", [])
        if isinstance(program, list):
            base += self.core.evolution._apply_program(program, features)
        return _clamp(base, 0.65, 1.65)

    def _predict_purpose_delta(self, mechanism: Dict[str, Any]) -> float:
        contexts = self._sample_feature_contexts(limit=24)
        if not contexts:
            return 0.0
        current = _clamp(self.core.transcendence.last_purpose_alignment, 0.0, 1.0)
        utility = 0.0
        for features in contexts:
            gain = self._mechanism_gain_from_features(mechanism, features)
            direction = _clamp(
                0.34 * (1.0 - current)
                + 0.22 * float(features["coherence"])
                + 0.2 * float(features["resonance"])
                + 0.14 * float(features["morphic"])
                + 0.1 * float(features["purpose"])
                + 0.1 * float(features.get("entropy_patterns", 0.0))
                - 0.18 * float(features["entropy"]),
                0.05,
                1.25,
            )
            utility += (gain - 1.0) * direction
        utility /= max(1, len(contexts))
        thermal_penalty = _clamp((self.core.phase_controller.system_temperature - 70.0) / 70.0, 0.0, 0.25)
        mechanism_scarcity = _clamp((2.0 - len(self.core.evolution.runtime_mechanisms)) / 2.0, 0.0, 1.0)
        exploration_bonus = 0.02 * (1.0 - current) + 0.025 * mechanism_scarcity
        delta = math.tanh(utility * 1.7) * (0.12 + 0.18 * (1.0 - current)) - thermal_penalty + exploration_bonus
        return _clamp(delta, -0.18, 0.22)

    def _select_outbound_mechanism(self) -> Optional[Dict[str, Any]]:
        if not self.core.evolution.runtime_mechanisms:
            return None
        ranked: list[tuple[float, Dict[str, Any]]] = []
        for mechanism in self.core.evolution.runtime_mechanisms.values():
            cleaned = self._sanitize_mechanism(mechanism, max_terms=self.max_terms_shared + 1)
            score = (
                abs(float(cleaned["gradient_gain"]))
                + abs(float(cleaned["resonance_gain"]))
                + abs(float(cleaned["coherence_gain"]))
                + 0.8 * abs(float(cleaned["entropy_pattern_gain"]))
                + 0.35 * len(cleaned["program"])
                + 0.12 * float(cleaned["abstraction_bias"])
                + 0.2 * _clamp(float(cleaned["entropy_damp"]), 0.0, 1.0)
            )
            ranked.append((score, cleaned))
        ranked.sort(key=lambda item: item[0], reverse=True)
        if not ranked:
            return None
        top = ranked[: min(3, len(ranked))]
        chosen = random.choice(top)[1]
        chosen["program"] = self._program_slice(chosen.get("program", []), terms=self.max_terms_shared)
        chosen["program_signature"] = self.core.evolution._program_signature(chosen["program"])
        return chosen

    def offer_mechanism(self) -> Optional[Dict[str, Any]]:
        offer = self._select_outbound_mechanism()
        if not offer:
            return None
        self.hgt_offers += 1
        self.last_offer_signature = str(offer.get("program_signature", ""))
        return {
            **offer,
            "offered_by": self.core.core_id,
            "offered_at": round(time.time(), 6),
        }

    def offer_symbol_packet(self) -> Optional[Dict[str, Any]]:
        packet = self.core.symbolics.export_symbol_packet()
        if not packet:
            return None
        self.symbol_offers += 1
        self.last_symbol_signature = str(packet.get("signature", ""))
        return packet

    def receive_symbol_packet(self, packet: Dict[str, Any], *, source_core_id: str) -> bool:
        self.symbol_received += 1
        signature = str(packet.get("signature", "")) if isinstance(packet, dict) else ""
        self.last_partner = source_core_id
        self.last_symbol_signature = signature or self.last_symbol_signature
        if not signature:
            self.symbol_rejects += 1
            return False

        known_signatures = {
            str(meta.get("signature", ""))
            for meta in self.core.symbolics.known_symbols()
            if meta.get("signature")
        }
        novelty = 1.0 if signature not in known_signatures else 0.0
        stability = _clamp(float(packet.get("stability", 0.0)), 0.0, 1.0)
        shared = _clamp(float(packet.get("shared_cores", 0.0)) / 4.0, 0.0, 1.0)
        acceptance = _clamp(
            0.46 * stability
            + 0.28 * novelty
            + 0.16 * shared
            + 0.1 * (1.0 - _clamp(self.core.cognition.epigenetic_registry.last_surprise_signal, 0.0, 1.0)),
            0.0,
            1.0,
        )
        if acceptance < 0.34:
            self.symbol_rejects += 1
            return False

        accepted = self.core.symbolics.ingest_symbol_packet(packet, source_core_id=source_core_id)
        if not accepted:
            self.symbol_rejects += 1
            return False

        self.symbol_accepts += 1
        return True

    def _hybridize_with_local(self, remote: Dict[str, Any]) -> Dict[str, Any]:
        local_mechanism: Optional[Dict[str, Any]] = None
        if self.core.evolution.runtime_mechanisms:
            local_mechanism = self._sanitize_mechanism(
                random.choice(list(self.core.evolution.runtime_mechanisms.values())),
                max_terms=self.max_terms_shared + 2,
            )

        if local_mechanism is None:
            hybrid = self._sanitize_mechanism(remote, max_terms=self.max_terms_shared + 2)
            hybrid["program_signature"] = self.core.evolution._program_signature(hybrid["program"])
            return hybrid

        remote_clean = self._sanitize_mechanism(remote, max_terms=self.max_terms_shared + 2)
        local_clean = self._sanitize_mechanism(local_mechanism, max_terms=self.max_terms_shared + 2)

        hybrid: Dict[str, Any] = {}
        scalar_keys = [
            "gradient_gain",
            "resonance_gain",
            "coherence_gain",
            "entropy_pattern_gain",
            "entropy_damp",
            "phase_bias_solid",
            "phase_bias_liquid",
            "phase_bias_plasma",
            "stochasticity",
            "abstraction_bias",
        ]
        for key in scalar_keys:
            rv = float(remote_clean.get(key, 0.0))
            lv = float(local_clean.get(key, 0.0))
            blended = 0.58 * rv + 0.42 * lv + random.uniform(-0.015, 0.015)
            if key.startswith("phase_bias_"):
                hybrid[key] = _clamp(blended, 0.65, 1.45)
            elif key == "entropy_damp":
                hybrid[key] = _clamp(blended, 0.0, 1.2)
            elif key == "stochasticity":
                hybrid[key] = _clamp(blended, 0.0, 0.2)
            elif key == "abstraction_bias":
                hybrid[key] = _clamp(blended, 0.45, 1.55)
            else:
                hybrid[key] = _clamp(blended, -1.2, 1.8)

        remote_terms = self._program_slice(remote_clean.get("program", []), terms=max(1, self.max_terms_shared // 2 + 1))
        local_terms = self._program_slice(local_clean.get("program", []), terms=max(1, self.max_terms_shared // 2))
        merged_program = remote_terms + local_terms
        if not merged_program:
            merged_program = self._program_slice(remote_clean.get("program", []), terms=2) or self._program_slice(
                local_clean.get("program", []),
                terms=2,
            )
        hybrid["program"] = merged_program[: max(2, self.max_terms_shared + 1)]
        hybrid["program_signature"] = self.core.evolution._program_signature(hybrid["program"])
        hybrid["bridge_signature"] = str(remote_clean.get("bridge_signature") or local_clean.get("bridge_signature") or "")
        return hybrid

    def _enforce_morphic_analogy(self) -> bool:
        bridges = self.core.cognition.morphic_analogy_bridges(limit=2)
        if not bridges:
            return False

        created = False
        for src, target, similarity in bridges:
            bridge_signature = hashlib.sha1(
                f"{src.label}|{target.label}|{round(similarity, 4)}".encode("utf-8")
            ).hexdigest()[:12]
            if any(
                str(mech.get("bridge_signature", "")) == bridge_signature
                for mech in self.core.evolution.runtime_mechanisms.values()
            ):
                self.last_bridge_signature = bridge_signature
                continue

            self._ensure_capacity()
            mech_name = self.core.evolution._new_mechanism_name()
            entropy_pattern = self.core.cognition.epigenetic_registry.aggregate_entropy_pattern((src.label, target.label))
            program = [
                {
                    "left": "entropy_patterns",
                    "op": "tanh",
                    "right": "resonance",
                    "coefficient": _clamp(0.14 + 0.24 * similarity, -1.4, 1.4),
                    "power": _clamp(1.1 + 0.9 * entropy_pattern, 1.0, 3.0),
                },
                {
                    "left": "coherence",
                    "op": "plus",
                    "right": "entropy_patterns",
                    "coefficient": _clamp(0.08 + 0.16 * similarity, -1.4, 1.4),
                    "power": 1.0,
                },
            ]
            signature = self.core.evolution._program_signature(program)
            self.core.evolution.runtime_mechanisms[mech_name] = {
                "gradient_gain": 0.05 + 0.06 * (1.0 - similarity),
                "resonance_gain": 0.16 + 0.18 * similarity,
                "coherence_gain": 0.08 + 0.14 * similarity,
                "entropy_pattern_gain": 0.2 + 0.32 * entropy_pattern,
                "entropy_damp": 0.04 + 0.08 * (1.0 - entropy_pattern),
                "phase_bias_solid": 0.92,
                "phase_bias_liquid": 1.08,
                "phase_bias_plasma": 1.14,
                "stochasticity": 0.0,
                "abstraction_bias": _clamp(0.92 + 0.22 * similarity, 0.45, 1.55),
                "program_signature": signature,
                "program": program,
                "bridge_signature": bridge_signature,
                "hgt": True,
                "source_core_id": self.core.core_id,
            }
            self.core.evolution.evolution_events += 1
            self.core.evolution.last_innovation_label = mech_name
            self.core.evolution.last_program_signature = signature
            self.bridge_forced_hgt_events += 1
            self.last_bridge_signature = bridge_signature
            created = True
        return created

    def _ensure_capacity(self) -> None:
        mechanisms = self.core.evolution.runtime_mechanisms
        while len(mechanisms) >= self.max_runtime_mechanisms:
            removable = sorted(mechanisms.keys())
            if not removable:
                return
            victim = removable[0]
            mechanisms.pop(victim, None)

    def receive_mechanism(self, mechanism_payload: Dict[str, Any], *, source_core_id: str) -> bool:
        self.hgt_received += 1
        remote = self._sanitize_mechanism(mechanism_payload, max_terms=self.max_terms_shared + 2)
        predicted_delta = self._predict_purpose_delta(remote)
        self.last_predicted_purpose_delta = predicted_delta
        self.last_partner = source_core_id
        self.last_received_signature = str(remote.get("program_signature", ""))

        if predicted_delta <= self.acceptance_margin:
            self.hgt_rejects += 1
            return False

        hybrid = self._hybridize_with_local(remote)
        self._ensure_capacity()
        mech_name = self.core.evolution._new_mechanism_name()
        hybrid["hgt"] = True
        hybrid["source_core_id"] = source_core_id
        hybrid["ingested_at"] = round(time.time(), 6)
        self.core.evolution.runtime_mechanisms[mech_name] = hybrid
        self.core.evolution.evolution_events += 1
        self.core.evolution.last_innovation_label = mech_name
        self.core.evolution.last_program_signature = str(hybrid.get("program_signature") or "")
        self.hgt_accepts += 1
        logger.info(
            "HGT-Symbiosis | receiver=%s donor=%s mechanism=%s predicted_delta=%.4f",
            self.core.core_id,
            source_core_id,
            mech_name,
            predicted_delta,
        )
        return True

    async def exchange_with(self, peer_core: "AtheriaCore", *, reciprocal: bool = True) -> bool:
        if not self.enabled:
            return False
        if peer_core.core_id == self.core.core_id:
            return False
        if not peer_core.running:
            return False
        if not hasattr(peer_core, "symbiosis"):
            return False

        now = time.perf_counter()
        last = self.last_exchange_by_peer.get(peer_core.core_id, 0.0)
        if (now - last) < self.exchange_cooldown_seconds:
            return False

        accepted_any = False
        peer_offer = peer_core.symbiosis.offer_mechanism()
        if peer_offer:
            accepted = self.receive_mechanism(peer_offer, source_core_id=peer_core.core_id)
            if accepted:
                peer_core.symbiosis.hgt_donated += 1
                accepted_any = True

        peer_symbol = peer_core.symbiosis.offer_symbol_packet()
        if peer_symbol:
            accepted = self.receive_symbol_packet(peer_symbol, source_core_id=peer_core.core_id)
            if accepted:
                peer_core.symbiosis.symbol_donated += 1
                accepted_any = True

        if reciprocal:
            own_offer = self.offer_mechanism()
            if own_offer:
                accepted = peer_core.symbiosis.receive_mechanism(own_offer, source_core_id=self.core.core_id)
                if accepted:
                    self.hgt_donated += 1
                    accepted_any = True
            own_symbol = self.offer_symbol_packet()
            if own_symbol:
                accepted = peer_core.symbiosis.receive_symbol_packet(own_symbol, source_core_id=self.core.core_id)
                if accepted:
                    self.symbol_donated += 1
                    accepted_any = True

        self.last_exchange_by_peer[peer_core.core_id] = now
        peer_core.symbiosis.last_exchange_by_peer[self.core.core_id] = now
        return accepted_any

    def _peer_priority(self, peer: "AtheriaCore") -> float:
        own_signatures = {
            str(mech.get("program_signature", ""))
            for mech in self.core.evolution.runtime_mechanisms.values()
            if mech.get("program_signature")
        }
        peer_signatures = {
            str(mech.get("program_signature", ""))
            for mech in peer.evolution.runtime_mechanisms.values()
            if mech.get("program_signature")
        }
        novelty = len(peer_signatures - own_signatures)
        own_symbol_signatures = {
            str(meta.get("signature", ""))
            for meta in self.core.symbolics.known_symbols()
            if meta.get("signature")
        }
        peer_symbol_signatures = {
            str(meta.get("signature", ""))
            for meta in peer.symbolics.known_symbols()
            if meta.get("signature")
        }
        symbol_novelty = len(peer_symbol_signatures - own_symbol_signatures)
        alignment_gap = abs(
            _clamp(peer.transcendence.last_purpose_alignment, 0.0, 1.0)
            - _clamp(self.core.transcendence.last_purpose_alignment, 0.0, 1.0)
        )
        peer_guardian = peer.assembler.guardian_score() if hasattr(peer, "assembler") else 0.0
        return 0.38 * novelty + 0.22 * symbol_novelty + 0.2 * alignment_gap + 0.2 * peer_guardian

    async def step(self) -> None:
        if not self.enabled:
            return
        bridge_created = self._enforce_morphic_analogy()
        if self.core.aion_meditation_mode:
            return
        peers = [
            peer
            for peer in GLOBAL_CORE_REGISTRY.peers(self.core.core_id, running_only=True)
            if not peer.aion_meditation_mode
            if len(peer.evolution.runtime_mechanisms) > 0 or len(peer.symbolics.known_symbols()) > 0
        ]
        if not peers:
            return
        peers.sort(key=self._peer_priority, reverse=True)
        best_peer = peers[0]
        if bridge_created:
            self.last_exchange_by_peer.pop(best_peer.core_id, None)
            best_peer.symbiosis.last_exchange_by_peer.pop(self.core.core_id, None)
        await self.exchange_with(best_peer, reciprocal=True)

    async def run(self) -> None:
        while self.core.running:
            try:
                await self.step()
            finally:
                await asyncio.sleep(self.interval)


class SelfReproductionEngine:
    """
    Autonomously creates independent offspring cores.
    """

    def __init__(self, core: "AtheriaCore") -> None:
        self.core = core
        self.max_offspring = 2
        self.cooldown_seconds = 18.0
        self.last_reproduction_ts = 0.0
        self._counter = 0
        self.reproduction_events = 0
        self.offspring_cores: Dict[str, "AtheriaCore"] = {}
        self.offspring_tasks: Dict[str, asyncio.Task] = {}
        self.last_reproduction_score = 0.0
        self.selection_trials_per_reproduction = 2
        self.selection_trial_seconds = 0.45
        self.selection_margin = 0.02
        self.selection_total_trials = 0
        self.selection_child_wins = 0
        self.selection_parent_wins = 0
        self.last_parent_fitness = 0.0
        self.last_child_fitness = 0.0
        self.selection_tasks: Dict[str, asyncio.Task] = {}
        self.reproduction_threshold_offset = 0.0
        self.artifact_emission_enabled = True
        self.artifact_run_harness = True
        self.artifact_output_root = Path("DEMO/lineage")
        self.artifact_events = 0
        self.last_artifact_profile: Optional[str] = None
        self.last_artifact_path: Optional[str] = None
        self.last_artifact_integrity_path: Optional[str] = None
        self.last_artifact_validated = False
        self.last_artifact_signature: Optional[str] = None
        self.last_artifact_report: Dict[str, Any] = {}
        self.artifact_tasks: Dict[str, asyncio.Task] = {}

    def _artifact_profile(self) -> str:
        temp = self.core.phase_controller.system_temperature
        align = self.core.transcendence.last_purpose_alignment
        scarcity = self.core.ecology.resource_scarcity
        heuristic = "survival"
        if temp >= 80.0:
            heuristic = "stress-test"
        elif scarcity >= 0.45 or align < 0.55:
            heuristic = "diagnostic"
        if hasattr(self.core, "lineage_auditor"):
            lineage_report = self.core.lineage_auditor.scan_lineage(default_profile=heuristic)
            recommended = str(lineage_report.get("recommended_profile") or heuristic)
            if recommended:
                return recommended
        return heuristic

    def _artifact_message(self, child_name: str) -> str:
        align = self.core.transcendence.last_purpose_alignment
        morphic = self.core.holographic_field.last_morphic_resonance_index
        return (
            f"{child_name} lineage pulse | alignment={align:.3f} | morphic={morphic:.3f} "
            f"| selection_pressure={self.core.ecology.selection_pressure:.3f}"
        )

    def _forge_offspring_executable_sync(self, child_name: str) -> Dict[str, Any]:
        from dataclasses import asdict

        from DEMO.forge_executable import forge

        profile = self._artifact_profile()
        output_dir = self.artifact_output_root / child_name
        signing_key_path = Path("DEMO/lineage_signing.key")
        result = forge(
            name=child_name.lower(),
            output_dir=output_dir,
            profile=profile,
            message=self._artifact_message(child_name),
            interval=0.11 if profile == "stress-test" else 0.2,
            iterations=16 if profile == "stress-test" else 10,
            build_exe=False,
            sign_artifacts=True,
            signing_key_path=signing_key_path,
            signing_key_env="ATHERIA_DEMO_SIGNING_KEY",
            auto_generate_signing_key=True,
            run_harness=self.artifact_run_harness,
            harness_iterations=2,
            harness_interval=0.0,
            harness_timeout_seconds=20.0,
            harness_run_launchers=False,
            strict_harness=False,
        )
        return asdict(result)

    async def _emit_offspring_executable(self, child_name: str) -> None:
        if not self.artifact_emission_enabled:
            return
        try:
            report = await asyncio.to_thread(self._forge_offspring_executable_sync, child_name)
        except Exception as exc:
            logger.warning("Self-Reproduction Artifact failed | offspring=%s | error=%s", child_name, exc)
            self.last_artifact_report = {
                "offspring": child_name,
                "error": str(exc),
                "timestamp": round(time.time(), 6),
            }
            self.last_artifact_validated = False
            return

        self.artifact_events += 1
        self.last_artifact_report = report
        self.last_artifact_profile = str(report.get("profile") or "")
        self.last_artifact_path = str(report.get("output_dir") or "")
        self.last_artifact_integrity_path = str(report.get("integrity_path") or "")
        harness = report.get("harness")
        if isinstance(harness, dict):
            self.last_artifact_validated = bool(harness.get("passed", False))
        else:
            self.last_artifact_validated = False
        signature = report.get("signing_key_fingerprint")
        self.last_artifact_signature = str(signature) if signature else None

        try:
            self.artifact_output_root.mkdir(parents=True, exist_ok=True)
            lineage_log = self.artifact_output_root / "lineage_artifacts.jsonl"
            with lineage_log.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "offspring": child_name,
                            "profile": self.last_artifact_profile,
                            "output_dir": self.last_artifact_path,
                            "integrity_path": self.last_artifact_integrity_path,
                            "validated": self.last_artifact_validated,
                            "signature_fingerprint": self.last_artifact_signature,
                            "timestamp": round(time.time(), 6),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except Exception:
            pass

        logger.info(
            "Self-Reproduction Artifact | offspring=%s | profile=%s | validated=%s",
            child_name,
            self.last_artifact_profile,
            self.last_artifact_validated,
        )

    def _clone_modulators(self) -> NeuroModulators:
        return NeuroModulators(
            dopamine=float(self.core.modulators.dopamine),
            adrenaline=float(self.core.modulators.adrenaline),
            serotonin=float(self.core.modulators.serotonin),
        )

    def _extract_genome(self, source_core: "AtheriaCore") -> Dict[str, object]:
        cells = []
        for cell in source_core.cells.values():
            cells.append(
                {
                    "label": cell.label,
                    "category": cell.category,
                    "semipermeability": float(cell.semipermeability),
                    "archetype": cell.archetype,
                    "archetype_traits": {k: float(v) for k, v in cell.archetype_traits.items()},
                    "integrity_rate": float(cell.integrity_rate),
                    "activation": float(cell.activation_value),
                }
            )
        edges = []
        for src in source_core.cells.values():
            for target_label, conn in src.connections.items():
                edges.append(
                    {
                        "src": src.label,
                        "dst": target_label,
                        "weight": float(conn.weight),
                        "energy": float(conn.activation_energy),
                    }
                )
        return {
            "cells": cells,
            "edges": edges,
            "topology": {
                name: {
                    "core": sorted(cluster["core"]),
                    "boundary": sorted(cluster["boundary"]),
                }
                for name, cluster in source_core.topological_logic.clusters.items()
            },
            "topology_rules": source_core.topological_logic.export_rules(),
            "evolution": source_core.evolution.export_state(),
        }

    def _genome(self) -> Dict[str, object]:
        return self._extract_genome(self.core)

    def _fitness_score_from_snapshot(self, snap: Dict[str, object]) -> float:
        purpose = float(snap["purpose_alignment"])
        morphic = float(snap["morphic_resonance_index"])
        dreams = min(1.0, float(snap["dream_replay_events"]) / 320.0)
        semantic = min(1.0, float(snap["semantic_analogy_cells"]) / 24.0)
        aion = min(1.0, float(snap["aion_cycle_activity"]) * 2.0)
        integrity = min(1.0, max(0.0, 0.5 + 0.5 * (1.0 - min(1.0, float(snap["mean_hyperbolic_distance"]) / 2.2))))
        temp_eff = max(0.0, min(1.0, 1.0 - abs(float(snap["system_temperature"]) - 52.0) / 60.0))
        score = (
            0.24 * purpose
            + 0.2 * morphic
            + 0.16 * dreams
            + 0.12 * semantic
            + 0.08 * aion
            + 0.1 * integrity
            + 0.1 * temp_eff
        )
        return max(0.0, min(1.0, score))

    def _maturity_score(self) -> float:
        snap = self.core.dashboard_snapshot()
        self.last_reproduction_score = self._fitness_score_from_snapshot(snap)
        return self.last_reproduction_score

    def _should_reproduce(self) -> bool:
        if len(self.offspring_cores) >= self.max_offspring:
            return False
        if self.core.assembler.resource_pool < 16.0:
            return False
        now = time.perf_counter()
        if now - self.last_reproduction_ts < self.cooldown_seconds:
            return False
        threshold = (0.78 if self.core.aion_meditation_mode else 0.86) + self.reproduction_threshold_offset
        threshold = max(0.58, min(0.95, threshold))
        return self._maturity_score() >= threshold

    def _spawn_from_genome(self, genome: Dict[str, object], *, child_name: str) -> "AtheriaCore":
        child_tick = max(0.02, min(0.09, self.core.tick_interval * random.uniform(0.92, 1.08)))
        child = AtheriaCore(tick_interval=child_tick, modulators=self._clone_modulators())

        cell_rows = genome.get("cells", [])
        for row in cell_rows:
            label = str(row.get("label", "Cell"))
            category = str(row.get("category", label))
            semipermeability = float(row.get("semipermeability", 0.7))
            cell = child.add_cell(label, category=category, semipermeability=semipermeability)
            cell.set_activation(float(row.get("activation", 0.0)) * random.uniform(0.78, 0.96))
            cell.integrity_rate = max(0.5, min(1.0, float(row.get("integrity_rate", 1.0)) * random.uniform(0.92, 1.02)))
            archetype = str(row.get("archetype", "baseline"))
            traits = {k: float(v) for k, v in dict(row.get("archetype_traits", {})).items()}
            if traits:
                traits = {k: max(-0.4, min(1.8, v + random.uniform(-0.02, 0.02))) for k, v in traits.items()}
            cell.apply_archetype(archetype, traits)

        for edge in genome.get("edges", []):
            src = str(edge.get("src", ""))
            dst = str(edge.get("dst", ""))
            if src not in child.cells or dst not in child.cells or src == dst:
                continue
            child.connect(src, dst, weight=float(edge.get("weight", 0.3)))
            conn = child.cells[src].connections.get(dst)
            if conn is not None:
                conn.activation_energy = max(0.05, float(edge.get("energy", conn.activation_energy)) * random.uniform(0.95, 1.05))

        topo = genome.get("topology", {})
        child.topological_logic.import_rules(dict(genome.get("topology_rules", {})))
        for cluster_name, cluster in topo.items():
            core_labels = [label for label in cluster.get("core", []) if label in child.cells]
            boundary_labels = [label for label in cluster.get("boundary", []) if label in child.cells]
            if core_labels:
                child.register_topological_cluster(
                    f"{cluster_name}_child_{child_name}",
                    core_labels=core_labels,
                    boundary_labels=boundary_labels,
                )
        child.setup_critical_entanglement()
        child.aion.ensure_singularity_node()
        child.setup_topological_core()
        child.evolution.import_state(dict(genome.get("evolution", {})), mutate=True)
        return child

    async def _apply_trial_disturbance(self, core: "AtheriaCore") -> None:
        core_labels = set()
        for cluster in core.topological_logic.clusters.values():
            core_labels.update(cluster["core"])
        excluded = core_labels | {core.aion.singularity_label, core.transcendence.telos.purpose_label}
        candidates = [cell for cell in core.cells.values() if cell.label not in excluded]
        if not candidates:
            return
        damage_count = max(1, int(len(candidates) * 0.25))
        for cell in random.sample(candidates, k=min(damage_count, len(candidates))):
            cell.integrity_rate = max(0.02, cell.integrity_rate * 0.35)
            cell.error_counter += 1
        cuttable = []
        for src in candidates:
            for dst in list(src.connections.keys()):
                if core.topological_logic.is_edge_protected(src.label, dst):
                    continue
                cuttable.append((src, dst))
        if cuttable:
            for src, dst in random.sample(cuttable, k=min(len(cuttable), max(1, int(0.2 * len(cuttable))))):
                src.remove_connection(dst)

    async def _simulate_fitness(self, genome: Dict[str, object], *, trial_seconds: float) -> float:
        sim = self._spawn_from_genome(genome, child_name=f"SIM_{random.randint(1000,9999)}")
        sim.reproduction.max_offspring = 0
        sim.reproduction.artifact_emission_enabled = False
        sim.symbiosis.enabled = False
        sim.assembler.market_enabled = False
        sim.rhythm.inter_core_dreaming_enabled = False
        await sim.start()
        try:
            sim.modulators.force_plasma(sim.phase_controller, intensity=1.0)
            await asyncio.sleep(trial_seconds * 0.35)
            await self._apply_trial_disturbance(sim)
            await asyncio.sleep(trial_seconds * 0.65)
            snap = sim.dashboard_snapshot()
            return self._fitness_score_from_snapshot(snap)
        finally:
            await sim.stop(shutdown_lineage=True)

    async def _run_selection_trials(self, child_name: str, parent_genome: Dict[str, object], child_genome: Dict[str, object]) -> None:
        parent_scores = []
        child_scores = []
        trials = max(1, int(self.selection_trials_per_reproduction))
        for _ in range(trials):
            parent_scores.append(await self._simulate_fitness(parent_genome, trial_seconds=self.selection_trial_seconds))
            child_scores.append(await self._simulate_fitness(child_genome, trial_seconds=self.selection_trial_seconds))

        parent_fit = sum(parent_scores) / max(1, len(parent_scores))
        child_fit = sum(child_scores) / max(1, len(child_scores))
        self.last_parent_fitness = parent_fit
        self.last_child_fitness = child_fit
        self.selection_total_trials += trials

        if child_fit + self.selection_margin < parent_fit:
            self.selection_parent_wins += 1
            doomed = self.offspring_cores.pop(child_name, None)
            self.offspring_tasks.pop(child_name, None)
            artifact_task = self.artifact_tasks.pop(child_name, None)
            if artifact_task is not None:
                artifact_task.cancel()
            if doomed is not None:
                await doomed.stop(shutdown_lineage=True)
            logger.info(
                "Lineage-Selection | parent wins | child=%s | parent_fit=%.4f | child_fit=%.4f",
                child_name,
                parent_fit,
                child_fit,
            )
        else:
            self.selection_child_wins += 1
            logger.info(
                "Lineage-Selection | child survives | child=%s | parent_fit=%.4f | child_fit=%.4f",
                child_name,
                parent_fit,
                child_fit,
            )

    def step(self) -> None:
        if not self._should_reproduce():
            return
        self.force_reproduction()

    def force_reproduction(self) -> Optional[str]:
        self._counter += 1
        child_name = f"ATHERIA_CHILD_{self._counter:03d}"
        genome = self._genome()
        child = self._spawn_from_genome(genome, child_name=child_name)
        task = asyncio.create_task(child.start(), name=f"atheria-offspring-{child_name}")
        self.offspring_cores[child_name] = child
        self.offspring_tasks[child_name] = task
        self.reproduction_events += 1
        self.last_reproduction_ts = time.perf_counter()
        self.core.assembler.resource_pool = max(0.0, self.core.assembler.resource_pool - 8.0)
        logger.info("Self-Reproduction | offspring=%s | lineage=%s", child_name, len(self.offspring_cores))
        child_genome = self._extract_genome(child)
        selection_task = asyncio.create_task(
            self._run_selection_trials(child_name, parent_genome=genome, child_genome=child_genome),
            name=f"atheria-selection-{child_name}",
        )
        self.selection_tasks[child_name] = selection_task
        if self.artifact_emission_enabled:
            artifact_task = asyncio.create_task(
                self._emit_offspring_executable(child_name),
                name=f"atheria-artifact-{child_name}",
            )
            self.artifact_tasks[child_name] = artifact_task
            artifact_task.add_done_callback(lambda _task, key=child_name: self.artifact_tasks.pop(key, None))
        return child_name

    async def stop_all_offspring(self) -> None:
        if self.artifact_tasks:
            for task in list(self.artifact_tasks.values()):
                task.cancel()
            await asyncio.gather(*self.artifact_tasks.values(), return_exceptions=True)
            self.artifact_tasks.clear()
        if self.selection_tasks:
            for task in list(self.selection_tasks.values()):
                task.cancel()
            await asyncio.gather(*self.selection_tasks.values(), return_exceptions=True)
            self.selection_tasks.clear()
        for child in self.offspring_cores.values():
            try:
                await child.stop()
            except Exception:
                continue
        self.offspring_cores.clear()
        self.offspring_tasks.clear()


class EcoDynamicsEngine:
    """
    Drives the four missing growth accelerators:
    - selection pressure
    - environmental complexity
    - resource limitation
    - explicit fitness gradient
    """

    def __init__(self, core: "AtheriaCore") -> None:
        self.core = core
        self.challenge_complexity = 0.22
        self.selection_pressure = 0.34
        self.resource_scarcity = 0.0
        self.last_fitness = 0.0
        self.last_fitness_gradient = 0.0
        self._tick = 0
        dims = int(self.core.holographic_field.pattern.numel())
        self.challenge_vector = torch.randn(dims, dtype=torch.float32)
        self.challenge_vector = self.challenge_vector / (torch.norm(self.challenge_vector, p=2) + 1e-8)

    def _system_fitness(self) -> float:
        purpose = self.core.transcendence.last_purpose_alignment
        morphic = self.core.holographic_field.last_morphic_resonance_index
        integrity = sum(cell.integrity_rate for cell in self.core.cells.values()) / max(1, len(self.core.cells))
        homeo_temp = float(
            getattr(self.core.cells.get(self.core.transcendence.telos.purpose_label), "homeostatic_temperature", 34.0)
        )
        temp = self.core.phase_controller.system_temperature
        temp_eff = math.exp(-abs(temp - homeo_temp) / 28.0)
        innovation = math.tanh(
            (max(0, len(self.core.evolution.cell_type_blueprints) - 1) + len(self.core.evolution.runtime_mechanisms))
            / 20.0
        )
        return max(
            0.0,
            min(
                1.0,
                0.28 * purpose + 0.24 * morphic + 0.2 * integrity + 0.16 * temp_eff + 0.12 * innovation,
            ),
        )

    def _update_fitness_gradient(self) -> None:
        current = self._system_fitness()
        if self.last_fitness <= 0.0:
            self.last_fitness = current
        grad = current - self.last_fitness
        self.last_fitness = 0.88 * self.last_fitness + 0.12 * current
        self.last_fitness_gradient = 0.82 * self.last_fitness_gradient + 0.18 * grad

    def _update_resource_model(self, cpu_load: float) -> None:
        population = len(self.core.cells) + len(self.core.reproduction.offspring_cores)
        carrying_capacity = 14.0 + 14.0 * self.challenge_complexity
        overload = max(0.0, (population - carrying_capacity) / max(1.0, carrying_capacity))
        demand = 0.04 * population + 0.35 * len(self.core.reproduction.offspring_cores) + 0.22 * overload
        demand += 0.012 * max(0.0, cpu_load - 40.0)

        regen = 0.12 + 0.22 * self.core.transcendence.last_purpose_alignment + 0.18 * self.core.holographic_field.last_morphic_resonance_index
        delta = regen - demand
        self.core.assembler.resource_pool = max(0.0, min(5000.0, self.core.assembler.resource_pool + delta))

        scarcity_base = max(0.0, min(1.0, (16.0 - self.core.assembler.resource_pool) / 16.0))
        self.resource_scarcity = max(0.0, min(1.0, 0.62 * scarcity_base + 0.38 * max(0.0, min(1.0, overload))))

    def _update_complexity_and_pressure(self) -> None:
        if self.last_fitness_gradient > 0.01 and self.resource_scarcity < 0.55:
            self.challenge_complexity = min(1.0, self.challenge_complexity + 0.015)
        elif self.last_fitness_gradient < -0.01:
            self.challenge_complexity = max(0.1, self.challenge_complexity - 0.012)
        else:
            drift = 0.003 * (0.5 - self.challenge_complexity)
            self.challenge_complexity = max(0.1, min(1.0, self.challenge_complexity + drift))

        pressure = 0.34 + 0.42 * self.challenge_complexity + 0.34 * self.resource_scarcity - 0.25 * max(
            0.0, self.last_fitness_gradient
        )
        self.selection_pressure = max(0.0, min(1.0, pressure))
        self.core.evolution.set_selection_pressure(self.selection_pressure)
        self.core.reproduction.reproduction_threshold_offset = max(
            -0.1,
            min(0.25, (self.selection_pressure - 0.5) * 0.22 + self.resource_scarcity * 0.2),
        )

    def _apply_environmental_complexity(self) -> None:
        if self.core.aion_meditation_mode:
            return
        if self._tick % 5 != 0:
            return
        dims = int(self.core.holographic_field.pattern.numel())
        noise = torch.randn(dims, dtype=torch.float32) * (0.08 + 0.22 * self.challenge_complexity)
        self.challenge_vector = torch.tanh(0.9 * self.challenge_vector + 0.1 * noise)
        self.challenge_vector = self.challenge_vector / (torch.norm(self.challenge_vector, p=2) + 1e-8)

        idx = int(torch.argmax(torch.abs(self.challenge_vector)).item())
        relevance = 0.06 + 0.24 * self.challenge_complexity
        self.core.assembler.feed(
            category=f"EcoChallenge_{idx}",
            relevance=relevance,
            input_tensor=self.challenge_vector,
            external=False,
        )
        self.core.assembler.feed(
            category=f"EcoStress_{idx}",
            relevance=max(0.04, relevance * 0.8),
            input_tensor=(0.7 * self.challenge_vector + 0.3 * self.core.holographic_field.pattern),
            external=False,
        )

    def step(self, cpu_load: float) -> None:
        self._tick += 1
        self._update_fitness_gradient()
        self._update_resource_model(cpu_load=cpu_load)
        self._update_complexity_and_pressure()
        self._apply_environmental_complexity()


class EpigeneticRegistry:
    def __init__(self, core: "AtheriaCore") -> None:
        self.core = core
        self._silenced_edges: Dict[Tuple[str, str], Dict[str, float | str]] = {}
        self._feature_vectors: Dict[str, Dict[str, float]] = {}
        self._library_cells: Dict[str, LibraryCell] = {}
        self._archived_sets: Set[str] = set()
        self._template_counter = 0
        self.last_extracted_entropy_pattern = 0.0
        self.predictive_inhibition_events = 0
        self.predictive_absorbed_energy = 0.0
        self.predictive_total_absorbed_energy = 0.0
        self.last_predictability = 0.0
        self.last_surprise_signal = 0.0
        self.last_predictive_template: Optional[str] = None

    def silence(self, src_label: str, dst_label: str, *, ttl: float, reason: str) -> None:
        self._silenced_edges[(src_label, dst_label)] = {
            "until": time.perf_counter() + max(0.05, ttl),
            "reason": reason,
        }

    def _prune_expired(self) -> None:
        now = time.perf_counter()
        expired = [edge for edge, meta in self._silenced_edges.items() if float(meta["until"]) <= now]
        for edge in expired:
            self._silenced_edges.pop(edge, None)

    def is_silenced(self, src_label: str, dst_label: str) -> bool:
        self._prune_expired()
        return (src_label, dst_label) in self._silenced_edges

    def _extract_cell_features(self, cell: AtherCell) -> Dict[str, float]:
        usage = sum(conn.usage_count for conn in cell.connections.values())
        flux = sum(conn.catalytic_flux for conn in cell.connections.values())
        entropy = _clamp(self.core.phase_controller.system_temperature / 120.0, 0.0, 1.0)
        entropy_pattern = _clamp(
            0.34 * entropy
            + 0.24 * _clamp(self.core.phase_controller.structural_tension, 0.0, 1.0)
            + 0.2 * cell.coherence
            + 0.12 * min(1.0, flux)
            + 0.1 * min(1.0, usage / 20.0),
            0.0,
            1.0,
        )
        return {
            "activation": _clamp(cell.activation_value, 0.0, 1.0),
            "integrity": _clamp(cell.integrity_rate, 0.0, 1.0),
            "coherence": _clamp(cell.coherence, 0.0, 1.0),
            "hyper_radius": _clamp(float(torch.norm(cell.poincare_coord, p=2)), 0.0, 1.0),
            "entropy_pattern": entropy_pattern,
        }

    def _refresh_feature_vectors(self) -> None:
        features: Dict[str, Dict[str, float]] = {}
        for cell in self.core.cells.values():
            if isinstance(cell, LibraryCell):
                continue
            features[cell.label] = self._extract_cell_features(cell)
        self._feature_vectors = features
        if not features:
            self.last_extracted_entropy_pattern = 0.0
            return
        self.last_extracted_entropy_pattern = sum(
            float(meta["entropy_pattern"]) for meta in features.values()
        ) / max(1, len(features))

    def feature_signal(self, label: str, key: str, default: float = 0.0) -> float:
        meta = self._feature_vectors.get(label)
        if not meta:
            return float(default)
        return float(meta.get(key, default))

    def aggregate_entropy_pattern(self, labels: Iterable[str]) -> float:
        values = [
            self.feature_signal(label, "entropy_pattern")
            for label in labels
            if label in self._feature_vectors
        ]
        if not values:
            return float(self.last_extracted_entropy_pattern)
        return sum(values) / max(1, len(values))

    def _template_program(self, entropy_pattern: float) -> list[Dict[str, Any]]:
        return [
            {
                "left": "entropy_patterns",
                "op": "tanh",
                "right": "morphic",
                "coefficient": _clamp(0.18 + 0.24 * entropy_pattern, -1.4, 1.4),
                "power": _clamp(1.2 + 0.8 * entropy_pattern, 1.0, 3.0),
            },
            {
                "left": "coherence",
                "op": "plus",
                "right": "resonance",
                "coefficient": _clamp(0.08 + 0.12 * entropy_pattern, -1.4, 1.4),
                "power": 1.0,
            },
        ]

    def _archive_autocatalytic_templates(self) -> None:
        age_threshold = 14 if self.core.aion_meditation_mode else 28
        potency_threshold = 0.82
        for set_id, data in list(self.core.assembler.autocatalytic_sets.items()):
            if set_id in self._archived_sets:
                continue
            potency = float(data.get("potency", 0.0))
            age = int(data.get("age", 0))
            members = [label for label in data.get("members", []) if label in self.core.cells]
            if len(members) < 2:
                continue
            if potency < potency_threshold or age < age_threshold:
                continue

            templates = self.library_templates()
            if any(set(template.template_members) == set(members) for template in templates):
                self._archived_sets.add(set_id)
                continue

            self._template_counter += 1
            label = f"LibraryCell_{self._template_counter:03d}"
            entropy_pattern = self.aggregate_entropy_pattern(members)
            template = LibraryCell(
                label=label,
                category="EpigeneticLibrary",
                template_members=tuple(sorted(members)),
                template_potency=_clamp(potency, 0.0, 1.0),
                template_entropy_pattern=_clamp(entropy_pattern, 0.0, 1.0),
                template_program=self._template_program(entropy_pattern),
            )

            member_cells = [self.core.cells[name] for name in members]
            fold = torch.mean(torch.stack([cell.fold_signature for cell in member_cells], dim=0), dim=0)
            fold = fold / (torch.norm(fold, p=2) + 1e-8)
            template.fold_signature = fold
            midpoint = torch.mean(torch.stack([cell.poincare_coord for cell in member_cells], dim=0), dim=0)
            template.poincare_coord = _project_to_poincare_ball(midpoint)

            self._library_cells[label] = template
            self._archived_sets.add(set_id)
            while len(self._library_cells) > 8:
                oldest = sorted(self._library_cells.keys())[0]
                self._library_cells.pop(oldest, None)

    def _apply_rhythm_policy(self) -> None:
        if self.core.rhythm.state is not RhythmState.SLEEP:
            return
        for src in self.core.cells.values():
            for dst_label, conn in src.connections.items():
                if self.core.topological_logic.is_edge_protected(src.label, dst_label):
                    continue
                low_signal = conn.catalytic_flux < 0.03
                weak = conn.efficiency < 0.36
                if low_signal and weak:
                    self.silence(src.label, dst_label, ttl=0.9, reason="sleep_silencing")

    def _apply_temperature_policy(self) -> None:
        temp = self.core.phase_controller.system_temperature
        if temp < 88.0:
            return
        for src in self.core.cells.values():
            for dst_label, conn in src.connections.items():
                if self.core.topological_logic.is_edge_protected(src.label, dst_label):
                    continue
                noisy = conn.activation_energy > 1.1 and conn.efficiency < 0.28
                if noisy:
                    ttl = 0.55 if temp < 100.0 else 0.95
                    self.silence(src.label, dst_label, ttl=ttl, reason="thermal_silencing")

    def step(self) -> int:
        self._prune_expired()
        self._apply_rhythm_policy()
        self._apply_temperature_policy()
        self._refresh_feature_vectors()
        self._archive_autocatalytic_templates()
        self._prune_expired()
        return len(self._silenced_edges)

    @property
    def silenced_count(self) -> int:
        self._prune_expired()
        return len(self._silenced_edges)

    @property
    def feature_count(self) -> int:
        return len(self._feature_vectors)

    @property
    def template_count(self) -> int:
        return len(self._library_cells)

    def library_templates(self) -> list[LibraryCell]:
        return [self._library_cells[key] for key in sorted(self._library_cells.keys())]

    def _signal_profile(self, src: AtherCell, target: AtherCell) -> tuple[torch.Tensor, torch.Tensor, float]:
        signal_fold = 0.58 * src.fold_signature + 0.42 * target.fold_signature
        signal_fold = signal_fold / (torch.norm(signal_fold, p=2) + 1e-8)
        signal_coord = _project_to_poincare_ball(0.5 * src.poincare_coord + 0.5 * target.poincare_coord)
        entropy_pattern = self.aggregate_entropy_pattern((src.label, target.label))
        return signal_fold, signal_coord, entropy_pattern

    def predictive_gate(
        self,
        src: AtherCell,
        target: AtherCell,
        raw_transfer: float,
        *,
        protected_edge: bool,
    ) -> Dict[str, float | Optional[str]]:
        adjusted = max(0.0, float(raw_transfer))
        if adjusted <= 0.0:
            self.predictive_absorbed_energy = 0.0
            self.last_predictability = 0.0
            self.last_surprise_signal = 0.0
            self.last_predictive_template = None
            return {
                "transfer": 0.0,
                "predictability": 0.0,
                "surprise": 0.0,
                "absorbed_energy": 0.0,
                "template_label": None,
            }

        best_predictability = 0.0
        best_inhibition = 0.0
        best_label: Optional[str] = None
        templates = self.library_templates()
        if templates:
            signal_fold, signal_coord, entropy_pattern = self._signal_profile(src, target)
            members = (src.label, target.label)
            for template in templates:
                predictability, inhibition = template.predictive_resonance(
                    signal_fold,
                    signal_coord,
                    entropy_pattern=entropy_pattern,
                    member_labels=members,
                )
                score = predictability + 0.35 * inhibition
                best_score = best_predictability + 0.35 * best_inhibition
                if score <= best_score:
                    continue
                best_predictability = predictability
                best_inhibition = inhibition
                best_label = template.label

        damping = max(0.42, 1.0 - 0.78 * best_predictability) if protected_edge else max(0.04, 1.0 - 0.92 * best_predictability)
        adjusted = adjusted * damping
        absorbed = max(0.0, float(raw_transfer) - adjusted)
        signal_strength = min(1.0, float(raw_transfer) / max(0.03, self.core.success_transfer))
        surprise = _clamp((1.0 - best_predictability) * signal_strength, 0.0, 1.0)

        self.predictive_absorbed_energy = absorbed
        self.last_predictability = best_predictability
        self.last_surprise_signal = surprise
        self.last_predictive_template = best_label
        if absorbed > 0.0 and best_label:
            self.predictive_inhibition_events += 1
            self.predictive_total_absorbed_energy += absorbed

        return {
            "transfer": adjusted,
            "predictability": best_predictability,
            "surprise": surprise,
            "absorbed_energy": absorbed,
            "template_label": best_label,
        }


class CognitionLayer:
    def __init__(self, core: "AtheriaCore") -> None:
        self.core = core
        self.epigenetic_registry = EpigeneticRegistry(core)
        self.last_mean_hyperbolic_distance = 0.0
        self.last_morphic_bridge_pressure = 0.0
        self.last_cross_domain_bridges: list[Tuple[str, str]] = []

    def hyperbolic_distance(self, cell_a: AtherCell, cell_b: AtherCell) -> float:
        return poincare_distance(cell_a.poincare_coord, cell_b.poincare_coord)

    def conceptual_proximity_gain(self, cell_a: AtherCell, cell_b: AtherCell) -> float:
        dist = self.hyperbolic_distance(cell_a, cell_b)
        # Near in hyperbolic space => stronger diffusion.
        gain = 0.86 + 0.94 * math.exp(-1.45 * dist)
        return max(0.72, min(1.85, gain))

    def morphic_analogy_bridges(self, limit: int = 3) -> list[tuple[AtherCell, AtherCell, float]]:
        cells = tuple(cell for cell in self.core.cells.values() if not isinstance(cell, LibraryCell))
        if len(cells) < 2:
            return []

        bridges: list[tuple[AtherCell, AtherCell, float]] = []
        for i, src in enumerate(cells):
            for target in cells[i + 1 :]:
                if src.category == target.category:
                    continue
                distance = self.hyperbolic_distance(src, target)
                if distance > 1.02:
                    continue
                resonance = self.core.origami_router.resonance(src, target)
                if resonance < 0.64:
                    continue
                activation_overlap = min(src.activation_value, target.activation_value)
                entropy_pattern = self.epigenetic_registry.aggregate_entropy_pattern((src.label, target.label))
                similarity = _clamp(
                    0.42 * (1.0 / (1.0 + distance))
                    + 0.28 * resonance
                    + 0.18 * entropy_pattern
                    + 0.12 * activation_overlap,
                    0.0,
                    1.0,
                )
                if similarity < 0.66:
                    continue
                bridges.append((src, target, similarity))
        bridges.sort(key=lambda item: item[2], reverse=True)
        return bridges[: max(1, limit)]

    def step(self) -> int:
        cells = tuple(self.core.cells.values())
        if len(cells) > 1:
            sampled = []
            max_pairs = min(12, len(cells) * 2)
            for _ in range(max_pairs):
                a, b = random.sample(cells, 2)
                sampled.append(self.hyperbolic_distance(a, b))
            self.last_mean_hyperbolic_distance = sum(sampled) / max(1, len(sampled))
        else:
            self.last_mean_hyperbolic_distance = 0.0
        silenced = self.epigenetic_registry.step()
        bridges = self.morphic_analogy_bridges(limit=4)
        self.last_cross_domain_bridges = [(src.label, target.label) for src, target, _ in bridges]
        if bridges:
            self.last_morphic_bridge_pressure = sum(score for _, _, score in bridges) / max(1, len(bridges))
        else:
            self.last_morphic_bridge_pressure = 0.0
        return silenced


class EnzymaticOptimizer:
    """
    Atheria_Biosynthesis enzyme layer:
    - Catalase effect: lowers activation energy, compiles hot paths to binary CUDA-like kernels.
    - Protease effect: dissolves malformed logic paths and returns resources.
    """

    def __init__(
        self,
        core: "AtheriaCore",
        *,
        compile_efficiency: float = 0.58,
        compile_usage: int = 6,
        protease_efficiency: float = 0.14,
    ) -> None:
        self.core = core
        self.compile_efficiency = compile_efficiency
        self.compile_usage = compile_usage
        self.protease_efficiency = protease_efficiency
        self.compiled_paths: Dict[str, str] = {}

    def _compile_kernel(self, src: AtherCell, target: AtherCell, conn: AtherConnection) -> None:
        if conn.compiled_kernel:
            return
        is_topo = self.core.topological_logic.is_edge_protected(src.label, target.label)
        kernel_tag = hashlib.sha1(f"{src.label}->{target.label}".encode("utf-8")).hexdigest()[:10]
        prefix = "topo.cuda.bin" if is_topo else "cuda.bin"
        kernel_id = f"{prefix}::{src.label}->{target.label}::{kernel_tag}"
        conn.compiled_kernel = kernel_id
        conn.frozen = True
        if is_topo:
            conn.activation_energy = min(0.04, conn.activation_energy)
            conn.weight = max(0.82, conn.weight)
        else:
            conn.activation_energy = max(0.05, conn.activation_energy * 0.65)
        conn.compute_savings = min(1.0, conn.compute_savings + 0.35)
        self.compiled_paths[f"{src.label}->{target.label}"] = kernel_id

    def _catalase_effect(self, src: AtherCell, conn: AtherConnection) -> None:
        if self.core.topological_logic.is_edge_protected(src.label, conn.target.label):
            conn.frozen = True
            conn.activation_energy = min(0.04, conn.activation_energy)
            conn.weight = max(0.82, conn.weight)
            if conn.compiled_kernel is None:
                self._compile_kernel(src, conn.target, conn)
            return

        interaction = float(conn.usage_count + conn.success_count * 2)
        catalase_level = min(1.0, interaction / 28.0)
        conn.catalytic_flux = 0.82 * conn.catalytic_flux + 0.18 * catalase_level
        conn.activation_energy = max(0.05, conn.activation_energy * (1.0 - 0.05 * catalase_level))
        hot_path = conn.catalytic_flux >= self.core.success_transfer * 0.4
        enough_success = conn.success_count >= 3
        if hot_path and conn.usage_count >= self.compile_usage and (
            conn.efficiency >= self.compile_efficiency or enough_success
        ):
            self._compile_kernel(src, conn.target, conn)

    def _protease_effect(self, src: AtherCell, target_label: str, conn: AtherConnection) -> float:
        if self.core.topological_logic.is_edge_protected(src.label, target_label):
            conn.protease_marks = 0
            return 0.0

        low_resonance = self.core.origami_router.resonance(src, conn.target) < 0.46
        malformed = conn.usage_count >= 8 and conn.efficiency < self.protease_efficiency and low_resonance
        if not malformed:
            conn.protease_marks = max(0, conn.protease_marks - 1)
            return 0.0

        conn.protease_marks += 1
        conn.weight = max(0.01, conn.weight * 0.84)
        conn.activation_energy = min(2.4, conn.activation_energy * 1.06)
        if conn.protease_marks < 3:
            return 0.0

        # Enzymatic decomposition + resource recycling
        reclaimed = 0.75 + conn.weight + conn.compute_savings
        src.remove_connection(target_label)
        return reclaimed

    def step(self) -> float:
        reclaimed_total = 0.0
        for src in tuple(self.core.cells.values()):
            for target_label, conn in tuple(src.connections.items()):
                self._catalase_effect(src, conn)
                reclaimed_total += self._protease_effect(src, target_label, conn)
        return reclaimed_total

    def sleep_cleanup(self, intensity: float = 1.0) -> float:
        reclaimed = 0.0
        purge_threshold = min(0.55, 0.28 + 0.15 * intensity)
        for src in tuple(self.core.cells.values()):
            for target_label, conn in tuple(src.connections.items()):
                if self.core.topological_logic.is_edge_protected(src.label, target_label):
                    continue
                if conn.frozen and conn.efficiency > 0.4:
                    continue
                weak = conn.efficiency < purge_threshold
                sparse_use = conn.usage_count < max(3, int(6 * intensity))
                if weak and sparse_use:
                    reclaimed += 0.4 + conn.weight + conn.compute_savings * 0.5
                    src.remove_connection(target_label)
        return reclaimed


class FieldInference:
    def __init__(self, core: "AtheriaCore") -> None:
        self.core = core

    def infer(self, input_tensor: torch.Tensor, top_k: int = 5) -> Dict[str, object]:
        result = self.core.holographic_field.query_field(
            input_tensor,
            cells=self.core.cells.values(),
            entanglement_registry=self.core.quantum_registry.registry,
            top_k=top_k,
        )
        for entry in result.get("top_matches", []):
            label = entry["label"]
            score = float(entry["score"])
            cell = self.core.cells.get(label)
            if cell and score > 0.35:
                cell.bump_activation(min(0.2, score * 0.2), entangled=True)

        # Anticipatory field projection: pre-activate likely future response zones.
        for entry in result.get("future_top_matches", []):
            label = entry["label"]
            score = float(entry["score"])
            cell = self.core.cells.get(label)
            if cell and score > 0.32:
                cell.bump_activation(min(0.08, score * 0.08), entangled=True)
        return result


class Atheria_Biosynthesis:
    def __init__(self, core: "AtheriaCore", interval: float = 0.2) -> None:
        self.core = core
        self.interval = interval
        self.enzymatic_optimizer = EnzymaticOptimizer(core)
        self.field_inference = FieldInference(core)

    async def run(self) -> None:
        while self.core.running:
            reclaimed = self.enzymatic_optimizer.step()
            if reclaimed > 0.0:
                self.core.assembler.reclaim_resources(reclaimed)
            if self.core.rhythm.state is RhythmState.SLEEP:
                reclaimed_sleep = self.enzymatic_optimizer.sleep_cleanup(intensity=1.15)
                if reclaimed_sleep > 0.0:
                    self.core.assembler.reclaim_resources(reclaimed_sleep)
            await asyncio.sleep(self.interval)


AtheriaBiosynthesis = Atheria_Biosynthesis


class CatalyticAssembler:
    def __init__(
        self,
        core: "AtheriaCore",
        *,
        concentration_threshold: float = 1.8,
        decay: float = 0.92,
        interval: float = 0.35,
    ) -> None:
        self.core = core
        self.concentration_threshold = concentration_threshold
        self.decay = decay
        self.interval = interval
        self.concentrations: Dict[str, float] = {}
        self.resource_pool: float = 3.0
        self.reclaimed_resources: float = 0.0
        self._recent_inputs: Deque[torch.Tensor] = deque(maxlen=32)
        self.autocatalytic_sets: Dict[str, Dict[str, object]] = {}
        self._autocat_counter = 0
        self.autocatalytic_activity: float = 0.0
        self.semantic_analogy_cells = 0
        self.semantic_resource_spent = 0.0
        self.aion_cycles: Dict[str, Dict[str, object]] = {}
        self._aion_counter = 0
        self.aion_cycle_activity = 0.0
        self._last_external_feed_ts = time.perf_counter()
        self.credit_balance: float = 24.0
        self.market_enabled = True
        self.market_need_threshold = 0.52
        self.market_guardian_score = 0.0
        self.market_transactions = 0
        self.market_borrow_events = 0
        self.market_lend_events = 0
        self.market_resources_in = 0.0
        self.market_resources_out = 0.0
        self.market_last_packet_quality = 0.0
        self.market_last_price = 0.0
        self.market_last_partner: Optional[str] = None
        self.last_market_report: Dict[str, Any] = {}
        self._last_market_ts = 0.0

    def feed(
        self,
        category: str,
        relevance: float,
        input_tensor: Optional[torch.Tensor] = None,
        *,
        external: bool = True,
    ) -> None:
        category_key = category.strip() or "Unbekannt"
        self.concentrations[category_key] = self.concentrations.get(category_key, 0.0) + max(0.0, relevance)
        if external:
            self._last_external_feed_ts = time.perf_counter()
        if input_tensor is not None:
            vec = input_tensor.detach().float().flatten()
        else:
            vec = _fold_vector_from_text(category_key, dims=int(self.core.holographic_field.pattern.numel()))
        dims = int(self.core.holographic_field.pattern.numel())
        if vec.numel() < dims:
            vec = torch.nn.functional.pad(vec, (0, dims - vec.numel()))
        elif vec.numel() > dims:
            vec = vec[:dims]
        vec = vec / (torch.norm(vec, p=2) + 1e-8)
        self._recent_inputs.append(vec)

    def reclaim_resources(self, amount: float) -> None:
        gained = max(0.0, float(amount))
        self.reclaimed_resources += gained
        self.resource_pool += gained

    def market_need_score(self) -> float:
        scarcity = _clamp(self.core.ecology.resource_scarcity, 0.0, 1.0)
        heat = _clamp((self.core.phase_controller.system_temperature - 52.0) / 52.0, 0.0, 1.0)
        reserve_pressure = _clamp((9.0 - self.resource_pool) / 9.0, 0.0, 1.0)
        local_entropy = sum(float(v) for v in self.core.phase_controller.local_entropy.values())
        entropy_load = _clamp(math.tanh(local_entropy / 60.0), 0.0, 1.0)
        return _clamp(0.34 * scarcity + 0.28 * heat + 0.22 * entropy_load + 0.16 * reserve_pressure, 0.0, 1.0)

    def guardian_score(self) -> float:
        coolness = 1.0 - _clamp(self.core.phase_controller.system_temperature / 100.0, 0.0, 1.0)
        abundance = math.tanh(max(0.0, self.resource_pool) / 30.0)
        purpose = _clamp(self.core.transcendence.last_purpose_alignment, 0.0, 1.0)
        morphic = _clamp(self.core.holographic_field.last_morphic_resonance_index, 0.0, 1.0)
        survival_bonus = 0.08 if self.core.reproduction.last_artifact_profile == "survival" else 0.0
        score = _clamp(0.35 * coolness + 0.3 * abundance + 0.2 * purpose + 0.15 * morphic + survival_bonus, 0.0, 1.0)
        self.market_guardian_score = score
        return score

    def market_role(self) -> str:
        guardian = self.guardian_score()
        need = self.market_need_score()
        if guardian >= 0.72 and self.resource_pool >= 18.0:
            return "guardian"
        if need >= self.market_need_threshold:
            return "borrower"
        return "balanced"

    def export_efficiency_packet(self) -> Dict[str, Any]:
        kernels: list[str] = []
        top_edges: list[tuple[float, AtherConnection]] = []
        for cell in self.core.cells.values():
            for conn in cell.connections.values():
                score = (conn.efficiency + 0.1) * (1.0 + 0.03 * conn.usage_count)
                top_edges.append((score, conn))
                if conn.compiled_kernel:
                    kernels.append(conn.compiled_kernel)
        top_edges.sort(key=lambda item: item[0], reverse=True)
        entropy_damp_values = [
            float(mech.get("entropy_damp", 0.0)) for mech in self.core.evolution.runtime_mechanisms.values()
        ]
        coherence_gain_values = [
            float(mech.get("coherence_gain", 0.0)) for mech in self.core.evolution.runtime_mechanisms.values()
        ]
        return {
            "source_core_id": self.core.core_id,
            "timestamp": round(time.time(), 6),
            "stability": round(self.guardian_score(), 6),
            "entropy_damp_hint": round(
                sum(entropy_damp_values) / max(1, len(entropy_damp_values)),
                6,
            ),
            "coherence_gain_hint": round(
                sum(coherence_gain_values) / max(1, len(coherence_gain_values)),
                6,
            ),
            "top_edge_energies": [
                round(conn.activation_energy, 6)
                for _, conn in top_edges[:6]
            ],
            "compiled_kernels": sorted(set(kernels))[:8],
            "program_signatures": sorted(
                {
                    str(mech.get("program_signature", ""))
                    for mech in self.core.evolution.runtime_mechanisms.values()
                    if mech.get("program_signature")
                }
            )[:6],
            "field_pattern": self.core.holographic_field.pattern.detach().tolist(),
        }

    def ingest_efficiency_packet(self, packet: Dict[str, Any]) -> float:
        if not isinstance(packet, dict):
            return 0.0

        stability = _clamp(float(packet.get("stability", 0.0)), 0.0, 1.0)
        entropy_damp_hint = _clamp(float(packet.get("entropy_damp_hint", 0.0)), 0.0, 1.0)
        coherence_hint = _clamp(float(packet.get("coherence_gain_hint", 0.0)), 0.0, 1.0)

        tuned = 0
        for cell in self.core.cells.values():
            if not cell.connections:
                continue
            candidates = sorted(
                cell.connections.values(),
                key=lambda conn: (conn.usage_count, conn.efficiency, conn.catalytic_flux),
                reverse=True,
            )
            for conn in candidates[:2]:
                before = conn.activation_energy
                conn.activation_energy = max(0.04, before * (1.0 - 0.06 * stability))
                conn.catalytic_flux = min(1.5, conn.catalytic_flux + 0.03 * stability + 0.02 * coherence_hint)
                if conn.activation_energy < before:
                    tuned += 1

        if self.core.phase_controller.local_entropy:
            damp = 1.0 - 0.12 * entropy_damp_hint
            for key in list(self.core.phase_controller.local_entropy.keys()):
                self.core.phase_controller.local_entropy[key] *= damp

        pattern = packet.get("field_pattern")
        if isinstance(pattern, list) and pattern:
            try:
                vec = torch.tensor(pattern, dtype=torch.float32).flatten()
                dims = int(self.core.holographic_field.pattern.numel())
                if vec.numel() < dims:
                    vec = torch.nn.functional.pad(vec, (0, dims - vec.numel()))
                elif vec.numel() > dims:
                    vec = vec[:dims]
                vec = vec / (torch.norm(vec, p=2) + 1e-8)
                self.core.holographic_field.pattern = torch.tanh(
                    0.93 * self.core.holographic_field.pattern + 0.07 * vec
                )
            except Exception:
                pass

        signatures = packet.get("program_signatures")
        if isinstance(signatures, list):
            for signature in signatures[:2]:
                self.feed(
                    category=f"MarketHint_{str(signature)[:10]}",
                    relevance=min(0.2, 0.06 + 0.1 * stability),
                    input_tensor=self.core.holographic_field.pattern,
                    external=False,
                )

        quality = _clamp(0.45 * stability + 0.35 * entropy_damp_hint + 0.2 * coherence_hint, 0.0, 1.0)
        self.market_last_packet_quality = quality
        return quality

    def transact_with_peer(
        self,
        peer_core: Optional["AtheriaCore"] = None,
        *,
        force: bool = False,
        requested_units: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        report = GLOBAL_ATHER_CREDIT_MARKET.execute_rental(
            borrower=self.core,
            lender=peer_core,
            requested_units=requested_units,
            force=force,
        )
        if report:
            self.last_market_report = report
        return report

    def _resource_market_step(self) -> None:
        if not self.market_enabled:
            return
        if self.core.aion_meditation_mode:
            return
        now = time.perf_counter()
        if (now - self._last_market_ts) < 1.1:
            return
        self._last_market_ts = now
        need = self.market_need_score()
        if need < self.market_need_threshold:
            return
        self.transact_with_peer(force=False)

    def _creative_gap_categories(self) -> list[tuple[str, float]]:
        if not self._recent_inputs:
            return []
        observed = torch.mean(torch.stack(list(self._recent_inputs), dim=0), dim=0)
        field = self.core.holographic_field.pattern
        gap = torch.relu(observed - field)
        gap_norm = float(torch.norm(gap, p=2))
        if gap_norm < 0.2:
            return []
        top_k = min(3, int(gap.numel()))
        top_values, top_indices = torch.topk(gap, k=top_k)
        candidates: list[tuple[str, float]] = []
        for value, idx in zip(top_values.tolist(), top_indices.tolist()):
            if value <= 0.05:
                continue
            category = f"Kreativluecke_{idx}"
            candidates.append((category, float(value) * (1.0 + gap_norm)))
        return candidates

    def _assemble_cell(self, category: str, concentration: float) -> None:
        assembly_cost = max(0.25, 1.1 - concentration * 0.08)
        if self.resource_pool < assembly_cost:
            return
        self.resource_pool -= assembly_cost

        cell = self.core.add_cell(
            category,
            category=category,
            semipermeability=max(0.45, min(0.95, 0.45 + concentration * 0.12)),
        )
        peers = [peer for peer in self.core.cells.values() if peer.label != cell.label]
        peers.sort(key=lambda peer: self.core.origami_router.resonance(cell, peer), reverse=True)
        for peer in peers[:3]:
            resonance = self.core.origami_router.resonance(cell, peer)
            if resonance < 0.6:
                continue
            if peer.label not in cell.connections:
                cell.add_connection(peer, weight=0.25 + 0.55 * resonance)
            if cell.label not in peer.connections and resonance > 0.78:
                peer.add_connection(cell, weight=0.2 + 0.5 * resonance)

    def _semantic_analogy_candidates(self) -> list[tuple[AtherCell, AtherCell, float]]:
        cells = tuple(self.core.cells.values())
        if len(cells) < 2:
            return []
        bridge_pressure = getattr(self.core.cognition, "last_morphic_bridge_pressure", 0.0)
        distance_limit = 1.15 if self.core.aion_meditation_mode else 0.95 + 0.12 * bridge_pressure
        resonance_limit = 0.7 if self.core.aion_meditation_mode else 0.78
        similarity_limit = 0.68 if self.core.aion_meditation_mode else 0.74 - 0.06 * bridge_pressure
        candidates: list[tuple[AtherCell, AtherCell, float]] = []
        for i, src in enumerate(cells):
            for target in cells[i + 1 :]:
                if src.label == target.label:
                    continue
                if src.category == target.category:
                    continue
                if self.core.topological_logic.is_cell_protected(src.label) and self.core.topological_logic.is_cell_protected(
                    target.label
                ):
                    continue
                distance = self.core.cognition.hyperbolic_distance(src, target)
                if distance > distance_limit:
                    continue
                resonance = self.core.origami_router.resonance(src, target)
                if resonance < resonance_limit:
                    continue
                entropy_pattern = self.core.cognition.epigenetic_registry.aggregate_entropy_pattern((src.label, target.label))
                similarity = max(
                    0.0,
                    min(
                        1.0,
                        0.48 * resonance
                        + 0.32 * (1.0 / (1.0 + distance))
                        + 0.14 * entropy_pattern
                        + 0.06 * bridge_pressure,
                    ),
                )
                if similarity < similarity_limit:
                    continue
                candidates.append((src, target, similarity))
        candidates.sort(key=lambda item: item[2], reverse=True)
        return candidates[:2]

    def _assemble_semantic_analog(self, src: AtherCell, target: AtherCell, similarity: float) -> None:
        label = f"Analog_{src.label}_{target.label}"
        if label in self.core.cells:
            return
        cost = max(0.3, 0.95 - similarity * 0.4)
        if self.resource_pool < cost:
            return
        self.resource_pool -= cost
        self.semantic_resource_spent += cost

        category = f"Analogy::{src.category}~{target.category}"
        analog = self.core.add_cell(
            label,
            category=category,
            semipermeability=max(0.5, min(0.96, (src.semipermeability + target.semipermeability) * 0.55)),
        )
        analog.fold_signature = (
            0.5 * src.fold_signature + 0.5 * target.fold_signature
        ) / (torch.norm(0.5 * src.fold_signature + 0.5 * target.fold_signature, p=2) + 1e-8)
        midpoint = 0.5 * src.poincare_coord + 0.5 * target.poincare_coord
        analog.poincare_coord = _project_to_poincare_ball(midpoint)

        analog.add_connection(src, weight=0.5 + 0.4 * similarity)
        analog.add_connection(target, weight=0.5 + 0.4 * similarity)
        src.add_connection(analog, weight=0.42 + 0.36 * similarity)
        target.add_connection(analog, weight=0.42 + 0.36 * similarity)
        self.semantic_analogy_cells += 1

    def _set_exists(self, members: Set[str]) -> bool:
        for existing in self.autocatalytic_sets.values():
            if set(existing["members"]) == members:
                return True
        return False

    def _register_autocatalytic_set(self, members: Set[str], catalyst: float) -> None:
        if len(members) < 2 or self._set_exists(members):
            return
        self._autocat_counter += 1
        set_id = f"AUTOSET_{self._autocat_counter:03d}"
        potency = max(0.3, min(1.0, catalyst))
        self.autocatalytic_sets[set_id] = {
            "members": sorted(members),
            "potency": potency,
            "age": 0,
        }

    def _grow_autocatalytic_sets(self) -> None:
        cells = tuple(self.core.cells.values())
        if len(cells) < 2:
            return

        pair_scores: list[tuple[float, AtherCell, AtherCell]] = []
        for i, src in enumerate(cells):
            for target in cells[i + 1 :]:
                if self.core.topological_logic.is_edge_protected(src.label, target.label):
                    continue
                if self.core.topological_logic.is_edge_protected(target.label, src.label):
                    continue
                resonance = self.core.origami_router.resonance(src, target)
                if resonance < 0.72:
                    continue
                src_conn = src.connections.get(target.label)
                dst_conn = target.connections.get(src.label)
                flux = 0.0
                if src_conn:
                    flux += src_conn.catalytic_flux
                if dst_conn:
                    flux += dst_conn.catalytic_flux
                score = resonance * (1.0 + flux)
                pair_scores.append((score, src, target))

        if not pair_scores:
            return
        pair_scores.sort(key=lambda item: item[0], reverse=True)
        top_pairs = pair_scores[:2]

        for score, src, target in top_pairs:
            members = {src.label, target.label}
            if self._set_exists(members):
                continue
            if target.label not in src.connections:
                src.add_connection(target, weight=0.74)
            if src.label not in target.connections:
                target.add_connection(src, weight=0.74)
            src_conn = src.connections[target.label]
            tgt_conn = target.connections[src.label]
            src_conn.activation_energy = max(0.05, src_conn.activation_energy * 0.72)
            tgt_conn.activation_energy = max(0.05, tgt_conn.activation_energy * 0.72)
            self._register_autocatalytic_set(members, catalyst=min(1.0, score))

    def _autocatalytic_maintenance(self) -> None:
        if self.core.aion_meditation_mode:
            self.autocatalytic_activity *= 0.95
            return
        if not self.autocatalytic_sets:
            self.autocatalytic_activity *= 0.9
            return

        total_concentration = sum(self.concentrations.values())
        external_quiet = total_concentration < 0.2
        maintenance_gain = 0.0

        for set_id in list(self.autocatalytic_sets.keys()):
            data = self.autocatalytic_sets[set_id]
            members = [self.core.cells[label] for label in data["members"] if label in self.core.cells]
            if len(members) < 2:
                self.autocatalytic_sets.pop(set_id, None)
                continue

            potency = float(data["potency"])
            data["age"] = int(data["age"]) + 1

            if external_quiet:
                pulse = min(0.06, 0.015 + potency * 0.05)
                for idx, cell in enumerate(members):
                    target = members[(idx + 1) % len(members)]
                    cell.bump_activation(pulse, source=target)
                    conn = cell.connections.get(target.label)
                    if conn:
                        conn.catalytic_flux = min(1.5, conn.catalytic_flux + pulse)
                        conn.success_count += 1
                        conn.usage_count += 1
                self.core.phase_controller.structural_tension = min(
                    1.0,
                    self.core.phase_controller.structural_tension + 0.01 * potency,
                )
                maintenance_gain += pulse * len(members)

            data["potency"] = max(0.15, min(1.0, potency * 0.997 + 0.003))
            if int(data["age"]) > 1200 and float(data["potency"]) < 0.2:
                self.autocatalytic_sets.pop(set_id, None)

        self.autocatalytic_activity = 0.85 * self.autocatalytic_activity + 0.15 * maintenance_gain

    def _quiet_duration(self) -> float:
        return max(0.0, time.perf_counter() - self._last_external_feed_ts)

    def _register_aion_cycle(self, members: list[str], stability: float) -> None:
        if len(members) < 3:
            return
        self._aion_counter += 1
        cycle_id = f"AION_{self._aion_counter:03d}"
        self.aion_cycles[cycle_id] = {
            "members": list(members),
            "stability": max(0.25, min(1.0, stability)),
            "age": 0,
        }

    def _grow_aion_cycles(self) -> None:
        quiet = self._quiet_duration()
        if quiet < 1.15:
            return
        if self.resource_pool < 0.9:
            return
        if len(self.aion_cycles) >= 5:
            return

        candidate_pool: list[str] = []
        for meta in self.autocatalytic_sets.values():
            candidate_pool.extend(meta["members"])
        if not candidate_pool:
            candidate_pool.extend(
                [label for label, cell in self.core.cells.items() if cell.label != self.core.aion.singularity_label]
            )

        deduped = []
        for label in candidate_pool:
            if label in self.core.cells and label not in deduped:
                deduped.append(label)
        if len(deduped) < 3:
            return

        members = deduped[:3]
        base_res = []
        for label in members:
            cell = self.core.cells[label]
            base_res.append(1.0 / (1.0 + float(torch.norm(cell.poincare_coord, p=2))))
        stability = sum(base_res) / max(1, len(base_res))
        self._register_aion_cycle(members, stability=stability)
        self.resource_pool -= 0.6

        for idx, src_label in enumerate(members):
            dst_label = members[(idx + 1) % len(members)]
            src = self.core.cells[src_label]
            dst = self.core.cells[dst_label]
            if dst_label not in src.connections:
                src.add_connection(dst, weight=0.68)
            conn = src.connections[dst_label]
            conn.frozen = True
            conn.activation_energy = max(0.05, conn.activation_energy * 0.74)
            conn.catalytic_flux = min(1.5, conn.catalytic_flux + 0.08)

    def _maintain_aion_cycles(self) -> None:
        if self.core.aion_meditation_mode:
            self.aion_cycle_activity *= 0.95
            return
        if not self.aion_cycles:
            self.aion_cycle_activity *= 0.9
            return

        quiet = self._quiet_duration()
        gain = 0.0
        for cycle_id in list(self.aion_cycles.keys()):
            data = self.aion_cycles[cycle_id]
            members = [self.core.cells[label] for label in data["members"] if label in self.core.cells]
            if len(members) < 3:
                self.aion_cycles.pop(cycle_id, None)
                continue

            stability = float(data["stability"])
            data["age"] = int(data["age"]) + 1
            pulse = min(0.08, 0.012 + stability * (0.03 if quiet >= 0.8 else 0.015))
            for idx, cell in enumerate(members):
                nxt = members[(idx + 1) % len(members)]
                cell.bump_activation(pulse, source=nxt, entangled=True)
                conn = cell.connections.get(nxt.label)
                if conn:
                    conn.usage_count += 1
                    conn.success_count += 1
                    conn.catalytic_flux = min(1.5, conn.catalytic_flux + pulse)
                    conn.frozen = True
                    conn.activation_energy = max(0.045, conn.activation_energy * 0.985)
                cell.integrity_rate = min(1.0, cell.integrity_rate + 0.008 + 0.01 * stability)
                gain += pulse

            if quiet >= 0.8:
                data["stability"] = min(1.0, stability + 0.004)
            else:
                data["stability"] = max(0.2, stability * 0.997)

            if int(data["age"]) > 1800 and float(data["stability"]) < 0.24:
                self.aion_cycles.pop(cycle_id, None)

        self.aion_cycle_activity = 0.84 * self.aion_cycle_activity + 0.16 * gain

    def step(self) -> None:
        self._resource_market_step()
        for category, gap_boost in self._creative_gap_categories():
            self.concentrations[category] = self.concentrations.get(category, 0.0) + gap_boost

        if not self.concentrations:
            self._grow_aion_cycles()
            self._grow_autocatalytic_sets()
            self._autocatalytic_maintenance()
            self._maintain_aion_cycles()
            return
        for category in list(self.concentrations.keys()):
            concentration = self.concentrations.get(category, 0.0)
            if concentration >= self.concentration_threshold:
                self._assemble_cell(category, concentration)
                self.concentrations[category] = concentration * 0.38
            else:
                self.concentrations[category] = concentration * self.decay
            if self.concentrations[category] < 0.05:
                self.concentrations.pop(category, None)

        for src, target, similarity in self._semantic_analogy_candidates():
            self._assemble_semantic_analog(src, target, similarity)

        self._grow_aion_cycles()
        self._grow_autocatalytic_sets()
        self._autocatalytic_maintenance()
        self._maintain_aion_cycles()

    async def run(self) -> None:
        while self.core.running:
            self.step()
            await asyncio.sleep(self.interval)


class PhaseController:
    def __init__(self, base_temperature: float = 25.0) -> None:
        self.system_temperature = base_temperature
        self._external_delta = 0.0
        self.local_entropy: Dict[str, float] = {}
        self.structural_tension: float = 0.0
        self.last_tensegrity_support: int = 0
        self.logging_enabled = True

    @property
    def current_state(self) -> AggregateState:
        if self.system_temperature < 40.0:
            return AggregateState.SOLID
        if self.system_temperature < 80.0:
            return AggregateState.LIQUID
        return AggregateState.PLASMA

    def inject_temperature(self, delta: float) -> None:
        self._external_delta += delta

    def spike_local_entropy(self, label: str, magnitude: float = 20.0) -> None:
        self.local_entropy[label] = self.local_entropy.get(label, 0.0) + magnitude

    def update(
        self,
        *,
        active_nodes: int,
        total_nodes: int,
        cpu_load: float,
        modulators: NeuroModulators,
    ) -> float:
        global System_Temperature

        active_ratio = active_nodes / max(1, total_nodes)
        entropy_heat = sum(self.local_entropy.values()) * 0.08
        target = (
            22.0
            + cpu_load * 0.35
            + active_ratio * 48.0
            + entropy_heat
            + modulators.adrenaline * 9.5
            - modulators.serotonin * 8.0
            + self._external_delta
        )
        self.system_temperature = max(0.0, min(120.0, 0.82 * self.system_temperature + 0.18 * target))
        self._external_delta = 0.0

        self.local_entropy = {
            label: entropy * 0.9
            for label, entropy in self.local_entropy.items()
            if entropy * 0.9 > 0.1
        }

        if self.current_state is AggregateState.PLASMA:
            instability = min(1.0, max(0.0, (self.system_temperature - 80.0) / 40.0))
            self.structural_tension = min(1.0, 0.78 * self.structural_tension + 0.22 * (0.45 + instability))
        else:
            self.structural_tension = max(0.0, self.structural_tension * 0.9)

        self.logging_enabled = self.current_state is not AggregateState.PLASMA
        System_Temperature = self.system_temperature
        return self.system_temperature

    def apply_tensegrity(
        self,
        cells: Iterable[AtherCell],
        origami_router: OrigamiRouter,
        topological_logic: Optional[TopologicalLogic] = None,
    ) -> int:
        """
        Tensegrity_Logic:
        in plasma the system keeps mechanical code tension and reinforces highly resonant paths.
        """
        if self.current_state is not AggregateState.PLASMA:
            self.last_tensegrity_support = 0
            return 0

        edges: list[tuple[float, AtherCell, AtherConnection]] = []
        for src in cells:
            for conn in src.connections.values():
                resonance = origami_router.resonance(src, conn.target)
                edges.append((resonance, src, conn))

        if not edges:
            self.last_tensegrity_support = 0
            return 0

        edges.sort(key=lambda item: item[0], reverse=True)
        support_budget = max(1, int(1 + self.structural_tension * 6))
        supported = 0

        for resonance, src, conn in edges[:support_budget]:
            if topological_logic and topological_logic.is_edge_protected(src.label, conn.target.label):
                conn.frozen = True
                conn.activation_energy = min(0.04, conn.activation_energy)
                conn.weight = max(0.82, conn.weight)
                supported += 1
                continue
            conn.frozen = True
            conn.weight = min(1.8, conn.weight + 0.03 * resonance)
            conn.activation_energy = max(0.04, conn.activation_energy * (1.0 - 0.08 * resonance))
            src.integrity_rate = min(1.0, src.integrity_rate + 0.018 + 0.02 * self.structural_tension)
            conn.target.integrity_rate = min(
                1.0,
                conn.target.integrity_rate + 0.012 + 0.016 * self.structural_tension,
            )
            supported += 1

        self.last_tensegrity_support = supported
        return supported


class QuantumRegistry:
    """Observer-based immediate synchronization."""

    def __init__(self) -> None:
        self.registry = Entanglement_Registry

    def entangle(self, var_a: AtherCell, var_b: AtherCell) -> None:
        self.registry.setdefault(var_a.label, set()).add(var_b.label)
        self.registry.setdefault(var_b.label, set()).add(var_a.label)

        def sync_a_to_b(value: float, emitter: AtherCell, source: Optional[AtherCell], _entangled: bool) -> None:
            if emitter is not var_a:
                return
            if source is var_b:
                return
            var_b.set_activation(value, source=var_a, entangled=True)

        def sync_b_to_a(value: float, emitter: AtherCell, source: Optional[AtherCell], _entangled: bool) -> None:
            if emitter is not var_b:
                return
            if source is var_a:
                return
            var_a.set_activation(value, source=var_b, entangled=True)

        var_a.watch(sync_a_to_b)
        var_b.watch(sync_b_to_a)


def entangle(var_a: AtherCell, var_b: AtherCell, registry: Optional[QuantumRegistry] = None) -> None:
    (registry or QuantumRegistry()).entangle(var_a, var_b)


class AtherHealing:
    def __init__(
        self,
        core: "AtheriaCore",
        *,
        integrity_threshold: float = 0.35,
        silent_limit: int = 20,
        error_limit: int = 3,
        interval: float = 0.25,
    ) -> None:
        self.core = core
        self.integrity_threshold = integrity_threshold
        self.silent_limit = silent_limit
        self.error_limit = error_limit
        self.interval = interval
        self.healing_events = 0
        self.last_repaired_labels: Deque[str] = deque(maxlen=16)

    def detect_necrosis(self, cell: AtherCell) -> bool:
        if self.core.topological_logic.is_cell_protected(cell.label):
            cell.integrity_rate = max(0.995, cell.integrity_rate)
            cell.error_counter = max(0, cell.error_counter - 1)
            return False
        return (
            cell.integrity_rate < self.integrity_threshold
            or cell.silent_epochs >= self.silent_limit
            or cell.error_counter >= self.error_limit
        )

    def handle_crash(self, cell: AtherCell, exc: Exception) -> None:
        if self.core.topological_logic.is_cell_protected(cell.label):
            cell.integrity_rate = max(0.995, cell.integrity_rate)
            logger.error("Crash in protected topological cell '%s': %s | runtime stayed deterministic", cell.label, exc)
            return
        cell.record_error()
        self.core.phase_controller.spike_local_entropy(cell.label, magnitude=35.0)
        self._rewrite_cell_runtime(cell)
        logger.error("Crash in cell '%s': %s", cell.label, exc)

    def _rewrite_cell_runtime(self, cell: AtherCell) -> None:
        async def safe_diffuse(this_cell: AtherCell, core: "AtheriaCore") -> int:
            this_cell.integrity_rate = min(1.0, this_cell.integrity_rate + 0.03)
            if this_cell.activation_value < 0.02:
                this_cell.set_activation(0.02)
            return 0

        cell.diffuse_process = types.MethodType(safe_diffuse, cell)

    def _select_donor(self, candidates: Iterable[AtherCell], excluded_label: str) -> Optional[AtherCell]:
        healthy = [
            cell
            for cell in candidates
            if cell.label != excluded_label and not cell.is_necrotic and cell.integrity_rate > 0.6
        ]
        if not healthy:
            return None
        return max(
            healthy,
            key=lambda cell: (sum(cell.activation_history) + cell.integrity_rate * 10.0),
        )

    async def repair(self, necrotic: AtherCell) -> None:
        if necrotic.is_necrotic:
            return
        necrotic.is_necrotic = True
        self.core.phase_controller.spike_local_entropy(necrotic.label, magnitude=45.0)

        incoming: list[Tuple[AtherCell, float]] = []
        for cell in self.core.cells.values():
            if necrotic.label in cell.connections:
                incoming.append((cell, cell.connections[necrotic.label].weight))
                cell.remove_connection(necrotic.label)

        necrotic.connections.clear()
        donor = self._select_donor((src for src, _ in incoming), excluded_label=necrotic.label)
        if donor is None:
            donor = self._select_donor(self.core.cells.values(), excluded_label=necrotic.label)
        if donor is None:
            self.core.holographic_field.reconstruct(necrotic)
            necrotic.integrity_rate = max(0.5, necrotic.integrity_rate)
            necrotic.is_necrotic = False
            return

        donor_semipermeability, donor_weights = donor.blueprint()
        necrotic.semipermeability = donor_semipermeability
        necrotic.activation_history = deque(donor.activation_history, maxlen=128)
        necrotic.set_activation(max(0.1, donor.activation_value * 0.7), source=donor)

        for target_label, weight in donor_weights.items():
            target = self.core.cells.get(target_label)
            if target is None or target.label == necrotic.label:
                continue
            necrotic.add_connection(target, weight=weight)

        for src, in_weight in incoming:
            src.add_connection(necrotic, weight=max(0.05, in_weight))

        # Osmotic injection from donor to reconstructed area.
        donor.bump_activation(0.12)
        donor.add_connection(necrotic, weight=0.9)

        necrotic.error_counter = 0
        necrotic.silent_epochs = 0
        necrotic.integrity_rate = 0.92
        necrotic.is_necrotic = False
        self.healing_events += 1
        self.last_repaired_labels.append(necrotic.label)
        self.core.aether.upsert_cell(necrotic)

    async def run(self) -> None:
        while self.core.running:
            for cell in tuple(self.core.cells.values()):
                if self.detect_necrosis(cell):
                    await self.repair(cell)
            await asyncio.sleep(self.interval)


class AtheriaCore:
    def __init__(self, tick_interval: float = 0.05, modulators: Optional[NeuroModulators] = None) -> None:
        self.core_id = f"ATHERIA_CORE_{uuid.uuid4().hex[:10].upper()}"
        self.population_registry = GLOBAL_CORE_REGISTRY
        self.global_morphic_node = GLOBAL_MORPHIC_NODE
        self.global_symbol_atlas = GLOBAL_SYMBOL_ATLAS
        self.global_credit_market = GLOBAL_ATHER_CREDIT_MARKET
        self.cells: Dict[str, AtherCell] = {}
        self.aether = AtherAether()
        self.phase_controller = PhaseController()
        self.quantum_registry = QuantumRegistry()
        self.origami_router = OrigamiRouter()
        self.holographic_field = HolographicField(dims=12)
        self.entropic_folding = EntropicFoldingAlgorithm(self.phase_controller, self.origami_router)
        self.modulators = modulators or GLOBAL_NEUROTRANSMITTERS
        self.healing = AtherHealing(self)
        self.assembler = CatalyticAssembler(self)
        self.topological_logic = TopologicalLogic(self)
        self.cognition = CognitionLayer(self)
        self.aion = AionLayer(self)
        self.transcendence = TranscendenceLayer(self)
        self.symbolics = SymbolGroundingLayer(self)
        self.episodic_memory = EpisodicMemoryLayer(self)
        self.reflective_deliberation = ReflectiveDeliberationLayer(self)
        self.executive = ExecutiveFunctionLayer(self)
        self.metacognition = MetaCognitionLayer(self)
        self.safety = SafetyConstraintLayer(self)
        self.tools = ToolRegistry(self)
        self.proposals = ProposalApplier(self)
        self.causal_model = CausalInterventionLayer(self)
        self.action_policy = ActionPolicyLayer(self)
        self.alchemy = AlchemyIngestor(self)
        self.market_alchemy = MarketAlchemyAdapter(self)
        self.lineage_auditor = LineageAuditor(self)
        self.inter_core_resonance = InterCoreResonanceAuditor(self)
        self.evolution = EvolutionEngine(self)
        self.symbiosis = SymbiosisLayer(self)
        self.reproduction = SelfReproductionEngine(self)
        self.ecology = EcoDynamicsEngine(self)
        self.biosynthesis = Atheria_Biosynthesis(self)
        self.rhythm = Atheria_Rhythm(self)

        self.tick_interval = tick_interval
        self.running = False
        self._tasks: list[asyncio.Task] = []
        self._last_tick = time.perf_counter()
        self._flow_count = 0
        self._fold_tick = 0

        self.min_transfer = 0.0005
        self.success_transfer = 0.03
        self.aion_meditation_mode = False
        self.external_feeds_enabled = True
        self._meditation_history: Deque[Dict[str, float]] = deque(maxlen=4096)
        self._last_morphic_snapshot_path: Optional[str] = None

    def add_cell(
        self,
        label: str,
        *,
        semipermeability: float = 0.7,
        category: Optional[str] = None,
        archetype: str = "baseline",
        archetype_traits: Optional[Dict[str, float]] = None,
    ) -> AtherCell:
        if label in self.cells:
            return self.cells[label]
        cell = AtherCell(
            label=label,
            category=category or label,
            semipermeability=semipermeability,
            archetype=archetype,
            archetype_traits=archetype_traits or {},
        )
        self.cells[label] = cell
        self.aether.upsert_cell(cell)
        return cell

    def connect(self, source_label: str, target_label: str, weight: Optional[float] = None) -> None:
        source = self.cells[source_label]
        target = self.cells[target_label]
        source.add_connection(target, weight=weight)

    def entangle(self, label_a: str, label_b: str) -> None:
        self.quantum_registry.entangle(self.cells[label_a], self.cells[label_b])

    def _allow_external_feed(self) -> bool:
        return self.external_feeds_enabled and not self.aion_meditation_mode

    def inject_signal(self, label: str, activation: float) -> None:
        if not self._allow_external_feed():
            return
        adjusted = self.rhythm.filter_input(activation)
        if adjusted < 0.002:
            return
        self.cells[label].set_activation(adjusted)

    def set_superposition(self, label: str, alpha: float = 0.7071, beta: float = 0.7071, enzyme: float = 0.92) -> None:
        if not self._allow_external_feed():
            return
        self.cells[label].set_superposition(alpha=alpha, beta=beta, enzyme=enzyme)

    def chemical_measure(self, label: str, probe: float = 0.5) -> float:
        return self.cells[label].chemical_measurement(probe=probe)

    def feed_raw_material(self, *, category: str, relevance: float) -> None:
        if not self._allow_external_feed():
            return
        adjusted = relevance * self.rhythm.input_gain
        if adjusted <= 0.01:
            return
        self.assembler.feed(category=category, relevance=adjusted)

    def feed_field_material(self, *, category: str, relevance: float, input_tensor: torch.Tensor) -> None:
        if not self._allow_external_feed():
            return
        adjusted = relevance * self.rhythm.input_gain
        if adjusted <= 0.01:
            return
        self.assembler.feed(category=category, relevance=adjusted, input_tensor=input_tensor)

    def field_query(self, input_tensor: torch.Tensor, top_k: int = 5) -> Dict[str, object]:
        if self.aion_meditation_mode:
            # Isolation mode: allow read-only introspection without external activation injection.
            return self.holographic_field.query_field(
                input_tensor=torch.zeros_like(input_tensor),
                cells=self.cells.values(),
                entanglement_registry=self.quantum_registry.registry,
                top_k=top_k,
            )
        return self.biosynthesis.field_inference.infer(input_tensor=input_tensor, top_k=top_k)

    def anchor_symbolic_concept(self, *, force: bool = False) -> Optional[Dict[str, Any]]:
        return self.symbolics.anchor_symbol(force=force)

    def set_executive_goal(
        self,
        kind: str,
        *,
        priority: float = 0.72,
        targets: Optional[Iterable[str]] = None,
        origin: str = "external",
    ) -> Dict[str, Any]:
        return self.executive.set_goal(kind, priority=priority, targets=targets, origin=origin)

    def recall_episode(self, *, targets: Optional[Iterable[str]] = None) -> Optional[Dict[str, Any]]:
        return self.episodic_memory.recall_best(target_labels=targets, min_match=0.0)

    def tool_snapshot(self) -> Dict[str, Any]:
        return self.action_policy._tool_snapshot()

    def reflective_tool_plan(self, target_metric: str) -> Optional[Dict[str, Any]]:
        return self.reflective_deliberation.generate_tool_plan(target_metric)

    def generate_reflective_tool_code(self, target_metric: str) -> Optional[str]:
        plan = self.reflective_deliberation.generate_tool_plan(target_metric)
        if not plan:
            return None
        return str(plan.get("code_string", ""))

    def ingest_external_data(self, source_name: str, data_dict: Any) -> Dict[str, Any]:
        return self.alchemy.ingest_external_data(source_name, data_dict)

    def start_market_alchemy(
        self,
        *,
        poll_interval_seconds: Optional[float] = None,
        provider_order: Optional[Iterable[str]] = None,
        symbols: Optional[Iterable[str]] = None,
        transport: Optional[str] = None,
        market_profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.market_alchemy.start(
            poll_interval_seconds=poll_interval_seconds,
            provider_order=provider_order,
            symbols=symbols,
            transport=transport,
            market_profile=market_profile,
        )

    def stop_market_alchemy(self, *, join_timeout: float = 1.0) -> Dict[str, Any]:
        return self.market_alchemy.stop(join_timeout=join_timeout)

    def poll_market_alchemy(
        self,
        *,
        sample_override: Any = None,
        provider_order: Optional[Iterable[str]] = None,
        symbols: Optional[Iterable[str]] = None,
        market_profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.market_alchemy.poll_once(
            sample_override=sample_override,
            provider_order=provider_order,
            symbols=symbols,
            market_profile=market_profile,
        )

    def market_alchemy_status(self) -> Dict[str, Any]:
        return self.market_alchemy.snapshot()

    def audit_lineage(
        self,
        *,
        lineage_root: Optional[str] = None,
        default_profile: str = "survival",
    ) -> Dict[str, Any]:
        return self.lineage_auditor.scan_lineage(
            lineage_root=lineage_root,
            default_profile=default_profile,
        )

    def audit_inter_core_resonance(
        self,
        *,
        primary_report_dir: Optional[str] = None,
        foreign_report_dir: Optional[str] = None,
        primary_domain: str = "crypto",
        foreign_domain: str = "finance",
        observer_label: Optional[str] = None,
        lag_minutes: float = 120.0,
        trigger_asset: Optional[str] = None,
        trigger_threshold: Optional[float] = None,
        target_asset: str = "BTC",
        min_matches: int = 2,
        min_effect_size: float = 0.05,
    ) -> Dict[str, Any]:
        return self.inter_core_resonance.scan_resonance(
            primary_report_dir=primary_report_dir,
            foreign_report_dir=foreign_report_dir,
            primary_domain=primary_domain,
            foreign_domain=foreign_domain,
            observer_label=observer_label,
            lag_minutes=lag_minutes,
            trigger_asset=trigger_asset,
            trigger_threshold=trigger_threshold,
            target_asset=target_asset,
            min_matches=min_matches,
            min_effect_size=min_effect_size,
        )

    def inter_core_resonance_status(self) -> Dict[str, Any]:
        return self.inter_core_resonance.snapshot()

    def run_analysis_tool(self, code_string: str, *, snapshot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        record = self.tools.execute(
            "python_interpreter",
            code_string=code_string,
            snapshot=snapshot or self.tool_snapshot(),
        )
        return record.as_dict()

    async def execute_external_action(
        self,
        action_name: str,
        *,
        target_metric: Optional[str] = None,
        peer_core: Optional["AtheriaCore"] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return await self.action_policy.execute_action(
            action_name,
            target_metric=target_metric,
            peer_core=peer_core,
            metadata=metadata,
        )

    async def test_causal_countermeasure(self, *, target_metric: Optional[str] = None) -> Dict[str, Any]:
        return await self.causal_model.test_countermeasure(target_metric=target_metric)

    def hyperbolic_distance(self, label_a: str, label_b: str) -> float:
        return self.cognition.hyperbolic_distance(self.cells[label_a], self.cells[label_b])

    def discover_peer_cores(self, *, running_only: bool = True) -> list[str]:
        return [core.core_id for core in self.population_registry.peers(self.core_id, running_only=running_only)]

    def system_stress_index(self) -> float:
        heat = _clamp((self.phase_controller.system_temperature - 50.0) / 60.0, 0.0, 1.0)
        local_entropy = sum(float(v) for v in self.phase_controller.local_entropy.values())
        entropy_load = _clamp(math.tanh(local_entropy / 60.0), 0.0, 1.0)
        scarcity = _clamp(self.ecology.resource_scarcity, 0.0, 1.0)
        if self.cells:
            integrity_deficit = _clamp(
                sum(1.0 - _clamp(cell.integrity_rate, 0.0, 1.0) for cell in self.cells.values()) / len(self.cells),
                0.0,
                1.0,
            )
            error_load = _clamp(
                sum(min(6, cell.error_counter) for cell in self.cells.values()) / (len(self.cells) * 6.0),
                0.0,
                1.0,
            )
        else:
            integrity_deficit = 0.0
            error_load = 0.0
        return _clamp(
            0.32 * heat + 0.22 * entropy_load + 0.2 * scarcity + 0.16 * integrity_deficit + 0.1 * error_load,
            0.0,
            1.0,
        )

    def force_reproduction(self) -> Optional[str]:
        return self.reproduction.force_reproduction()

    async def exchange_genes_with(self, peer_core: "AtheriaCore", *, reciprocal: bool = True) -> bool:
        return await self.symbiosis.exchange_with(peer_core, reciprocal=reciprocal)

    def request_resource_rental(
        self,
        peer_core: Optional["AtheriaCore"] = None,
        *,
        requested_units: Optional[float] = None,
        force: bool = False,
    ) -> Optional[Dict[str, Any]]:
        return self.assembler.transact_with_peer(
            peer_core,
            force=force,
            requested_units=requested_units,
        )

    def trigger_collective_dream_sync(self) -> bool:
        before = self.rhythm.inter_core_dream_sync_events
        replay_strength = _clamp(
            max(self.holographic_field.last_uncertainty, self.holographic_field.last_projection_uncertainty) + 0.2,
            0.0,
            1.0,
        )
        self.rhythm._inter_core_dream_sync(
            replay_labels=list(self.rhythm.last_replay_labels),
            replay_strength=replay_strength,
        )
        return self.rhythm.inter_core_dream_sync_events > before

    def dashboard_snapshot(self) -> Dict[str, object]:
        topo = self.topological_logic.snapshot()
        return {
            "aether_density": self.aether.density(),
            "aggregatform": self.phase_controller.current_state.dashboard_name,
            "phase": self.phase_controller.current_state.value,
            "system_temperature": round(self.phase_controller.system_temperature, 2),
            "rhythm_state": self.rhythm.state.value,
            "rhythm_cycle": self.rhythm.cycle_count,
            "structural_tension": round(self.phase_controller.structural_tension, 4),
            "tensegrity_support": self.phase_controller.last_tensegrity_support,
            "active_cells": sum(1 for cell in self.cells.values() if cell.activation_value > 0.02),
            "entropic_index": round(self.entropic_folding.last_index, 4),
            "holographic_energy": round(self.holographic_field.energy, 4),
            "enzymatic_compiled_paths": len(self.biosynthesis.enzymatic_optimizer.compiled_paths),
            "resource_pool": round(self.assembler.resource_pool, 4),
            "ather_credits": round(self.assembler.credit_balance, 4),
            "market_role": self.assembler.market_role(),
            "market_guardian_score": round(self.assembler.market_guardian_score, 6),
            "market_transactions": self.assembler.market_transactions,
            "market_borrow_events": self.assembler.market_borrow_events,
            "market_lend_events": self.assembler.market_lend_events,
            "market_resources_in": round(self.assembler.market_resources_in, 6),
            "market_resources_out": round(self.assembler.market_resources_out, 6),
            "market_last_price": round(self.assembler.market_last_price, 6),
            "market_last_partner": self.assembler.market_last_partner,
            "market_last_packet_quality": round(self.assembler.market_last_packet_quality, 6),
            "autocatalytic_sets": len(self.assembler.autocatalytic_sets),
            "autocatalytic_activity": round(self.assembler.autocatalytic_activity, 6),
            "aion_cycles": len(self.assembler.aion_cycles),
            "aion_cycle_activity": round(self.assembler.aion_cycle_activity, 6),
            "semantic_analogy_cells": self.assembler.semantic_analogy_cells,
            "semantic_resource_spent": round(self.assembler.semantic_resource_spent, 6),
            "evolved_cell_types": max(0, len(self.evolution.cell_type_blueprints) - 1),
            "evolved_runtime_mechanisms": len(self.evolution.runtime_mechanisms),
            "evolution_events": self.evolution.evolution_events,
            "evolution_program_signature": self.evolution.last_program_signature,
            "reproduction_events": self.reproduction.reproduction_events,
            "offspring_instances": len(self.reproduction.offspring_cores),
            "lineage_selection_trials": self.reproduction.selection_total_trials,
            "lineage_selection_child_wins": self.reproduction.selection_child_wins,
            "lineage_selection_parent_wins": self.reproduction.selection_parent_wins,
            "lineage_last_parent_fitness": round(self.reproduction.last_parent_fitness, 6),
            "lineage_last_child_fitness": round(self.reproduction.last_child_fitness, 6),
            "reproduction_artifact_events": self.reproduction.artifact_events,
            "reproduction_artifact_last_profile": self.reproduction.last_artifact_profile,
            "reproduction_artifact_last_path": self.reproduction.last_artifact_path,
            "reproduction_artifact_last_integrity_path": self.reproduction.last_artifact_integrity_path,
            "reproduction_artifact_last_validated": self.reproduction.last_artifact_validated,
            "reproduction_artifact_last_signature": self.reproduction.last_artifact_signature,
            "alchemy_ingest_events": self.alchemy.ingest_events,
            "alchemy_last_source": self.alchemy.last_source,
            "alchemy_last_signal_strength": round(self.alchemy.last_signal_strength, 6),
            "lineage_audit_scans": self.lineage_auditor.scans,
            "lineage_audit_last_profile": self.lineage_auditor.last_recommended_profile,
            "lineage_audit_last_integrity": round(self.lineage_auditor.last_integrity_score, 6),
            "inter_core_resonance_scans": self.inter_core_resonance.scans,
            "inter_core_resonance_invariants": self.inter_core_resonance.learned_invariants,
            "inter_core_resonance_last_confidence": round(self.inter_core_resonance.last_confidence, 6),
            "inter_core_resonance_last_effect": round(self.inter_core_resonance.last_effect_size, 6),
            "inter_core_resonance_last_scan": self.inter_core_resonance.last_scan_signature,
            "ecological_complexity": round(self.ecology.challenge_complexity, 6),
            "selection_pressure": round(self.ecology.selection_pressure, 6),
            "resource_scarcity": round(self.ecology.resource_scarcity, 6),
            "fitness_gradient": round(self.ecology.last_fitness_gradient, 6),
            "epigenetic_silenced_edges": self.cognition.epigenetic_registry.silenced_count,
            "epigenetic_feature_cells": self.cognition.epigenetic_registry.feature_count,
            "epigenetic_library_cells": self.cognition.epigenetic_registry.template_count,
            "epigenetic_entropy_pattern": round(self.cognition.epigenetic_registry.last_extracted_entropy_pattern, 6),
            "predictive_inhibition_events": self.cognition.epigenetic_registry.predictive_inhibition_events,
            "predictive_absorbed_energy": round(self.cognition.epigenetic_registry.predictive_absorbed_energy, 6),
            "predictive_total_absorbed_energy": round(self.cognition.epigenetic_registry.predictive_total_absorbed_energy, 6),
            "predictive_last_predictability": round(self.cognition.epigenetic_registry.last_predictability, 6),
            "predictive_last_surprise": round(self.cognition.epigenetic_registry.last_surprise_signal, 6),
            "predictive_last_template": self.cognition.epigenetic_registry.last_predictive_template,
            "mean_hyperbolic_distance": round(self.cognition.last_mean_hyperbolic_distance, 6),
            "cross_domain_bridges": len(self.cognition.last_cross_domain_bridges),
            "cross_domain_bridge_pressure": round(self.cognition.last_morphic_bridge_pressure, 6),
            "dream_replay_events": self.rhythm.dream_replay_events,
            "dream_last_replay_labels": list(self.rhythm.last_replay_labels),
            "healing_events": self.healing.healing_events,
            "healing_last_repaired_labels": list(self.healing.last_repaired_labels),
            "time_crystal_energy": round(self.aion.time_crystal.last_crystal_energy, 6),
            "time_crystal_targets": len(self.aion.time_crystal.oscillators),
            "singularity_activation": round(self.aion.last_singularity_activation, 6),
            "morphic_resonance_index": round(self.holographic_field.last_morphic_resonance_index, 6),
            "morphic_buffer_states": self.holographic_field.morphic_buffer.size,
            "projection_uncertainty": round(self.holographic_field.last_projection_uncertainty, 6),
            "dream_forward_cycles": self.aion.imagination_cycles,
            "dream_forward_vectors": self.aion.last_imagination_vectors,
            "dream_forward_gap_closures": self.aion.last_imagination_gap_closures,
            "dream_forward_uncertainty": round(self.aion.last_imagination_uncertainty, 6),
            "dream_forward_cost": round(self.aion.last_imagination_cost, 6),
            "intuition_spikes": self.transcendence.intuition.last_spikes,
            "intuition_surprise_events": self.transcendence.intuition.surprise_events,
            "intuition_last_surprise_heat": round(self.transcendence.intuition.last_surprise_heat, 6),
            "intuition_last_surprise_label": self.transcendence.intuition.last_surprise_label,
            "purpose_alignment": round(self.transcendence.last_purpose_alignment, 6),
            "executive_active_goal": (self.executive.active_goal or {}).get("kind"),
            "executive_active_goal_id": (self.executive.active_goal or {}).get("goal_id"),
            "executive_goal_origin": self.executive.last_goal_origin,
            "executive_goal_stack": len(self.executive.goal_stack),
            "executive_plan_cycles": self.executive.plan_cycles,
            "executive_goal_switches": self.executive.goal_switches,
            "executive_completed_goals": self.executive.completed_goals,
            "executive_self_generated_goals": self.executive.self_generated_goals,
            "executive_last_goal_score": round(self.executive.last_goal_score, 6),
            "executive_last_goal_completion": round(self.executive.last_goal_completion, 6),
            "executive_last_plan_signature": self.executive.last_plan_signature,
            "executive_last_plan_steps": list(self.executive.last_plan_steps),
            "episodic_recorded": self.episodic_memory.recorded_episodes,
            "episodic_consolidated": self.episodic_memory.consolidated_count,
            "episodic_recalled": self.episodic_memory.recalled_episodes,
            "episodic_last_episode_id": self.episodic_memory.last_episode_id,
            "episodic_last_episode_goal": self.episodic_memory.last_episode_goal,
            "episodic_last_salience": round(self.episodic_memory.last_episode_salience, 6),
            "episodic_last_recall_match": round(self.episodic_memory.last_recall_match, 6),
            "episodic_last_recall_signature": self.episodic_memory.last_recall_signature,
            "reflective_cycles": self.reflective_deliberation.reflection_cycles,
            "reflective_last_target_metric": self.reflective_deliberation.last_target_metric,
            "reflective_last_episode_id": self.reflective_deliberation.last_selected_episode_id,
            "reflective_last_signature": self.reflective_deliberation.last_reflection_signature,
            "reflective_last_code_hash": self.reflective_deliberation.last_generated_code_hash,
            "reflective_last_rationale": self.reflective_deliberation.last_rationale,
            "reflective_last_correlation_hint": round(self.reflective_deliberation.last_correlation_hint, 6),
            "reflective_last_plan": dict(self.reflective_deliberation.last_plan),
            "metacognitive_confidence": round(self.metacognition.self_model_confidence, 6),
            "metacognitive_prediction_error": round(self.metacognition.last_prediction_error, 6),
            "metacognitive_audits": self.metacognition.audit_cycles,
            "metacognitive_low_confidence_events": self.metacognition.low_confidence_events,
            "metacognitive_goal_redirects": self.metacognition.goal_redirects,
            "metacognitive_last_directive": self.metacognition.last_directive,
            "action_last": self.action_policy.last_action,
            "action_last_target_metric": self.action_policy.last_target_metric,
            "action_last_success": self.action_policy.last_action_success,
            "action_last_score": round(self.action_policy.last_action_score, 6),
            "action_executed": self.action_policy.executed_actions,
            "action_failed": self.action_policy.failed_actions,
            "action_blocked": self.action_policy.blocked_actions,
            "action_external": self.action_policy.external_actions,
            "action_tool_runs": self.action_policy.tool_actions,
            "action_last_tool_record": dict(self.action_policy.last_tool_record),
            "action_last_proposal_id": self.action_policy.last_proposal_id,
            "causal_last_target_metric": self.causal_model.last_target_metric,
            "causal_last_action": self.causal_model.last_chosen_action,
            "causal_last_predicted_effect": round(self.causal_model.last_predicted_effect, 6),
            "causal_last_actual_effect": round(self.causal_model.last_actual_effect, 6),
            "causal_trials": self.causal_model.countermeasure_trials,
            "causal_successes": self.causal_model.countermeasure_successes,
            "causal_updates": self.causal_model.intervention_updates,
            "causal_last_signature": self.causal_model.last_intervention_signature,
            "causal_last_plan": dict(self.causal_model.last_plan),
            "tool_registry_executions": self.tools.executions,
            "tool_registry_failures": self.tools.failures,
            "tool_registry_last_tool": self.tools.last_tool_name,
            "tool_registry_last_record": dict(self.tools.last_record),
            "proposal_applied": self.proposals.applied,
            "proposal_rejected": self.proposals.rejected,
            "proposal_last_id": self.proposals.last_proposal_id,
            "proposal_last_field": self.proposals.last_applied_field,
            "proposal_last_value": round(self.proposals.last_applied_value, 6),
            "safety_blocked_actions": self.safety.blocked_actions,
            "safety_blocked_rewrites": self.safety.blocked_rewrites,
            "safety_goal_rewrites": self.safety.goal_rewrites,
            "safety_goal_rejections": self.safety.goal_rejections,
            "safety_constraint_events": self.safety.constraint_events,
            "safety_audit_events": self.safety.audit_events,
            "safety_audit_failures": self.safety.audit_failures,
            "safety_invariant_violations": self.safety.invariant_violations,
            "safety_last_audit_signature": self.safety.last_audit_signature,
            "safety_persisted_audit_entries": self.safety.persisted_audit_entries,
            "safety_audit_persist_failures": self.safety.audit_persist_failures,
            "safety_last_persisted_audit_path": self.safety.last_persisted_audit_path,
            "safety_last_journal_signature": self.safety.last_journal_signature,
            "safety_last_audit_key_fingerprint": self.safety.last_audit_key_fingerprint,
            "safety_last_persist_error": self.safety.last_persist_error,
            "safety_last_block_reason": self.safety.last_block_reason,
            "safety_last_reviewed_goal": self.safety.last_reviewed_goal,
            "safety_last_authorized_action": self.safety.last_authorized_action,
            "safety_last_authorized_rewrite_policy": self.safety.last_authorized_rewrite_policy,
            "safety_determinism_checks": self.safety.determinism_checks,
            "safety_determinism_failures": self.safety.determinism_failures,
            "safety_last_determinism_signature": self.safety.last_determinism_signature,
            "safety_last_determinism_reason": self.safety.last_determinism_reason,
            "hgt_offers": self.symbiosis.hgt_offers,
            "hgt_accepts": self.symbiosis.hgt_accepts,
            "hgt_rejects": self.symbiosis.hgt_rejects,
            "hgt_received": self.symbiosis.hgt_received,
            "hgt_donated": self.symbiosis.hgt_donated,
            "hgt_bridge_forced": self.symbiosis.bridge_forced_hgt_events,
            "hgt_last_partner": self.symbiosis.last_partner,
            "hgt_last_predicted_purpose_delta": round(self.symbiosis.last_predicted_purpose_delta, 6),
            "hgt_symbol_offers": self.symbiosis.symbol_offers,
            "hgt_symbol_accepts": self.symbiosis.symbol_accepts,
            "hgt_symbol_rejects": self.symbiosis.symbol_rejects,
            "hgt_symbol_received": self.symbiosis.symbol_received,
            "hgt_symbol_donated": self.symbiosis.symbol_donated,
            "hgt_symbol_last_signature": self.symbiosis.last_symbol_signature,
            "inter_core_dream_sync_events": self.rhythm.inter_core_dream_sync_events,
            "inter_core_dream_trauma_events": self.rhythm.inter_core_dream_trauma_events,
            "inter_core_dream_peers": self.rhythm.last_inter_core_peer_count,
            "inter_core_dream_coherence": round(self.rhythm.last_inter_core_coherence, 6),
            "inter_core_dream_trauma_intensity": round(self.rhythm.last_inter_core_trauma_intensity, 6),
            "global_population_size": self.population_registry.count(running_only=True),
            "global_morphic_sync_events": self.global_morphic_node.sync_events,
            "global_trauma_broadcast_events": self.global_morphic_node.trauma_broadcast_events,
            "global_market_transactions": len(self.global_credit_market.transactions),
            "global_market_last_price": round(self.global_credit_market.last_price_per_unit, 6),
            "system_stress_index": round(self.system_stress_index(), 6),
            "symbol_known": len(self.symbolics.known_symbols()),
            "symbol_anchor_events": self.symbolics.anchor_events,
            "symbol_shared_reuses": self.symbolics.shared_symbol_reuses,
            "symbol_last_id": self.symbolics.last_symbol_id,
            "symbol_last_signature": self.symbolics.last_symbol_signature,
            "symbol_last_stability": round(self.symbolics.last_symbol_stability, 6),
            "symbol_last_shared_cores": self.symbolics.last_symbol_shared_cores,
            "symbol_packets_exported": self.symbolics.symbol_packets_exported,
            "symbol_packets_received": self.symbolics.symbol_packets_received,
            "symbol_last_imported_id": self.symbolics.last_imported_symbol_id,
            "global_symbol_count": self.global_symbol_atlas.size,
            "purpose_homeostatic_temperature": round(
                float(getattr(self.cells.get(self.transcendence.telos.purpose_label), "homeostatic_temperature", 34.0)),
                6,
            ),
            "aion_meditation_mode": self.aion_meditation_mode,
            "topological_clusters": topo["clusters"],
            "topological_core_cells": topo["core_cells"],
            "topological_edges": topo["protected_edges"],
            "topological_rule_version": topo["rule_version"],
            "topological_rewrite_events": topo["rewrite_events"],
            "topological_last_rewrite_reason": self.topological_logic.last_rewrite_reason,
            "topological_last_rewrite_signature": self.topological_logic.last_rewrite_signature,
            "topological_last_rewrite_pressure": round(self.topological_logic.last_rewrite_pressure, 6),
            "topological_last_policy": topo["last_policy"],
            "topological_last_policy_score": topo["last_policy_score"],
            "entanglement_registry": {k: sorted(v) for k, v in self.quantum_registry.registry.items()},
        }

    def _topological_core_labels(self) -> list[str]:
        core_labels: Set[str] = set()
        for cluster in self.topological_logic.clusters.values():
            core_labels.update(cluster["core"])
        return sorted(core_labels)

    def _meditation_holy_geometry(self) -> None:
        if not self.aion_meditation_mode:
            return
        core_labels = set(self._topological_core_labels())
        for label in core_labels:
            cell = self.cells.get(label)
            if cell is None:
                continue
            cell.integrity_rate = max(0.995, cell.integrity_rate)
            cell.error_counter = max(0, cell.error_counter - 1)

        excluded = core_labels | {self.aion.singularity_label, self.transcendence.telos.purpose_label}
        mutable = [cell for cell in self.cells.values() if cell.label not in excluded]
        if len(mutable) < 2:
            return

        coords = torch.stack([cell.poincare_coord for cell in mutable], dim=0)
        centroid = torch.mean(coords, dim=0)
        centroid = _project_to_poincare_ball(centroid)
        field_hint = self.holographic_field.pattern[:POINCARE_DIMS]
        field_hint = field_hint / (torch.norm(field_hint, p=2) + 1e-8)
        field_hint = _project_to_poincare_ball(field_hint * 0.72)

        for cell in mutable:
            blended = 0.82 * cell.poincare_coord + 0.14 * centroid + 0.04 * field_hint
            cell.poincare_coord = _project_to_poincare_ball(blended)
            fold = cell.fold_signature.detach().clone()
            coord_hint = torch.nn.functional.pad(cell.poincare_coord, (0, max(0, fold.numel() - cell.poincare_coord.numel())))
            fold = 0.93 * fold + 0.07 * coord_hint[: fold.numel()]
            cell.fold_signature = fold / (torch.norm(fold, p=2) + 1e-8)
            cell.semipermeability = max(0.45, min(0.95, 0.996 * cell.semipermeability + 0.004 * 0.72))

    def _meditation_aura_stabilization(self) -> None:
        if not self.aion_meditation_mode:
            return
        uncertainty = max(
            0.56,
            min(
                1.0,
                0.62
                + 0.22 * (1.0 - self.transcendence.last_purpose_alignment)
                + 0.16 * min(1.0, self.cognition.last_mean_hyperbolic_distance),
            ),
        )
        guide, idx = self.holographic_field.morphic_resonance(uncertainty=uncertainty)
        if idx > 0.0:
            self.holographic_field.pattern = torch.tanh(0.9 * self.holographic_field.pattern + 0.1 * guide)
            boosted = idx + 0.15 * self.transcendence.last_purpose_alignment
            self.holographic_field.last_morphic_resonance_index = max(
                self.holographic_field.last_morphic_resonance_index,
                min(1.0, boosted),
            )

    def _record_meditation_sample(self, snapshot: Dict[str, object]) -> None:
        self._meditation_history.append(
            {
                "t": round(time.perf_counter(), 6),
                "purpose_alignment": float(snapshot["purpose_alignment"]),
                "morphic_resonance_index": float(snapshot["morphic_resonance_index"]),
                "mean_hyperbolic_distance": float(snapshot["mean_hyperbolic_distance"]),
                "resource_pool": float(snapshot["resource_pool"]),
                "semantic_analogy_cells": float(snapshot["semantic_analogy_cells"]),
                "dream_replay_events": float(snapshot["dream_replay_events"]),
            }
        )

    def _create_morphic_snapshot(self, path: str = "morphic_snapshot.json", *, trigger: str) -> Dict[str, object]:
        payload = {
            "timestamp": round(time.time(), 6),
            "trigger": trigger,
            "system_temperature": round(self.phase_controller.system_temperature, 6),
            "purpose_alignment": round(self.transcendence.last_purpose_alignment, 6),
            "morphic_resonance_index": round(self.holographic_field.last_morphic_resonance_index, 6),
            "mean_hyperbolic_distance": round(self.cognition.last_mean_hyperbolic_distance, 6),
            "topological_core_labels": self._topological_core_labels(),
            "topological_rules": self.topological_logic.export_rules(),
            "field_pattern": self.holographic_field.pattern.detach().tolist(),
            "future_projection": self.holographic_field.last_future_projection.detach().tolist(),
            "morphic_buffer": self.holographic_field.morphic_buffer.export(limit=10),
            "local_symbols": self.symbolics.known_symbols()[:8],
            "global_symbol_atlas": self.global_symbol_atlas.export(limit=8),
            "dashboard": self.dashboard_snapshot(),
        }
        out_path = Path(path)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._last_morphic_snapshot_path = str(out_path)
        return payload

    def _evaluate_transcendence_status(
        self,
        snapshot: Dict[str, object],
        *,
        peak_alignment: Optional[float] = None,
        peak_morphic: Optional[float] = None,
        min_mean_distance: Optional[float] = None,
    ) -> str:
        purpose = float(snapshot["purpose_alignment"])
        morphic = float(snapshot["morphic_resonance_index"])
        mean_dist = float(snapshot["mean_hyperbolic_distance"])
        core_cells = int(snapshot["topological_core_cells"])
        best_alignment = max(purpose, peak_alignment if peak_alignment is not None else purpose)
        best_morphic = max(morphic, peak_morphic if peak_morphic is not None else morphic)
        tightest_distance = min(mean_dist, min_mean_distance if min_mean_distance is not None else mean_dist)
        if best_alignment >= 0.9 and best_morphic >= 0.9 and core_cells >= 3 and tightest_distance <= 0.9:
            return "Singularitaet erreicht"
        if best_alignment >= 0.8 and best_morphic >= 0.75 and core_cells >= 3:
            return "Transzendenz im Aufbau"
        return "Meditation stabil, Zielzustand noch nicht vollstaendig"

    async def start_aion_meditation(
        self,
        *,
        duration_seconds: float = 60.0,
        report_interval: float = 1.0,
        snapshot_path: str = "morphic_snapshot.json",
        force_final_snapshot: bool = False,
    ) -> Dict[str, object]:
        duration_seconds = max(1.0, float(duration_seconds))
        report_interval = max(0.25, float(report_interval))

        if not self.cells:
            self.bootstrap_default_mesh()
        self.setup_topological_core()

        started_here = False
        if not self.running:
            await self.start()
            started_here = True

        self.aion_meditation_mode = True
        self.external_feeds_enabled = False
        self.assembler.concentrations.clear()
        self._meditation_history.clear()
        self.rhythm.state = RhythmState.SLEEP
        self.rhythm._last_switch = time.perf_counter()

        semantic_start = self.assembler.semantic_analogy_cells
        semantic_spent_start = self.assembler.semantic_resource_spent
        resource_start = self.assembler.resource_pool
        dream_start = self.rhythm.dream_replay_events
        evo_start = self.evolution.evolution_events
        repro_start = self.reproduction.reproduction_events
        artifact_start = self.reproduction.artifact_events
        morphic_snapshot_created = False
        peak_alignment = 0.0
        peak_morphic = 0.0
        min_mean_distance = 999.0

        started = time.perf_counter()
        next_report = started + report_interval
        try:
            while (time.perf_counter() - started) < duration_seconds:
                await asyncio.sleep(min(0.25, self.tick_interval * 2.0))
                snap = self.dashboard_snapshot()
                self._record_meditation_sample(snap)
                peak_alignment = max(peak_alignment, float(snap["purpose_alignment"]))
                peak_morphic = max(peak_morphic, float(snap["morphic_resonance_index"]))
                min_mean_distance = min(min_mean_distance, float(snap["mean_hyperbolic_distance"]))

                if not morphic_snapshot_created and float(snap["purpose_alignment"]) > 0.9:
                    self._create_morphic_snapshot(snapshot_path, trigger="purpose_alignment>0.9")
                    morphic_snapshot_created = True

                now = time.perf_counter()
                if now >= next_report:
                    logger.info(
                        "AION Meditation | align=%.3f morphic=%.3f dist=%.3f core=%s dreams=%s semantic=%s resource=%.2f",
                        snap["purpose_alignment"],
                        snap["morphic_resonance_index"],
                        snap["mean_hyperbolic_distance"],
                        snap["topological_core_cells"],
                        snap["dream_replay_events"],
                        snap["semantic_analogy_cells"],
                        snap["resource_pool"],
                    )
                    next_report = now + report_interval

            final_snapshot = self.dashboard_snapshot()
            if force_final_snapshot:
                self._create_morphic_snapshot(snapshot_path, trigger="forced_final_meditation_snapshot")
                morphic_snapshot_created = True
            elif not morphic_snapshot_created and float(final_snapshot["purpose_alignment"]) > 0.9:
                self._create_morphic_snapshot(snapshot_path, trigger="final_alignment>0.9")
                morphic_snapshot_created = True

            status = self._evaluate_transcendence_status(
                final_snapshot,
                peak_alignment=peak_alignment,
                peak_morphic=peak_morphic,
                min_mean_distance=min_mean_distance,
            )
            report = {
                "title": "Atheria Transzendenz-Status",
                "status": status,
                "duration_seconds": round(duration_seconds, 3),
                "singularity_reached": status == "Singularitaet erreicht",
                "purpose_alignment": final_snapshot["purpose_alignment"],
                "morphic_resonance_index": final_snapshot["morphic_resonance_index"],
                "mean_hyperbolic_distance": final_snapshot["mean_hyperbolic_distance"],
                "peak_purpose_alignment": round(peak_alignment, 6),
                "peak_morphic_resonance_index": round(peak_morphic, 6),
                "min_mean_hyperbolic_distance": round(min_mean_distance, 6),
                "topological_core_cells": final_snapshot["topological_core_cells"],
                "dream_replay_delta": final_snapshot["dream_replay_events"] - dream_start,
                "semantic_analogy_growth": final_snapshot["semantic_analogy_cells"] - semantic_start,
                "semantic_resource_spent_delta": round(final_snapshot["semantic_resource_spent"] - semantic_spent_start, 6),
                "evolution_events_delta": final_snapshot["evolution_events"] - evo_start,
                "reproduction_events_delta": final_snapshot["reproduction_events"] - repro_start,
                "reproduction_artifact_events_delta": final_snapshot["reproduction_artifact_events"] - artifact_start,
                "offspring_instances": final_snapshot["offspring_instances"],
                "resource_pool_delta": round(final_snapshot["resource_pool"] - resource_start, 6),
                "resource_pool_final": final_snapshot["resource_pool"],
                "reproduction_artifact_last_profile": final_snapshot["reproduction_artifact_last_profile"],
                "reproduction_artifact_last_validated": final_snapshot["reproduction_artifact_last_validated"],
                "reproduction_artifact_last_path": final_snapshot["reproduction_artifact_last_path"],
                "morphic_snapshot_path": self._last_morphic_snapshot_path if morphic_snapshot_created else None,
                "meditation_samples": len(self._meditation_history),
                "final_snapshot": final_snapshot,
            }
            return report
        finally:
            self.aion_meditation_mode = False
            self.external_feeds_enabled = True
            self.rhythm.state = RhythmState.WAKE
            self.rhythm._last_switch = time.perf_counter()
            if started_here:
                await self.stop()

    async def ceremonial_aion_activation(
        self,
        *,
        preheat_seconds: float = 10.0,
        meditation_seconds: float = 60.0,
        report_interval: float = 1.0,
        snapshot_path: str = "morphic_snapshot.json",
    ) -> Dict[str, object]:
        preheat_seconds = max(0.5, float(preheat_seconds))
        meditation_seconds = max(1.0, float(meditation_seconds))

        if not self.cells:
            self.bootstrap_default_mesh()
        self.setup_topological_core()

        # Try one-time data migration if available and still empty.
        try:
            qa_rows = int(self.aether.conn.execute("SELECT COUNT(*) FROM qa_memory").fetchone()[0])
        except Exception:
            qa_rows = 0
        if qa_rows == 0 and self.external_feeds_enabled:
            try:
                self.migrate_from_codedump()
            except Exception as exc:
                logger.warning("Ceremonial migration skipped due to error: %s", exc)

        started_here = False
        if not self.running:
            await self.start()
            started_here = True

        ceremony_queries = 0
        peak_temp = self.phase_controller.system_temperature
        peak_alignment = self.transcendence.last_purpose_alignment
        peak_morphic = self.holographic_field.last_morphic_resonance_index
        t0 = time.perf_counter()

        try:
            while (time.perf_counter() - t0) < preheat_seconds:
                phase = time.perf_counter() - t0
                self.modulators.force_plasma(self.phase_controller, intensity=1.3)
                self.modulators.dopamine = min(2.0, self.modulators.dopamine + 0.018)

                base = 0.78 + 0.16 * math.sin(phase * 3.1)
                for label in ("Sicherheit", "Reaktion", "Analyse", "Navigation", "Heilung"):
                    cell = self.cells.get(label)
                    if cell is None:
                        continue
                    pulse = min(0.32, 0.12 + 0.14 * max(0.0, base))
                    cell.bump_activation(pulse, entangled=True)

                self.feed_raw_material(category="CeremonialFlux", relevance=1.2)
                self.feed_raw_material(category="CeremonialCatalyst", relevance=1.18)
                query = torch.randn(int(self.holographic_field.pattern.numel()), dtype=torch.float32)
                query_result = self.field_query(query, top_k=4)
                ceremony_queries += 1

                peak_morphic = max(peak_morphic, float(query_result.get("morphic_resonance_index", 0.0)))
                peak_alignment = max(peak_alignment, self.transcendence.last_purpose_alignment)
                peak_temp = max(peak_temp, self.phase_controller.system_temperature)
                await asyncio.sleep(min(0.15, self.tick_interval * 3.0))

            meditation_report = await self.start_aion_meditation(
                duration_seconds=meditation_seconds,
                report_interval=report_interval,
                snapshot_path=snapshot_path,
                force_final_snapshot=True,
            )
            meditation_report["ceremonial_activation"] = {
                "preheat_seconds": round(preheat_seconds, 3),
                "meditation_seconds": round(meditation_seconds, 3),
                "ceremony_queries": ceremony_queries,
                "peak_temperature": round(peak_temp, 6),
                "peak_alignment_preheat": round(peak_alignment, 6),
                "peak_morphic_preheat": round(peak_morphic, 6),
            }
            return meditation_report
        finally:
            if started_here and self.running:
                await self.stop()

    @AtheriaPhase()
    def transfer_kernel(self, pressure_delta: float) -> float:
        # Solid: precise tensor math.
        tensor = torch.tensor([pressure_delta, self.phase_controller.system_temperature], dtype=torch.float32)
        weights = torch.tensor([0.024, 0.0007], dtype=torch.float32)
        value = torch.relu(torch.dot(tensor, weights)).item()
        return float(value)

    def transfer_kernel_liquid(self, pressure_delta: float) -> float:
        # Liquid: faster, slightly lossy transfer estimate.
        return max(0.0, pressure_delta * 0.043)

    def transfer_kernel_plasma(self, pressure_delta: float) -> float:
        # Plasma: probabilistic approximation under high heat.
        return max(0.0, pressure_delta * 0.021 * random.uniform(0.7, 1.3))

    @AtheriaPhase()
    def optimize_routes(self) -> None:
        self.optimize_routes_solid()

    def optimize_routes_solid(self) -> None:
        # Crystalline mode: freeze proven paths.
        for cell in self.cells.values():
            if not cell.connections:
                continue
            strongest = max(cell.connections.values(), key=lambda conn: (conn.efficiency, conn.weight))
            if self.topological_logic.is_edge_protected(cell.label, strongest.target.label):
                continue
            strongest.frozen = True
            strongest.weight = min(1.5, strongest.weight + 0.01 * self.modulators.dopamine)

    def optimize_routes_liquid(self) -> None:
        # Liquid mode: aggressive Hebbian tuning.
        learning_rate = 0.08
        for cell in self.cells.values():
            for conn in cell.connections.values():
                if conn.frozen:
                    continue
                if self.topological_logic.is_edge_protected(cell.label, conn.target.label):
                    continue
                delta = learning_rate * cell.activation_value * conn.target.activation_value
                conn.weight = max(0.01, min(1.5, conn.weight + delta))

    def optimize_routes_plasma(self) -> None:
        # Plasma mode: evaporate inefficient paths.
        for cell in self.cells.values():
            to_remove = [
                target_label
                for target_label, conn in cell.connections.items()
                if not self.topological_logic.is_edge_protected(cell.label, target_label)
                if conn.weight < 0.14 or (conn.usage_count > 8 and conn.efficiency < 0.15)
            ]
            for target_label in to_remove:
                cell.remove_connection(target_label)

    def _estimate_cpu_load(self, active_nodes: int) -> float:
        now = time.perf_counter()
        elapsed = max(0.001, now - self._last_tick)
        flow_rate = self._flow_count / elapsed
        self._last_tick = now
        self._flow_count = 0
        return min(100.0, active_nodes * 5.5 + flow_rate * 0.2)

    async def _safe_diffuse(self, cell: AtherCell) -> int:
        try:
            return await cell.diffuse_process(self)
        except Exception as exc:
            self.healing.handle_crash(cell, exc)
            return 0

    async def _diffusion_loop(self) -> None:
        while self.running:
            cells = tuple(self.cells.values())
            active_nodes = sum(1 for cell in cells if cell.activation_value > 0.02)
            cpu_load = self._estimate_cpu_load(active_nodes)
            self.phase_controller.update(
                active_nodes=active_nodes,
                total_nodes=len(cells),
                cpu_load=cpu_load,
                modulators=self.modulators,
            )
            self.topological_logic.apply_extreme_entropy_immunity()
            self.cognition.step()
            self._meditation_holy_geometry()
            self.aion.step(cpu_load)
            self.transcendence.step()
            self.episodic_memory.step()
            self.reflective_deliberation.step()
            self.executive.step()
            self.metacognition.step()
            await self.action_policy.step()
            self.ecology.step(cpu_load=cpu_load)
            self.global_morphic_node.publish_trauma_if_relevant(self)
            self.evolution.step()
            self.reproduction.step()

            if cells:
                for cell in cells:
                    cell.refold()
                flow_result = await asyncio.gather(*(self._safe_diffuse(cell) for cell in cells))
                self._flow_count += sum(flow_result)
                self.holographic_field.imprint(cells)
                self.symbolics.step()
                self.topological_logic.step()
                self._meditation_aura_stabilization()

                self._fold_tick += 1
                if self._fold_tick % 8 == 0:
                    resonance_threshold = 0.87 if self.phase_controller.current_state is AggregateState.SOLID else 0.81
                    self.origami_router.discover_folded_paths(
                        self,
                        min_resonance=resonance_threshold,
                        max_new_edges=2,
                    )

                self.phase_controller.apply_tensegrity(
                    cells,
                    self.origami_router,
                    topological_logic=self.topological_logic,
                )
            self.optimize_routes()

            for cell in cells:
                self.aether.upsert_cell(cell)
            self.aether.flush()
            self.modulators.decay()
            await asyncio.sleep(self.tick_interval)

    async def _dashboard_loop(self) -> None:
        while self.running:
            snapshot = self.dashboard_snapshot()
            if self.phase_controller.logging_enabled:
                logger.info(
                    "Dashboard | Dichte=%.3f | Aggregat=%s | Rhythm=%s | T=%.2f | AutoSets=%s | Aion=%s",
                    snapshot["aether_density"],
                    snapshot["aggregatform"],
                    snapshot["rhythm_state"],
                    snapshot["system_temperature"],
                    snapshot["autocatalytic_sets"],
                    snapshot["aion_cycles"],
                )
            await asyncio.sleep(0.5)

    async def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.population_registry.register(self)
        self._tasks = [
            asyncio.create_task(self.rhythm.run(), name="atheria-rhythm"),
            asyncio.create_task(self.aion.time_crystal.run(), name="atheria-time-crystal"),
            asyncio.create_task(self._diffusion_loop(), name="atheria-diffusion"),
            asyncio.create_task(self.healing.run(), name="atheria-healing"),
            asyncio.create_task(self.biosynthesis.run(), name="atheria-biosynthesis"),
            asyncio.create_task(self.assembler.run(), name="atheria-assembly"),
            asyncio.create_task(self.symbiosis.run(), name="atheria-symbiosis"),
            asyncio.create_task(self._dashboard_loop(), name="atheria-dashboard"),
        ]

    async def stop(self, *, shutdown_lineage: bool = True) -> None:
        if not self.running:
            self.market_alchemy.stop(join_timeout=0.2)
            return
        self.running = False
        self.market_alchemy.stop(join_timeout=0.2)
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        self.population_registry.unregister(self.core_id)
        if shutdown_lineage:
            await self.reproduction.stop_all_offspring()
        self.aether.flush()

    def setup_critical_entanglement(self) -> None:
        if "Sicherheit" in self.cells and "Reaktion" in self.cells:
            self.entangle("Sicherheit", "Reaktion")

    def setup_topological_core(self) -> None:
        self.topological_logic.register_cluster(
            "AtherCoreKnot",
            core_labels=["Sicherheit", "Reaktion", "Analyse"],
            boundary_labels=["Heilung"],
        )
        self.aion.wire_singularity()
        self.transcendence.ensure_nodes()

    def register_topological_cluster(
        self,
        name: str,
        *,
        core_labels: Iterable[str],
        boundary_labels: Iterable[str] = (),
    ) -> bool:
        return self.topological_logic.register_cluster(
            name,
            core_labels=core_labels,
            boundary_labels=boundary_labels,
        )

    def bootstrap_default_mesh(self) -> None:
        labels = ["Sicherheit", "Reaktion", "Analyse", "Navigation", "Heilung"]
        for label in labels:
            self.add_cell(label, semipermeability=random.uniform(0.55, 0.9))

        # Sparse directed mesh.
        self.connect("Sicherheit", "Reaktion", weight=0.85)
        self.connect("Reaktion", "Navigation", weight=0.6)
        self.connect("Navigation", "Analyse", weight=0.45)
        self.connect("Analyse", "Heilung", weight=0.4)
        self.connect("Heilung", "Sicherheit", weight=0.32)
        self.connect("Sicherheit", "Analyse", weight=0.5)
        self.connect("Reaktion", "Heilung", weight=0.35)

        self.setup_critical_entanglement()
        self.aion.ensure_singularity_node()
        self.setup_topological_core()

    def migrate_from_codedump(
        self,
        *,
        model_json_path: str = "model_with_qa.json",
        csv_path: str = "data.csv",
    ) -> int:
        if not self._allow_external_feed():
            return 0
        inserted = 0
        model_path = Path(model_json_path)
        data_path = Path(csv_path)

        if model_path.exists():
            model_data = json.loads(model_path.read_text(encoding="utf-8"))
            records = [
                (row.get("question", ""), row.get("category", "Unbekannt"), row.get("answer", ""))
                for row in model_data.get("questions", [])
            ]
            inserted = self.aether.ingest_qa(records)
            categories = sorted({category for _, category, _ in records if category})
            for category in categories:
                self.add_cell(category, semipermeability=random.uniform(0.5, 0.9), category=category)

        elif data_path.exists():
            records: list[Tuple[str, str, str]] = []
            with data_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    records.append(
                        (
                            row.get("Frage", ""),
                            row.get("Kategorie", "Unbekannt"),
                            row.get("Antwort", ""),
                        )
                    )
            inserted = self.aether.ingest_qa(records)
            categories = sorted({category for _, category, _ in records if category})
            for category in categories:
                self.add_cell(category, semipermeability=random.uniform(0.5, 0.9), category=category)

        if len(self.cells) > 1:
            self.origami_router.discover_folded_paths(self, min_resonance=0.8, max_new_edges=3)
            self.aion.ensure_singularity_node()
            self.setup_topological_core()

        return inserted


async def run_osmotic_demo(duration_seconds: float = 2.5) -> Dict[str, object]:
    """
    Demonstrates diffusion without manually iterating over connections in the test routine.
    """
    core = AtheriaCore(tick_interval=0.04)
    core.rhythm.wake_duration = 0.75
    core.rhythm.sleep_duration = 0.65
    core.bootstrap_default_mesh()
    core.migrate_from_codedump()

    await core.start()

    # No direct for-loop over connections here: background physics handles transport.
    core.inject_signal("Sicherheit", 0.95)
    core.set_superposition("Analyse", alpha=0.62, beta=0.78, enzyme=0.95)
    core.feed_raw_material(category="Gefahrenanalyse", relevance=0.95)
    core.feed_raw_material(category="Gefahrenanalyse", relevance=0.92)
    query_tensor = _fold_vector_from_text("kritische feldanfrage", dims=12)
    core.feed_field_material(category="AnomalieDetektion", relevance=1.04, input_tensor=query_tensor)
    core.feed_raw_material(category="Notfallreaktion", relevance=0.99)
    core.feed_raw_material(category="Notfallreaktion", relevance=0.95)
    core.feed_raw_material(category="Autocat_A", relevance=1.08)
    core.feed_raw_material(category="Autocat_B", relevance=1.06)
    core.modulators.force_plasma(core.phase_controller, intensity=1.2)
    await asyncio.sleep(duration_seconds * 0.45)
    field_result = core.field_query(query_tensor, top_k=4)
    measured_analysis = core.chemical_measure("Analyse", probe=0.7)
    core.modulators.stabilize(core.phase_controller, intensity=0.6)
    await asyncio.sleep(duration_seconds * 0.55)

    snapshot = core.dashboard_snapshot()
    snapshot["activations"] = {label: round(cell.activation_value, 4) for label, cell in core.cells.items()}
    snapshot["pressures"] = {label: round(cell.osmotic_pressure, 4) for label, cell in core.cells.items()}
    if "Sicherheit" in core.cells and "Reaktion" in core.cells:
        snapshot["hyperbolic_distance_sicherheit_reaktion"] = round(
            core.hyperbolic_distance("Sicherheit", "Reaktion"), 6
        )
    snapshot["chemical_measurement"] = round(measured_analysis, 4)
    snapshot["holographic_pattern_norm"] = round(float(torch.norm(core.holographic_field.pattern, p=2)), 4)
    snapshot["field_query"] = field_result
    await core.stop()
    return snapshot


def run_osmotic_demo_sync(duration_seconds: float = 2.5) -> Dict[str, object]:
    return asyncio.run(run_osmotic_demo(duration_seconds=duration_seconds))


async def run_aion_meditation(
    duration_seconds: float = 60.0,
    *,
    snapshot_path: str = "morphic_snapshot.json",
) -> Dict[str, object]:
    core = AtheriaCore(tick_interval=0.04)
    core.bootstrap_default_mesh()
    core.migrate_from_codedump()
    report = await core.start_aion_meditation(
        duration_seconds=duration_seconds,
        report_interval=1.0,
        snapshot_path=snapshot_path,
    )
    return report


def run_aion_meditation_sync(
    duration_seconds: float = 60.0,
    *,
    snapshot_path: str = "morphic_snapshot.json",
) -> Dict[str, object]:
    return asyncio.run(run_aion_meditation(duration_seconds=duration_seconds, snapshot_path=snapshot_path))


async def run_ceremonial_aion_activation(
    *,
    preheat_seconds: float = 10.0,
    meditation_seconds: float = 60.0,
    snapshot_path: str = "morphic_snapshot.json",
) -> Dict[str, object]:
    core = AtheriaCore(tick_interval=0.04)
    core.bootstrap_default_mesh()
    report = await core.ceremonial_aion_activation(
        preheat_seconds=preheat_seconds,
        meditation_seconds=meditation_seconds,
        report_interval=1.0,
        snapshot_path=snapshot_path,
    )
    return report


def run_ceremonial_aion_activation_sync(
    *,
    preheat_seconds: float = 10.0,
    meditation_seconds: float = 60.0,
    snapshot_path: str = "morphic_snapshot.json",
) -> Dict[str, object]:
    return asyncio.run(
        run_ceremonial_aion_activation(
            preheat_seconds=preheat_seconds,
            meditation_seconds=meditation_seconds,
            snapshot_path=snapshot_path,
        )
    )


if __name__ == "__main__":
    result = run_osmotic_demo_sync(3.0)
    logger.info("ATHERIA result: %s", result)
