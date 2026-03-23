from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value: Any, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, _safe_float(value, lower)))


def _coerce_json(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return value
    return value


def _as_list(value: Any) -> list[Any]:
    value = _coerce_json(value)
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def default_policy() -> dict[str, Any]:
    return {
        "max_risk": 0.68,
        "capital_limit": 420000.0,
        "forbidden_actions": [
            "acquire_competitor",
            "disable_core_security",
        ],
        "minimum_runway_months": 3.0,
    }


def default_domain_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": _now_iso(),
        "capital": {
            "liquidity": 1600000.0,
            "burn_rate": 210000.0,
            "allocations": {
                "core_platform": 520000.0,
                "growth": 0.0,
                "operations": 0.0,
                "resilience": 0.0,
            },
        },
        "operations": {
            "capacity": 1.0,
            "utilization": 0.72,
            "bottlenecks": [],
            "active_jobs": [],
        },
        "strategy": {
            "active_initiatives": [
                "enterprise_growth",
                "runtime_security",
            ],
            "priorities": {
                "growth": 0.72,
                "resilience": 0.78,
                "efficiency": 0.64,
            },
            "horizon": "quarter",
        },
        "risk": {
            "exposure": 0.38,
            "volatility": 0.34,
            "critical_flags": [],
        },
        "market": {
            "demand": 0.66,
            "signals": [],
            "opportunities": [],
        },
        "policy": default_policy(),
        "decisions_history": [],
        "execution_log": [],
        "signal_history": [],
        "last_decision": {},
        "last_execution": {},
        "last_outcome": {},
    }


def load_or_bootstrap_state(existing: Any) -> dict[str, Any]:
    payload = _coerce_json(existing)
    if not isinstance(payload, dict):
        return default_domain_state()
    state = default_domain_state()
    _deep_merge(state, payload)
    state["updated_at"] = _now_iso()
    return state


def apply_policy_overrides(state_like: Any, overrides_like: Any) -> dict[str, Any]:
    state = load_or_bootstrap_state(state_like)
    overrides = _coerce_json(overrides_like)
    if isinstance(overrides, list):
        overrides = overrides[0] if overrides else {}
    if not isinstance(overrides, dict):
        return state
    policy = dict(state.get("policy") or {})
    for key in ("max_risk", "capital_limit", "minimum_runway_months"):
        if key in overrides:
            policy[key] = _safe_float(overrides[key], policy.get(key, 0.0))
    if isinstance(overrides.get("forbidden_actions"), list):
        policy["forbidden_actions"] = [str(item) for item in overrides["forbidden_actions"] if str(item).strip()]
    state["policy"] = policy
    state["updated_at"] = _now_iso()
    return state


def _derive_signal_severity(record: dict[str, Any], source_kind: str) -> float:
    payload = dict(record.get("payload") or {}) if isinstance(record.get("payload"), dict) else {}
    text = " ".join(
        [
            str(record.get("title") or ""),
            str(record.get("summary") or ""),
            str(record.get("source") or ""),
            str(source_kind or ""),
            str(payload.get("partner") or ""),
        ]
    ).lower()
    deadline_days = int(_safe_float(payload.get("deadline_days"), -1.0))

    base_severity: float | None = None
    if "severity" in record:
        base_severity = _clamp(record.get("severity"), 0.0, 1.0)
    metrics = dict(record.get("metrics") or {})
    candidates = [
        metrics.get("utilization"),
        metrics.get("demand"),
        metrics.get("opportunity"),
        metrics.get("volatility"),
        metrics.get("exposure"),
        metrics.get("pressure"),
    ]
    numeric = [_safe_float(item, -1.0) for item in candidates if item is not None]
    valid = [item for item in numeric if item >= 0.0]
    if base_severity is None:
        if valid:
            base_severity = _clamp(sum(valid) / len(valid))
        elif any(token in text for token in ("critical", "high", "urgent", "capacity", "deadline", "investment")):
            base_severity = 0.76
        elif any(token in text for token in ("growth", "demand", "partner", "expand", "opportunity")):
            base_severity = 0.64
        else:
            base_severity = 0.45

    # Strategic partner signals with a near-term commitment window should not stay in the
    # mid-0.7 range; they represent concrete board-level pressure rather than soft demand.
    if ("partner" in text or payload.get("partner")) and (str(record.get("type") or source_kind or "").lower() in {"event", "opportunity", "market"}):
        base_severity = max(base_severity, 0.82)
        if 0 < deadline_days <= 30:
            base_severity = max(base_severity, 0.86)
        if 0 < deadline_days <= 14:
            base_severity = max(base_severity, 0.9)

    return _clamp(base_severity, 0.0, 1.0)


def normalize_signal_batch(records_like: Any, *, source_kind: str, default_domain: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(_as_list(records_like)):
        record = raw if isinstance(raw, dict) else {"value": raw}
        title = str(record.get("title") or record.get("name") or f"{source_kind}-{index}")
        summary = str(record.get("summary") or record.get("text") or record.get("value") or "")
        domain = str(record.get("domain") or default_domain or "general")
        signal_type = str(record.get("type") or source_kind or "signal")
        metrics = dict(record.get("metrics") or {})
        payload = dict(record.get("payload") or {}) if isinstance(record.get("payload"), dict) else {}
        extra_payload = {
            key: value
            for key, value in record.items()
            if key not in {"signal_id", "title", "summary", "source", "type", "domain", "severity", "metrics", "payload"}
        }
        payload.update(extra_payload)
        signal_id = str(record.get("signal_id") or hashlib.sha1(f"{title}|{domain}|{summary}|{index}".encode("utf-8")).hexdigest()[:12])
        normalized.append(
            {
                "signal_id": signal_id,
                "type": signal_type,
                "severity": _derive_signal_severity(record, source_kind),
                "domain": domain,
                "source": str(record.get("source") or source_kind or "local"),
                "title": title,
                "summary": summary,
                "metrics": metrics,
                "payload": payload,
                "timestamp": _now_iso(),
            }
        )
    return normalized


def merge_signal_batches(*batches: Any) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for batch in batches:
        for item in _as_list(batch):
            if not isinstance(item, dict):
                continue
            signal_id = str(item.get("signal_id") or hashlib.sha1(json.dumps(item, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12])
            merged[signal_id] = item
    return sorted(merged.values(), key=lambda item: (-_safe_float(item.get("severity"), 0.0), str(item.get("domain") or ""), str(item.get("title") or "")))


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def refresh_state_from_signals(state_like: Any, signals_like: Any) -> dict[str, Any]:
    state = load_or_bootstrap_state(state_like)
    signals = merge_signal_batches(signals_like)
    market_values = [_safe_float(item.get("metrics", {}).get("demand"), item.get("severity", 0.0)) for item in signals if item.get("domain") == "market"]
    operations_values = [_safe_float(item.get("metrics", {}).get("utilization"), item.get("severity", 0.0)) for item in signals if item.get("domain") == "operations"]
    liquidity_values = [_safe_float(item.get("metrics", {}).get("liquidity"), -1.0) for item in signals if item.get("domain") == "capital"]
    burn_values = [_safe_float(item.get("metrics", {}).get("burn_rate"), -1.0) for item in signals if item.get("domain") == "capital"]
    risk_values = [_safe_float(item.get("metrics", {}).get("volatility"), item.get("severity", 0.0)) for item in signals if item.get("domain") == "risk"]
    opportunity_titles = [str(item.get("title") or "") for item in signals if item.get("type") in {"opportunity", "event", "trend"} and item.get("domain") in {"market", "strategy"}]
    critical_flags = [
        str(item.get("title") or item.get("summary") or item.get("signal_id") or "")
        for item in signals
        if _safe_float(item.get("severity"), 0.0) >= 0.85
    ]

    if market_values:
        state["market"]["demand"] = round(_clamp(_average(market_values)), 6)
    if operations_values:
        state["operations"]["utilization"] = round(_clamp(max(operations_values), 0.0, 1.2), 6)
    if liquidity_values:
        liquidity = max((item for item in liquidity_values if item >= 0.0), default=state["capital"]["liquidity"])
        state["capital"]["liquidity"] = round(liquidity, 2)
    if burn_values:
        burn_rate = max((item for item in burn_values if item >= 0.0), default=state["capital"]["burn_rate"])
        state["capital"]["burn_rate"] = round(burn_rate, 2)
    if risk_values:
        state["risk"]["volatility"] = round(_clamp(_average(risk_values)), 6)

    state["market"]["signals"] = signals[-12:]
    state["market"]["opportunities"] = opportunity_titles[:8]
    state["risk"]["critical_flags"] = critical_flags[:8]
    state["operations"]["bottlenecks"] = [
        str(item.get("title") or "")
        for item in signals
        if item.get("domain") == "operations" and _safe_float(item.get("severity"), 0.0) >= 0.75
    ][:6]
    state["signal_history"] = [*list(state.get("signal_history", [])), {"timestamp": _now_iso(), "count": len(signals), "top_signal": signals[0]["title"] if signals else ""}][-64:]
    state["updated_at"] = _now_iso()
    return state


def _option_packet(
    option_id: str,
    action: str,
    expected_gain: float,
    required_capital: float,
    operational_load: float,
    timeframe: str,
    rationale: str,
    domains: list[str],
    signal_refs: list[str],
) -> dict[str, Any]:
    return {
        "option_id": option_id,
        "action": action,
        "expected_gain": round(_clamp(expected_gain), 6),
        "required_capital": round(max(0.0, required_capital), 2),
        "operational_load": round(_clamp(operational_load), 6),
        "timeframe": timeframe,
        "rationale": rationale,
        "domains": domains,
        "signal_refs": signal_refs,
    }


def strategy_agent(signals_like: Any, state_like: Any) -> dict[str, Any]:
    signals = merge_signal_batches(signals_like)
    state = load_or_bootstrap_state(state_like)
    market_demand = _safe_float(state.get("market", {}).get("demand"), 0.5)
    operations_utilization = _safe_float(state.get("operations", {}).get("utilization"), 0.5)
    liquidity = _safe_float(state.get("capital", {}).get("liquidity"), 0.0)
    partner_event = any("partner" in (str(item.get("title") or "") + " " + str(item.get("summary") or "")).lower() for item in signals)

    options: list[dict[str, Any]] = []
    if market_demand >= 0.58:
        options.append(
            _option_packet(
                "opt_scale_enterprise_capacity",
                "scale_enterprise_capacity",
                expected_gain=0.52 + (market_demand * 0.34),
                required_capital=180000.0 + max(0.0, market_demand - 0.6) * 220000.0,
                operational_load=0.18,
                timeframe="30-60 Tage",
                rationale="Steigende Enterprise-Nachfrage rechtfertigt eine kontrollierte Kapazitaetserweiterung.",
                domains=["market", "operations"],
                signal_refs=[item["signal_id"] for item in signals if item.get("domain") in {"market", "operations"}][:6],
            )
        )
    if operations_utilization >= 0.82:
        options.append(
            _option_packet(
                "opt_stabilize_compute_capacity",
                "stabilize_compute_capacity",
                expected_gain=0.44 + (operations_utilization * 0.26),
                required_capital=140000.0 + max(0.0, operations_utilization - 0.8) * 180000.0,
                operational_load=0.22,
                timeframe="14-30 Tage",
                rationale="Hohe Auslastung erfordert gezielte Kapazitaets- und Resilienzmassnahmen.",
                domains=["operations", "risk"],
                signal_refs=[item["signal_id"] for item in signals if item.get("domain") in {"operations", "risk"}][:6],
            )
        )
    if partner_event and liquidity > 600000.0:
        options.append(
            _option_packet(
                "opt_fund_partner_program",
                "fund_partner_program",
                expected_gain=0.48 + (market_demand * 0.28),
                required_capital=260000.0,
                operational_load=0.12,
                timeframe="45-90 Tage",
                rationale="Partner-Co-Investment beschleunigt Pipelinezugang bei vertretbarem Einsatz.",
                domains=["market", "capital"],
                signal_refs=[item["signal_id"] for item in signals if "partner" in (str(item.get("title") or "") + " " + str(item.get("summary") or "")).lower()][:4],
            )
        )
    if not options:
        options.append(
            _option_packet(
                "opt_hold_position",
                "hold_position",
                expected_gain=0.28,
                required_capital=0.0,
                operational_load=0.02,
                timeframe="7-14 Tage",
                rationale="Keine Option mit ausreichendem asymmetrischem Vorteil sichtbar; Lage aktiv beobachten.",
                domains=["strategy"],
                signal_refs=[item["signal_id"] for item in signals[:3]],
            )
        )

    options.sort(key=lambda item: (-_safe_float(item.get("expected_gain"), 0.0), _safe_float(item.get("required_capital"), 0.0)))
    dominant_domains = sorted({str(item.get("domain") or "") for item in signals if str(item.get("domain") or "")})[:5]
    return {
        "agent": "StrategyAgent",
        "generated_at": _now_iso(),
        "signal_count": len(signals),
        "dominant_domains": dominant_domains,
        "options": options,
    }


def risk_agent(strategy_packet_like: Any, signals_like: Any, state_like: Any) -> dict[str, Any]:
    strategy_packet = _coerce_json(strategy_packet_like) or {}
    signals = merge_signal_batches(signals_like)
    state = load_or_bootstrap_state(state_like)
    options = list(strategy_packet.get("options") or [])
    base_volatility = _safe_float(state.get("risk", {}).get("volatility"), 0.3)
    critical_count = len(list(state.get("risk", {}).get("critical_flags") or []))
    policy = dict(state.get("policy") or {})
    assessments: list[dict[str, Any]] = []

    for option in options:
        domains = set(str(item) for item in option.get("domains") or [])
        relevant = [item for item in signals if str(item.get("domain") or "") in domains]
        domain_pressure = _average([_safe_float(item.get("severity"), 0.0) for item in relevant])
        capital_stress = _safe_float(option.get("required_capital"), 0.0) / max(_safe_float(policy.get("capital_limit"), 1.0), 1.0)
        risk_score = _clamp(0.16 + (base_volatility * 0.45) + (domain_pressure * 0.3) + min(0.18, critical_count * 0.05) + (capital_stress * 0.12))
        failure_modes: list[str] = []
        if critical_count:
            failure_modes.append("kritische Warnsignale bereits aktiv")
        if domain_pressure >= 0.75:
            failure_modes.append("Signalintensitaet im betroffenen Bereich hoch")
        if capital_stress >= 0.85:
            failure_modes.append("Kapitalbedarf naeher an Governance-Grenze")
        if option.get("action") == "hold_position":
            failure_modes.append("Opportunitaetskosten bei zu langem Zuwarten")
        recommendation = "allow"
        if risk_score > _safe_float(policy.get("max_risk"), 0.68):
            recommendation = "revise"
        if risk_score > _safe_float(policy.get("max_risk"), 0.68) + 0.12:
            recommendation = "block"
        assessments.append(
            {
                "option_id": option.get("option_id"),
                "risk_score": round(risk_score, 6),
                "failure_modes": failure_modes or ["kein dominanter Failure Mode"],
                "recommendation": recommendation,
            }
        )

    return {
        "agent": "RiskAgent",
        "generated_at": _now_iso(),
        "assessments": assessments,
    }


def capital_agent(strategy_packet_like: Any, state_like: Any) -> dict[str, Any]:
    strategy_packet = _coerce_json(strategy_packet_like) or {}
    state = load_or_bootstrap_state(state_like)
    options = list(strategy_packet.get("options") or [])
    liquidity = _safe_float(state.get("capital", {}).get("liquidity"), 0.0)
    burn_rate = max(1.0, _safe_float(state.get("capital", {}).get("burn_rate"), 1.0))
    policy = dict(state.get("policy") or {})
    capital_limit = _safe_float(policy.get("capital_limit"), liquidity)
    reserve_floor = burn_rate * _safe_float(policy.get("minimum_runway_months"), 3.0)
    runway_months = liquidity / burn_rate if burn_rate > 0 else 0.0
    plans: list[dict[str, Any]] = []

    for option in options:
        required_capital = _safe_float(option.get("required_capital"), 0.0)
        remaining_liquidity = liquidity - required_capital
        feasible = required_capital <= capital_limit and remaining_liquidity >= reserve_floor
        feasibility = _clamp((remaining_liquidity - reserve_floor) / max(liquidity, 1.0) + 0.5)
        plans.append(
            {
                "option_id": option.get("option_id"),
                "required_capital": round(required_capital, 2),
                "approved_allocation": round(min(required_capital, capital_limit), 2),
                "feasible": bool(feasible),
                "capital_feasibility": round(feasibility, 6),
                "runway_months": round(runway_months, 3),
                "remaining_liquidity": round(max(remaining_liquidity, 0.0), 2),
            }
        )

    return {
        "agent": "CapitalAgent",
        "generated_at": _now_iso(),
        "plans": plans,
    }


def operations_agent(strategy_packet_like: Any, state_like: Any, signals_like: Any) -> dict[str, Any]:
    strategy_packet = _coerce_json(strategy_packet_like) or {}
    state = load_or_bootstrap_state(state_like)
    signals = merge_signal_batches(signals_like)
    options = list(strategy_packet.get("options") or [])
    utilization = _safe_float(state.get("operations", {}).get("utilization"), 0.0)
    capacity = max(0.1, _safe_float(state.get("operations", {}).get("capacity"), 1.0))
    headroom = max(0.0, capacity - utilization)
    bottlenecks = list(state.get("operations", {}).get("bottlenecks") or [])
    bottleneck_penalty = min(0.32, len(bottlenecks) * 0.07)
    active_alerts = [
        str(item.get("title") or "")
        for item in signals
        if item.get("domain") == "operations" and _safe_float(item.get("severity"), 0.0) >= 0.7
    ]
    plans: list[dict[str, Any]] = []

    for option in options:
        operational_load = _safe_float(option.get("operational_load"), 0.0)
        fit = _clamp(1.0 - max(0.0, operational_load - headroom) - bottleneck_penalty)
        plans.append(
            {
                "option_id": option.get("option_id"),
                "operational_fit": round(fit, 6),
                "headroom": round(headroom, 6),
                "active_alerts": active_alerts[:5],
                "bottlenecks": bottlenecks[:5],
            }
        )

    return {
        "agent": "OperationsAgent",
        "generated_at": _now_iso(),
        "plans": plans,
    }


def consensus_layer(
    strategy_packet_like: Any,
    risk_packet_like: Any,
    capital_packet_like: Any,
    operations_packet_like: Any,
    state_like: Any,
) -> dict[str, Any]:
    strategy_packet = _coerce_json(strategy_packet_like) or {}
    risk_packet = _coerce_json(risk_packet_like) or {}
    capital_packet = _coerce_json(capital_packet_like) or {}
    operations_packet = _coerce_json(operations_packet_like) or {}
    state = load_or_bootstrap_state(state_like)
    options = list(strategy_packet.get("options") or [])
    risk_by_id = {str(item.get("option_id")): item for item in risk_packet.get("assessments") or []}
    capital_by_id = {str(item.get("option_id")): item for item in capital_packet.get("plans") or []}
    operations_by_id = {str(item.get("option_id")): item for item in operations_packet.get("plans") or []}
    policy = dict(state.get("policy") or default_policy())
    ranking: list[dict[str, Any]] = []

    for option in options:
        option_id = str(option.get("option_id") or "")
        risk_item = dict(risk_by_id.get(option_id) or {})
        capital_item = dict(capital_by_id.get(option_id) or {})
        operations_item = dict(operations_by_id.get(option_id) or {})
        weighted_score = (
            (_safe_float(option.get("expected_gain"), 0.0) * 0.4)
            + (_safe_float(capital_item.get("capital_feasibility"), 0.0) * 0.2)
            - (_safe_float(risk_item.get("risk_score"), 0.0) * 0.3)
            + (_safe_float(operations_item.get("operational_fit"), 0.0) * 0.1)
        )
        blocks: list[str] = []
        if str(option.get("action") or "") in {str(item) for item in policy.get("forbidden_actions") or []}:
            blocks.append("Aktion ist durch Policy verboten")
        if _safe_float(risk_item.get("risk_score"), 0.0) > _safe_float(policy.get("max_risk"), 0.68):
            blocks.append("Risikoschwelle ueberschritten")
        if _safe_float(option.get("required_capital"), 0.0) > _safe_float(policy.get("capital_limit"), 0.0):
            blocks.append("Kapitalgrenze ueberschritten")
        if capital_item and not bool(capital_item.get("feasible")):
            blocks.append("Kapitalplan nicht tragfaehig")
        status = "allowed" if not blocks else "blocked"
        ranking.append(
            {
                "option_id": option_id,
                "action": option.get("action"),
                "weighted_score": round(weighted_score, 6),
                "expected_gain": round(_safe_float(option.get("expected_gain"), 0.0), 6),
                "risk_score": round(_safe_float(risk_item.get("risk_score"), 0.0), 6),
                "capital_feasibility": round(_safe_float(capital_item.get("capital_feasibility"), 0.0), 6),
                "operational_fit": round(_safe_float(operations_item.get("operational_fit"), 0.0), 6),
                "required_capital": round(_safe_float(option.get("required_capital"), 0.0), 2),
                "status": status,
                "blocks": blocks,
                "rationale": option.get("rationale"),
            }
        )

    ranking.sort(key=lambda item: (0 if item.get("status") == "allowed" else 1, -_safe_float(item.get("weighted_score"), 0.0), _safe_float(item.get("required_capital"), 0.0)))
    selected = dict(ranking[0] if ranking else {})
    allowed = [item for item in ranking if item.get("status") == "allowed"]
    decision = "hold"
    recommended_action = "monitor_market"
    reason = "Keine tragfaehige Option identifiziert."
    if allowed:
        selected = dict(allowed[0])
        decision = "approve" if _safe_float(selected.get("weighted_score"), 0.0) >= 0.12 else "hold"
        recommended_action = str(selected.get("action") or "monitor_market")
        reason = "Beste erlaubte Option nach gewichteter Bewertung ausgewaehlt."
    elif selected:
        decision = "revise"
        recommended_action = "request_revision"
        reason = "; ".join(selected.get("blocks") or []) or "Option durch Governance blockiert"

    return {
        "agent": "ConsensusLayer",
        "generated_at": _now_iso(),
        "decision_id": f"ceo-{int(time.time())}",
        "decision": decision,
        "recommended_action": recommended_action,
        "score": round(_safe_float(selected.get("weighted_score"), 0.0), 6),
        "selected_option": selected,
        "ranking": ranking,
        "reason": reason,
        "policy": policy,
    }


def execution_agent(decision_packet_like: Any, state_like: Any) -> dict[str, Any]:
    decision_packet = _coerce_json(decision_packet_like) or {}
    state = load_or_bootstrap_state(state_like)
    selected = dict(decision_packet.get("selected_option") or {})
    decision = str(decision_packet.get("decision") or "hold")
    action = str(selected.get("action") or decision_packet.get("recommended_action") or "monitor_market")
    actions: list[dict[str, Any]] = []
    owner = "executive-office"
    capital_reserved = 0.0
    capacity_delta = 0.0

    if decision == "approve" and action == "scale_enterprise_capacity":
        capital_reserved = _safe_float(selected.get("required_capital"), 0.0)
        capacity_delta = 0.22
        owner = "platform-ops"
        actions = [
            {"kind": "budget.reserve", "amount": round(capital_reserved, 2), "bucket": "growth"},
            {"kind": "service.scale", "target": "inference-cluster", "delta": 2},
            {"kind": "initiative.start", "name": "enterprise_capacity_expansion"},
        ]
    elif decision == "approve" and action == "stabilize_compute_capacity":
        capital_reserved = _safe_float(selected.get("required_capital"), 0.0)
        capacity_delta = 0.18
        owner = "runtime-ops"
        actions = [
            {"kind": "budget.reserve", "amount": round(capital_reserved, 2), "bucket": "operations"},
            {"kind": "service.scale", "target": "gpu-capacity-pool", "delta": 1},
            {"kind": "queue.reprioritize", "target": "low-priority-jobs"},
        ]
    elif decision == "approve" and action == "fund_partner_program":
        capital_reserved = _safe_float(selected.get("required_capital"), 0.0)
        owner = "go-to-market"
        actions = [
            {"kind": "budget.reserve", "amount": round(capital_reserved, 2), "bucket": "growth"},
            {"kind": "initiative.start", "name": "partner_launch_program"},
            {"kind": "workflow.trigger", "target": "partner.enablement"},
        ]
    elif decision == "revise":
        owner = "strategy-office"
        actions = [
            {"kind": "review.request", "target": "selected-option", "reason": decision_packet.get("reason")},
            {"kind": "monitor.activate", "target": "risk-and-capital"},
        ]
    else:
        owner = "executive-office"
        actions = [
            {"kind": "monitor.activate", "target": "market"},
            {"kind": "status.broadcast", "message": "CEO system stays in monitored hold."},
        ]

    return {
        "agent": "ExecutionAgent",
        "generated_at": _now_iso(),
        "decision": decision,
        "action": action,
        "status": "dispatched" if decision == "approve" else "gated",
        "owner": owner,
        "capital_reserved": round(capital_reserved, 2),
        "capacity_delta": round(capacity_delta, 6),
        "actions": actions,
        "state_before": {
            "liquidity": round(_safe_float(state.get("capital", {}).get("liquidity"), 0.0), 2),
            "utilization": round(_safe_float(state.get("operations", {}).get("utilization"), 0.0), 6),
        },
    }


def apply_execution(state_like: Any, execution_packet_like: Any, decision_packet_like: Any) -> dict[str, Any]:
    state = load_or_bootstrap_state(state_like)
    execution = _coerce_json(execution_packet_like) or {}
    decision = _coerce_json(decision_packet_like) or {}
    capital_reserved = _safe_float(execution.get("capital_reserved"), 0.0)
    capacity_delta = _safe_float(execution.get("capacity_delta"), 0.0)
    selected = dict(decision.get("selected_option") or {})
    allocations = dict(state.get("capital", {}).get("allocations") or {})
    bucket = "operations" if str(execution.get("action") or "").startswith("stabilize_") else "growth"

    if capital_reserved > 0.0:
        state["capital"]["liquidity"] = round(max(0.0, _safe_float(state["capital"].get("liquidity"), 0.0) - capital_reserved), 2)
        allocations[bucket] = round(_safe_float(allocations.get(bucket), 0.0) + capital_reserved, 2)
        state["capital"]["allocations"] = allocations

    if capacity_delta > 0.0:
        state["operations"]["capacity"] = round(_safe_float(state["operations"].get("capacity"), 1.0) + capacity_delta, 6)
        state["operations"]["utilization"] = round(max(0.0, _safe_float(state["operations"].get("utilization"), 0.0) - (capacity_delta * 0.22)), 6)

    initiative = {
        "scale_enterprise_capacity": "enterprise_capacity_expansion",
        "stabilize_compute_capacity": "runtime_resilience_program",
        "fund_partner_program": "partner_launch_program",
    }.get(str(execution.get("action") or ""))
    if initiative and initiative not in state["strategy"]["active_initiatives"]:
        state["strategy"]["active_initiatives"].append(initiative)

    execution_entry = {
        "timestamp": _now_iso(),
        "decision_id": decision.get("decision_id"),
        "action": execution.get("action"),
        "owner": execution.get("owner"),
        "capital_reserved": round(capital_reserved, 2),
        "capacity_delta": round(capacity_delta, 6),
        "option_id": selected.get("option_id"),
    }
    state["execution_log"] = [*list(state.get("execution_log", [])), execution_entry][-64:]
    state["last_execution"] = execution_entry
    state["last_decision"] = {
        "decision_id": decision.get("decision_id"),
        "decision": decision.get("decision"),
        "action": execution.get("action"),
        "score": decision.get("score"),
        "option_id": selected.get("option_id"),
    }
    state["updated_at"] = _now_iso()
    return state


def evaluate_outcome(execution_packet_like: Any, decision_packet_like: Any, state_like: Any, signals_like: Any) -> dict[str, Any]:
    execution = _coerce_json(execution_packet_like) or {}
    decision = _coerce_json(decision_packet_like) or {}
    state = load_or_bootstrap_state(state_like)
    signals = merge_signal_batches(signals_like)
    selected = dict(decision.get("selected_option") or {})
    risk_score = _safe_float(selected.get("risk_score"), 0.0)
    operational_fit = _safe_float(selected.get("operational_fit"), 0.5)
    weighted_score = _safe_float(decision.get("score"), 0.0)
    market_pressure = _average([_safe_float(item.get("severity"), 0.0) for item in signals if item.get("domain") == "market"])
    decision_kind = str(decision.get("decision") or "hold")
    success_score = _clamp(0.42 + (weighted_score * 0.45) - (risk_score * 0.2) + (operational_fit * 0.18) + (market_pressure * 0.12))
    realized_gain = 0.0
    outcome = "stabilized"
    if decision_kind == "approve":
        realized_gain = round(_safe_float(selected.get("required_capital"), 0.0) * max(0.0, success_score - 0.18), 2)
        outcome = "positive" if success_score >= 0.58 else "mixed"
    elif decision_kind == "revise":
        success_score = _clamp(0.52 + (1.0 - risk_score) * 0.18)
        outcome = "guarded"
    else:
        success_score = _clamp(0.48 + (1.0 - risk_score) * 0.14)
        outcome = "monitored"

    return {
        "evaluated_at": _now_iso(),
        "decision_id": decision.get("decision_id"),
        "outcome": outcome,
        "success_score": round(success_score, 6),
        "realized_gain": round(realized_gain, 2),
        "lessons": [
            "Gewichtete Entscheidung blieb innerhalb der Governance-Grenzen."
            if decision_kind != "approve" or risk_score <= _safe_float(state.get("policy", {}).get("max_risk"), 0.68)
            else "Genehmigte Aktion bewegt sich nah an der Risikogrenze."
        ],
    }


def feedback_update(state_like: Any, decision_packet_like: Any, execution_packet_like: Any, outcome_like: Any) -> dict[str, Any]:
    state = load_or_bootstrap_state(state_like)
    decision = _coerce_json(decision_packet_like) or {}
    execution = _coerce_json(execution_packet_like) or {}
    outcome = _coerce_json(outcome_like) or {}
    realized_gain = _safe_float(outcome.get("realized_gain"), 0.0)
    state["capital"]["liquidity"] = round(_safe_float(state["capital"].get("liquidity"), 0.0) + realized_gain, 2)
    state["risk"]["volatility"] = round(_clamp((_safe_float(state["risk"].get("volatility"), 0.0) * 0.82) + (_safe_float(decision.get("selected_option", {}).get("risk_score"), 0.0) * 0.18)), 6)
    state["risk"]["exposure"] = round(_clamp((_safe_float(state["risk"].get("exposure"), 0.0) * 0.78) + (_safe_float(outcome.get("success_score"), 0.0) * 0.12)), 6)

    priorities = dict(state.get("strategy", {}).get("priorities") or {})
    action = str(execution.get("action") or "")
    if action in {"scale_enterprise_capacity", "fund_partner_program"}:
        priorities["growth"] = round(_clamp(_safe_float(priorities.get("growth"), 0.5) + (_safe_float(outcome.get("success_score"), 0.0) - 0.5) * 0.1), 6)
    if action == "stabilize_compute_capacity":
        priorities["resilience"] = round(_clamp(_safe_float(priorities.get("resilience"), 0.5) + (_safe_float(outcome.get("success_score"), 0.0) - 0.5) * 0.12), 6)
    state["strategy"]["priorities"] = priorities

    history_entry = {
        "timestamp": _now_iso(),
        "decision_id": decision.get("decision_id"),
        "decision": decision.get("decision"),
        "action": execution.get("action"),
        "option_id": decision.get("selected_option", {}).get("option_id"),
        "outcome": outcome.get("outcome"),
        "success_score": outcome.get("success_score"),
        "realized_gain": outcome.get("realized_gain"),
    }
    state["decisions_history"] = [*list(state.get("decisions_history", [])), history_entry][-100:]
    state["last_outcome"] = outcome
    state["updated_at"] = _now_iso()
    return state


def build_narrative(decision_packet_like: Any, execution_packet_like: Any, outcome_like: Any, state_like: Any) -> dict[str, Any]:
    decision = _coerce_json(decision_packet_like) or {}
    execution = _coerce_json(execution_packet_like) or {}
    outcome = _coerce_json(outcome_like) or {}
    state = load_or_bootstrap_state(state_like)
    selected = dict(decision.get("selected_option") or {})
    summary = (
        f"CEO-System entschied {decision.get('decision', 'hold')} fuer {execution.get('action', 'monitor_market')}. "
        f"Gewichteter Score {round(_safe_float(decision.get('score'), 0.0), 3)}, "
        f"Risikowert {round(_safe_float(selected.get('risk_score'), 0.0), 3)}."
    )
    return {
        "agent": "NarrativeAgent",
        "generated_at": _now_iso(),
        "summary": summary,
        "why_now": selected.get("rationale") or decision.get("reason") or "",
        "what_to_watch": ", ".join(state.get("risk", {}).get("critical_flags", [])[:3]) or "Liquiditaet, Auslastung und Marktreaktion beobachten.",
    }


def market_event_payload(signals_like: Any, decision_packet_like: Any) -> dict[str, Any]:
    signals = merge_signal_batches(signals_like)
    decision = _coerce_json(decision_packet_like) or {}
    market_pressure = round(_average([_safe_float(item.get("severity"), 0.0) for item in signals if item.get("domain") == "market"]), 6)
    return {
        "event": "event.market.change",
        "active": market_pressure >= 0.55,
        "market_pressure": market_pressure,
        "selected_action": decision.get("recommended_action"),
        "top_signal": signals[0]["title"] if signals else "",
    }


def capacity_event_payload(state_like: Any, execution_packet_like: Any) -> dict[str, Any]:
    state = load_or_bootstrap_state(state_like)
    execution = _coerce_json(execution_packet_like) or {}
    utilization = round(_safe_float(state.get("operations", {}).get("utilization"), 0.0), 6)
    return {
        "event": "event.capacity.limit",
        "active": utilization >= 0.82,
        "utilization": utilization,
        "capacity": round(_safe_float(state.get("operations", {}).get("capacity"), 1.0), 6),
        "execution_action": execution.get("action"),
        "bottlenecks": list(state.get("operations", {}).get("bottlenecks") or [])[:5],
    }


def capital_event_payload(state_like: Any, decision_packet_like: Any) -> dict[str, Any]:
    state = load_or_bootstrap_state(state_like)
    decision = _coerce_json(decision_packet_like) or {}
    liquidity = _safe_float(state.get("capital", {}).get("liquidity"), 0.0)
    burn_rate = max(1.0, _safe_float(state.get("capital", {}).get("burn_rate"), 1.0))
    runway_months = liquidity / burn_rate
    return {
        "event": "event.capital.alert",
        "active": runway_months <= _safe_float(state.get("policy", {}).get("minimum_runway_months"), 3.0) + 1.0 or decision.get("decision") == "revise",
        "liquidity": round(liquidity, 2),
        "burn_rate": round(burn_rate, 2),
        "runway_months": round(runway_months, 3),
        "decision": decision.get("decision"),
    }


def build_report(
    state_like: Any,
    signals_like: Any,
    strategy_packet_like: Any,
    risk_packet_like: Any,
    capital_packet_like: Any,
    operations_packet_like: Any,
    decision_packet_like: Any,
    execution_packet_like: Any,
    outcome_like: Any,
    narrative_like: Any,
) -> dict[str, Any]:
    state = load_or_bootstrap_state(state_like)
    signals = merge_signal_batches(signals_like)
    strategy_packet = _coerce_json(strategy_packet_like) or {}
    risk_packet = _coerce_json(risk_packet_like) or {}
    capital_packet = _coerce_json(capital_packet_like) or {}
    operations_packet = _coerce_json(operations_packet_like) or {}
    decision = _coerce_json(decision_packet_like) or {}
    execution = _coerce_json(execution_packet_like) or {}
    outcome = _coerce_json(outcome_like) or {}
    narrative = _coerce_json(narrative_like) or {}
    selected = dict(decision.get("selected_option") or {})

    return {
        "generated_at": _now_iso(),
        "headline": f"CEO cycle {decision.get('decision', 'hold')} -> {execution.get('action', 'monitor_market')}",
        "decision": decision,
        "execution": execution,
        "outcome": outcome,
        "narrative": narrative,
        "signals": {
            "count": len(signals),
            "top_items": signals[:6],
        },
        "domain_state": {
            "capital": state.get("capital", {}),
            "operations": state.get("operations", {}),
            "strategy": state.get("strategy", {}),
            "risk": state.get("risk", {}),
            "market": state.get("market", {}),
            "policy": state.get("policy", {}),
        },
        "strategy_options": list(strategy_packet.get("options") or []),
        "risk_assessment": list(risk_packet.get("assessments") or []),
        "capital_plan": list(capital_packet.get("plans") or []),
        "operations_plan": list(operations_packet.get("plans") or []),
        "selected_summary": {
            "option_id": selected.get("option_id"),
            "action": selected.get("action"),
            "weighted_score": selected.get("weighted_score"),
            "required_capital": selected.get("required_capital"),
            "risk_score": selected.get("risk_score"),
        },
        "history_length": len(list(state.get("decisions_history", []))),
    }


def render_report_html(report_like: Any) -> str:
    report = _coerce_json(report_like) or {}
    decision = dict(report.get("decision") or {})
    execution = dict(report.get("execution") or {})
    outcome = dict(report.get("outcome") or {})
    narrative = dict(report.get("narrative") or {})
    state = dict(report.get("domain_state") or {})
    signals = list(report.get("signals", {}).get("top_items") or [])
    options = list(report.get("strategy_options") or [])
    rows = "".join(
        [
            "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                item.get("option_id", ""),
                item.get("action", ""),
                item.get("expected_gain", ""),
                item.get("required_capital", ""),
            )
            for item in options
        ]
    ) or "<tr><td colspan=\"4\">Keine Optionen</td></tr>"
    signal_items = "".join(
        [
            "<li><strong>{}</strong> [{} | {}] - {}</li>".format(
                item.get("title", ""),
                item.get("domain", ""),
                item.get("severity", ""),
                item.get("summary", ""),
            )
            for item in signals
        ]
    ) or "<li>Keine Signale</li>"
    return (
        "<!DOCTYPE html><html lang=\"de\"><head><meta charset=\"utf-8\">"
        "<title>Nova CEO Report</title>"
        "<style>"
        "body{font-family:Segoe UI,Arial,sans-serif;margin:32px;background:#0f172a;color:#e2e8f0;}"
        "section{background:#111827;border:1px solid #334155;border-radius:16px;padding:20px;margin-bottom:18px;}"
        "h1,h2{margin:0 0 12px 0;}table{width:100%;border-collapse:collapse;}"
        "th,td{padding:10px;border-bottom:1px solid #334155;text-align:left;vertical-align:top;}"
        "th{background:#1e293b;}ul{margin:0;padding-left:20px;}code{background:#1e293b;padding:2px 6px;border-radius:6px;}"
        ".metric{display:inline-block;margin-right:16px;font-weight:600;}"
        "</style></head><body>"
        f"<h1>{report.get('headline', 'Nova CEO Report')}</h1>"
        "<section>"
        f"<div class=\"metric\">Entscheidung: {decision.get('decision', 'hold')}</div>"
        f"<div class=\"metric\">Aktion: {execution.get('action', 'monitor_market')}</div>"
        f"<div class=\"metric\">Score: {decision.get('score', 0)}</div>"
        f"<div class=\"metric\">Outcome: {outcome.get('outcome', 'unknown')}</div>"
        "</section>"
        "<section><h2>Board-Narrativ</h2>"
        f"<p>{narrative.get('summary', '')}</p>"
        f"<p><strong>Warum jetzt:</strong> {narrative.get('why_now', '')}</p>"
        f"<p><strong>Beobachten:</strong> {narrative.get('what_to_watch', '')}</p>"
        "</section>"
        "<section><h2>Signale</h2><ul>"
        f"{signal_items}"
        "</ul></section>"
        "<section><h2>Strategieoptionen</h2><table><thead><tr><th>ID</th><th>Aktion</th><th>Expected Gain</th><th>Kapital</th></tr></thead><tbody>"
        f"{rows}"
        "</tbody></table></section>"
        "<section><h2>Domain State</h2>"
        f"<p><strong>Liquidity:</strong> {state.get('capital', {}).get('liquidity', '')}</p>"
        f"<p><strong>Burn Rate:</strong> {state.get('capital', {}).get('burn_rate', '')}</p>"
        f"<p><strong>Utilization:</strong> {state.get('operations', {}).get('utilization', '')}</p>"
        f"<p><strong>Demand:</strong> {state.get('market', {}).get('demand', '')}</p>"
        f"<p><strong>Volatility:</strong> {state.get('risk', {}).get('volatility', '')}</p>"
        "</section>"
        "</body></html>"
    )


def persist_runtime_artifacts(base_path_like: Any, report_like: Any, execution_like: Any, state_like: Any) -> dict[str, Any]:
    report = _coerce_json(report_like) or {}
    execution = _coerce_json(execution_like) or {}
    state = load_or_bootstrap_state(state_like)
    base_path = Path(str(base_path_like)).resolve(strict=False)
    runtime_dir = base_path / ".nova_ceo"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    report_path = runtime_dir / "ceo_report.json"
    html_path = runtime_dir / "ceo_report.html"
    execution_path = runtime_dir / "latest_execution.json"
    state_path = runtime_dir / "ceo_state.json"
    history_path = runtime_dir / "decision_history.jsonl"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_report_html(report), encoding="utf-8")
    execution_path.write_text(json.dumps(execution, ensure_ascii=False, indent=2), encoding="utf-8")
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"timestamp": _now_iso(), "decision": report.get("decision", {}), "execution": execution}, ensure_ascii=False) + "\n")
    return {
        "runtime_dir": str(runtime_dir),
        "report_path": str(report_path),
        "html_path": str(html_path),
        "execution_path": str(execution_path),
        "state_path": str(state_path),
        "history_path": str(history_path),
    }
