from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import math
import random
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


def _clamp_unit(value: Any, default: float = 0.5) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return float(default)


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[A-Za-z0-9_\\-\\u00C0-\\u024F]+", str(text or "").lower()):
        for candidate in [token, *re.split(r"[_\\-]+", token)]:
            candidate = str(candidate).strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            tokens.append(candidate)
    return tokens


def _jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    left_set = {str(item) for item in left if str(item)}
    right_set = {str(item) for item in right if str(item)}
    if not left_set or not right_set:
        return 0.0
    union = left_set.union(right_set)
    if not union:
        return 0.0
    return len(left_set.intersection(right_set)) / len(union)


def _signature_vector(text: str, *, dims: int = 12) -> list[float]:
    accum = [0.0] * dims
    tokens = _tokenize(text)
    if not tokens:
        return accum
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        for index in range(dims):
            accum[index] += ((digest[index] / 255.0) * 2.0) - 1.0
    norm = math.sqrt(sum(value * value for value in accum))
    if norm <= 1e-9:
        return [0.0] * dims
    return [value / norm for value in accum]


@dataclass
class MyceliaGenome:
    prompt_template: str
    provider: str
    model: str
    system_prompt: str = ""
    tool_names: list[str] = field(default_factory=list)
    preferred_caps: list[str] = field(default_factory=list)
    module_affinity: dict[str, float] = field(default_factory=dict)
    traits: dict[str, float] = field(default_factory=dict)
    safety_profile: str = "bounded-v1"
    mutation_rate: float = 0.18


@dataclass
class MyceliaMember:
    member_id: str
    population: str
    role_name: str
    genome: MyceliaGenome
    parent_ids: list[str] = field(default_factory=list)
    generation: int = 0
    lineage_depth: int = 0
    species_id: str = ""
    status: str = "active"
    assigned_modules: dict[str, Any] = field(default_factory=dict)
    average_fitness: float = 0.0
    last_fitness: float = 0.0
    fitness_samples: int = 0
    success_count: int = 0
    error_count: int = 0
    last_output: str = ""
    last_error: str = ""
    last_tick_at: float = 0.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass
class MyceliaPopulation:
    name: str
    goal: str
    seed_agents: list[str] = field(default_factory=list)
    target_size: int = 4
    mutation_rate: float = 0.18
    selection_pressure: float = 0.55
    elitism: int = 1
    namespace: str = "default"
    project: str = "default"
    auto_tick: bool = True
    allow_swarm: bool = True
    allow_tool_autowire: bool = True
    allow_sensor_autowire: bool = True
    allow_memory_autowire: bool = True
    status: str = "active"
    tick_count: int = 0
    last_input: str = ""
    last_summary: str = ""
    last_tick_at: float = 0.0
    created_at: float = field(default_factory=time.time)


class MyceliaRuntime:
    """Persistent population runtime for bounded, auditable agent evolution."""

    TRAIT_KEYS = (
        "analysis_depth",
        "caution_bias",
        "novelty_drive",
        "swarm_affinity",
        "tool_affinity",
        "sensor_affinity",
        "memory_affinity",
    )

    def __init__(self, storage_root: Path) -> None:
        self.storage_root = Path(storage_root).resolve()
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.storage_root / "mycelia_state.json"
        self.lineage_path = self.storage_root / "mycelia_lineage.jsonl"
        self.populations: dict[str, MyceliaPopulation] = {}
        self.members: dict[str, MyceliaMember] = {}
        self._load_state()

    def _atomic_write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(path)

    def _load_state(self) -> None:
        if not self.state_path.exists():
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        self.populations.clear()
        for item in payload.get("populations", []):
            if not isinstance(item, dict):
                continue
            try:
                population = MyceliaPopulation(
                    name=str(item.get("name") or ""),
                    goal=str(item.get("goal") or ""),
                    seed_agents=[str(value) for value in list(item.get("seed_agents") or []) if str(value).strip()],
                    target_size=max(2, int(item.get("target_size") or 4)),
                    mutation_rate=_clamp_unit(item.get("mutation_rate"), 0.18),
                    selection_pressure=_clamp_unit(item.get("selection_pressure"), 0.55),
                    elitism=max(1, int(item.get("elitism") or 1)),
                    namespace=str(item.get("namespace") or "default"),
                    project=str(item.get("project") or "default"),
                    auto_tick=bool(item.get("auto_tick", True)),
                    allow_swarm=bool(item.get("allow_swarm", True)),
                    allow_tool_autowire=bool(item.get("allow_tool_autowire", True)),
                    allow_sensor_autowire=bool(item.get("allow_sensor_autowire", True)),
                    allow_memory_autowire=bool(item.get("allow_memory_autowire", True)),
                    status=str(item.get("status") or "active"),
                    tick_count=max(0, int(item.get("tick_count") or 0)),
                    last_input=str(item.get("last_input") or ""),
                    last_summary=str(item.get("last_summary") or ""),
                    last_tick_at=float(item.get("last_tick_at") or 0.0),
                    created_at=float(item.get("created_at") or time.time()),
                )
            except Exception:
                continue
            if population.name:
                self.populations[population.name] = population
        self.members.clear()
        for item in payload.get("members", []):
            if not isinstance(item, dict):
                continue
            genome_payload = dict(item.get("genome") or {})
            genome = MyceliaGenome(
                prompt_template=str(genome_payload.get("prompt_template") or ""),
                provider=str(genome_payload.get("provider") or ""),
                model=str(genome_payload.get("model") or ""),
                system_prompt=str(genome_payload.get("system_prompt") or ""),
                tool_names=[str(value) for value in list(genome_payload.get("tool_names") or []) if str(value).strip()],
                preferred_caps=[str(value) for value in list(genome_payload.get("preferred_caps") or []) if str(value).strip()],
                module_affinity={str(key): _clamp_unit(value) for key, value in dict(genome_payload.get("module_affinity") or {}).items()},
                traits={str(key): _clamp_unit(value) for key, value in dict(genome_payload.get("traits") or {}).items()},
                safety_profile=str(genome_payload.get("safety_profile") or "bounded-v1"),
                mutation_rate=_clamp_unit(genome_payload.get("mutation_rate"), 0.18),
            )
            member = MyceliaMember(
                member_id=str(item.get("member_id") or ""),
                population=str(item.get("population") or ""),
                role_name=str(item.get("role_name") or ""),
                genome=genome,
                parent_ids=[str(value) for value in list(item.get("parent_ids") or []) if str(value).strip()],
                generation=max(0, int(item.get("generation") or 0)),
                lineage_depth=max(0, int(item.get("lineage_depth") or 0)),
                species_id=str(item.get("species_id") or ""),
                status=str(item.get("status") or "active"),
                assigned_modules=dict(item.get("assigned_modules") or {}),
                average_fitness=float(item.get("average_fitness") or 0.0),
                last_fitness=float(item.get("last_fitness") or 0.0),
                fitness_samples=max(0, int(item.get("fitness_samples") or 0)),
                success_count=max(0, int(item.get("success_count") or 0)),
                error_count=max(0, int(item.get("error_count") or 0)),
                last_output=str(item.get("last_output") or ""),
                last_error=str(item.get("last_error") or ""),
                last_tick_at=float(item.get("last_tick_at") or 0.0),
                created_at=float(item.get("created_at") or time.time()),
                updated_at=float(item.get("updated_at") or time.time()),
            )
            if member.member_id and member.population:
                self.members[member.member_id] = member
        for population_name in list(self.populations.keys()):
            self._reassign_species(population_name)

    def _save_state(self) -> None:
        payload = {
            "version": 1,
            "populations": [asdict(item) for item in sorted(self.populations.values(), key=lambda row: row.name)],
            "members": [self._member_row(item) for item in sorted(self.members.values(), key=lambda row: (row.population, row.created_at, row.member_id))],
        }
        self._atomic_write_json(self.state_path, payload)

    def _append_lineage_event(
        self,
        *,
        population: str,
        action: str,
        member_id: str = "",
        parent_ids: Iterable[str] | None = None,
        species_id: str = "",
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "event_id": f"lineage_{uuid.uuid4().hex[:12]}",
            "population": str(population or ""),
            "action": str(action or "").strip(),
            "member_id": str(member_id or ""),
            "parent_ids": [str(value) for value in list(parent_ids or []) if str(value).strip()],
            "species_id": str(species_id or ""),
            "details": dict(details or {}),
            "created_at": time.time(),
        }
        self.lineage_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lineage_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def _member_row(self, member: MyceliaMember) -> dict[str, Any]:
        payload = asdict(member)
        payload["genome"]["tool_names"] = list(dict.fromkeys(payload["genome"].get("tool_names") or []))
        payload["genome"]["preferred_caps"] = list(dict.fromkeys(payload["genome"].get("preferred_caps") or []))
        return payload

    def _population_row(self, population: MyceliaPopulation) -> dict[str, Any]:
        active = self.list_members(population.name, active_only=True)
        species = self.list_species(population.name)
        return {
            **asdict(population),
            "active_members": len(active),
            "archived_members": len(self.list_members(population.name, active_only=False)) - len(active),
            "species_count": len(species),
            "top_fitness": round(max((float(item["average_fitness"]) for item in active), default=0.0), 6),
        }

    def _normalize_traits(self, traits: dict[str, Any] | None = None, *, seed_text: str = "") -> dict[str, float]:
        base_vector = _signature_vector(seed_text or "mycelia", dims=len(self.TRAIT_KEYS))
        normalized: dict[str, float] = {}
        for index, key in enumerate(self.TRAIT_KEYS):
            seed_value = (base_vector[index] + 1.0) / 2.0
            normalized[key] = _clamp_unit(seed_value * 0.7 + 0.15, 0.5)
        for key, value in dict(traits or {}).items():
            if key in normalized:
                normalized[key] = _clamp_unit(value, normalized[key])
        return normalized

    def _member_signature_text(self, member: MyceliaMember) -> str:
        traits = " ".join(f"{key}:{round(float(value), 3)}" for key, value in sorted(member.genome.traits.items()))
        modules = " ".join(
            [
                " ".join(member.genome.tool_names),
                " ".join(member.genome.preferred_caps),
                " ".join(sorted(member.genome.module_affinity.keys())),
                member.role_name,
                member.genome.provider,
                member.genome.model,
                member.genome.prompt_template,
                member.genome.system_prompt,
                traits,
            ]
        )
        return modules.strip()

    def _species_id_for_member(self, member: MyceliaMember) -> str:
        vector = _signature_vector(self._member_signature_text(member), dims=10)
        bucket = "".join("p" if value >= 0.2 else "n" if value <= -0.2 else "z" for value in vector)
        return "species_" + hashlib.sha1(bucket.encode("utf-8")).hexdigest()[:8]

    def _reassign_species(self, population_name: str) -> list[dict[str, Any]]:
        members = self.members_for_population(population_name, active_only=False)
        if not members:
            return []
        for member in members:
            member.species_id = self._species_id_for_member(member)
            member.updated_at = time.time()
        return self.list_species(population_name)

    def _validate_genome(self, genome: MyceliaGenome) -> None:
        prompt_template = str(genome.prompt_template or "").strip()
        provider = str(genome.provider or "").strip()
        model = str(genome.model or "").strip()
        if not prompt_template:
            raise ValueError("mycelia genome prompt_template must not be empty")
        if len(prompt_template) > 2400:
            raise ValueError("mycelia genome prompt_template is too large")
        if len(str(genome.system_prompt or "")) > 2400:
            raise ValueError("mycelia genome system_prompt is too large")
        if not provider or not re.match(r"^[A-Za-z0-9_.-]+$", provider):
            raise ValueError("mycelia genome provider is invalid")
        if not model or not re.match(r"^[A-Za-z0-9_.:/-]+$", model):
            raise ValueError("mycelia genome model is invalid")
        if str(genome.safety_profile or "") != "bounded-v1":
            raise ValueError("mycelia genome safety_profile is unsupported")
        genome.tool_names = [str(value) for value in list(dict.fromkeys(genome.tool_names)) if str(value).strip()][:4]
        genome.preferred_caps = [str(value) for value in list(dict.fromkeys(genome.preferred_caps)) if str(value).strip()][:4]
        genome.mutation_rate = _clamp_unit(genome.mutation_rate, 0.18)
        genome.traits = self._normalize_traits(genome.traits, seed_text=prompt_template + " " + genome.system_prompt)
        genome.module_affinity = {str(key): _clamp_unit(value) for key, value in dict(genome.module_affinity or {}).items()}

    def _build_system_prompt_from_traits(self, base: str, traits: dict[str, float]) -> str:
        directives: list[str] = []
        if traits.get("analysis_depth", 0.0) >= 0.58:
            directives.append("Provide a structured, step-by-step analysis.")
        if traits.get("caution_bias", 0.0) >= 0.58:
            directives.append("Verify claims, state uncertainty, and avoid unsupported assertions.")
        if traits.get("novelty_drive", 0.0) >= 0.6:
            directives.append("Explore alternative strategies before converging on one answer.")
        if traits.get("tool_affinity", 0.0) >= 0.55:
            directives.append("Prefer explicit Nova-shell tools or modules when they improve reliability.")
        if traits.get("memory_affinity", 0.0) >= 0.55:
            directives.append("Reuse available memory context when it improves consistency.")
        if traits.get("sensor_affinity", 0.0) >= 0.55:
            directives.append("Incorporate relevant sensor evidence when available.")
        pieces = [str(base or "").strip(), *directives]
        merged = " ".join(piece for piece in pieces if piece).strip()
        return merged[:2400]

    def _genome_from_agent(self, agent: dict[str, Any], *, mutation_rate: float, goal: str) -> MyceliaGenome:
        prompt_template = str(agent.get("prompt_template") or "").strip()
        genome = MyceliaGenome(
            prompt_template=prompt_template,
            provider=str(agent.get("provider") or ""),
            model=str(agent.get("model") or ""),
            system_prompt=str(agent.get("system_prompt") or ""),
            tool_names=[],
            preferred_caps=["cpu", "py", "ai"],
            mutation_rate=mutation_rate,
        )
        genome.traits = self._normalize_traits(seed_text=" ".join([goal, prompt_template, genome.system_prompt, genome.provider, genome.model]))
        genome.system_prompt = self._build_system_prompt_from_traits(genome.system_prompt, genome.traits)
        self._validate_genome(genome)
        return genome

    def _new_member(
        self,
        population: MyceliaPopulation,
        *,
        role_name: str,
        genome: MyceliaGenome,
        parent_ids: Iterable[str] | None = None,
        generation: int = 0,
        lineage_depth: int = 0,
    ) -> MyceliaMember:
        self._validate_genome(genome)
        member = MyceliaMember(
            member_id=f"myc_{uuid.uuid4().hex[:10]}",
            population=population.name,
            role_name=str(role_name or population.name).strip() or population.name,
            genome=copy.deepcopy(genome),
            parent_ids=[str(value) for value in list(parent_ids or []) if str(value).strip()],
            generation=max(0, int(generation)),
            lineage_depth=max(0, int(lineage_depth)),
        )
        member.species_id = self._species_id_for_member(member)
        return member

    def create_population(
        self,
        name: str,
        *,
        goal: str,
        seed_agents: list[dict[str, Any]],
        target_size: int = 4,
        mutation_rate: float = 0.18,
        selection_pressure: float = 0.55,
        namespace: str = "default",
        project: str = "default",
        auto_tick: bool = True,
        allow_swarm: bool = True,
        allow_tool_autowire: bool = True,
        allow_sensor_autowire: bool = True,
        allow_memory_autowire: bool = True,
    ) -> dict[str, Any]:
        population_name = str(name or "").strip()
        if not population_name:
            raise ValueError("population name must not be empty")
        if population_name in self.populations:
            raise ValueError("mycelia population already exists")
        if not str(goal or "").strip():
            raise ValueError("mycelia population goal must not be empty")
        if not seed_agents:
            raise ValueError("mycelia population requires at least one seed agent")
        population = MyceliaPopulation(
            name=population_name,
            goal=str(goal).strip(),
            seed_agents=[str(item.get("name") or "") for item in seed_agents if str(item.get("name") or "").strip()],
            target_size=max(2, int(target_size)),
            mutation_rate=_clamp_unit(mutation_rate, 0.18),
            selection_pressure=_clamp_unit(selection_pressure, 0.55),
            elitism=1,
            namespace=str(namespace or "default").strip() or "default",
            project=str(project or "default").strip() or "default",
            auto_tick=bool(auto_tick),
            allow_swarm=bool(allow_swarm),
            allow_tool_autowire=bool(allow_tool_autowire),
            allow_sensor_autowire=bool(allow_sensor_autowire),
            allow_memory_autowire=bool(allow_memory_autowire),
        )
        self.populations[population.name] = population
        seeded_rows: list[dict[str, Any]] = []
        for agent in seed_agents:
            genome = self._genome_from_agent(agent, mutation_rate=population.mutation_rate, goal=population.goal)
            member = self._new_member(population, role_name=str(agent.get("name") or "agent"), genome=genome)
            self.members[member.member_id] = member
            seeded_rows.append(self._member_row(member))
            self._append_lineage_event(
                population=population.name,
                action="member_seeded",
                member_id=member.member_id,
                species_id=member.species_id,
                details={"role_name": member.role_name, "provider": member.genome.provider, "model": member.genome.model},
            )
        species = self._reassign_species(population.name)
        self._append_lineage_event(
            population=population.name,
            action="population_created",
            details={"goal": population.goal, "target_size": population.target_size, "seed_count": len(seeded_rows)},
        )
        self._save_state()
        return {
            "population": self._population_row(population),
            "seeded_members": seeded_rows,
            "species": species,
        }

    def get_population(self, name: str) -> MyceliaPopulation | None:
        return self.populations.get(str(name or "").strip())

    def list_populations(self) -> list[dict[str, Any]]:
        return [self._population_row(item) for item in sorted(self.populations.values(), key=lambda row: row.name)]

    def members_for_population(self, population_name: str, *, active_only: bool = False) -> list[MyceliaMember]:
        rows = [
            member
            for member in self.members.values()
            if member.population == population_name and (not active_only or member.status == "active")
        ]
        rows.sort(key=lambda item: (-float(item.average_fitness), item.generation, item.created_at, item.member_id))
        return rows

    def list_members(self, population_name: str, *, active_only: bool = False) -> list[dict[str, Any]]:
        return [self._member_row(member) for member in self.members_for_population(population_name, active_only=active_only)]

    def get_member(self, member_id: str) -> MyceliaMember | None:
        return self.members.get(str(member_id or "").strip())

    def list_species(self, population_name: str) -> list[dict[str, Any]]:
        groups: dict[str, list[MyceliaMember]] = {}
        for member in self.members_for_population(population_name, active_only=False):
            groups.setdefault(member.species_id or "species_unknown", []).append(member)
        rows: list[dict[str, Any]] = []
        for species_id, members in sorted(groups.items()):
            active_members = [item for item in members if item.status == "active"]
            champion = max(members, key=lambda item: (float(item.average_fitness), float(item.last_fitness), -item.generation))
            rows.append(
                {
                    "species_id": species_id,
                    "member_count": len(members),
                    "active_members": len(active_members),
                    "generations": sorted({int(item.generation) for item in members}),
                    "champion": champion.member_id,
                    "champion_role": champion.role_name,
                    "champion_fitness": round(float(champion.average_fitness), 6),
                    "members": [item.member_id for item in members],
                }
            )
        return rows

    def build_agent_definition(self, member_id: str) -> dict[str, Any]:
        member = self.get_member(member_id)
        if member is None:
            raise KeyError(member_id)
        return {
            "name": member.member_id,
            "prompt_template": member.genome.prompt_template,
            "provider": member.genome.provider,
            "model": member.genome.model,
            "system_prompt": member.genome.system_prompt,
        }

    def organize_modules(
        self,
        population_name: str,
        member_id: str,
        *,
        available_tools: list[dict[str, Any]],
        available_sensors: list[dict[str, Any]],
        mesh_caps: set[str],
        memory_scope: dict[str, str],
    ) -> dict[str, Any]:
        population = self.get_population(population_name)
        member = self.get_member(member_id)
        if population is None or member is None:
            raise KeyError(population_name if population is None else member_id)
        goal_text = " ".join([population.goal, member.role_name, member.genome.prompt_template, member.genome.system_prompt]).strip()
        goal_tokens = _tokenize(goal_text)
        assigned_tools: list[str] = []
        if population.allow_tool_autowire:
            scored_tools: list[tuple[float, str]] = []
            for tool in available_tools:
                descriptor = " ".join([str(tool.get("name") or ""), str(tool.get("description") or ""), json.dumps(tool.get("schema") or {}, ensure_ascii=False)]).strip()
                score = _jaccard(goal_tokens, _tokenize(descriptor))
                if score > 0.0:
                    scored_tools.append((score, str(tool.get("name") or "")))
            scored_tools.sort(key=lambda item: (-item[0], item[1]))
            tool_limit = max(1, min(3, int(1 + member.genome.traits.get("tool_affinity", 0.0) * 3)))
            assigned_tools = [name for _, name in scored_tools[:tool_limit] if name]
        assigned_sensors: list[str] = []
        sensor_recommendations: list[str] = []
        if population.allow_sensor_autowire:
            scored_sensors: list[tuple[float, str]] = []
            for sensor in available_sensors:
                descriptor = " ".join(
                    [
                        str(sensor.get("name") or ""),
                        str(sensor.get("category") or ""),
                        str(sensor.get("template") or ""),
                        " ".join(str(tag) for tag in list(sensor.get("tags") or [])),
                        str(sensor.get("last_summary") or ""),
                    ]
                ).strip()
                score = _jaccard(goal_tokens, _tokenize(descriptor))
                if score > 0.0:
                    scored_sensors.append((score, str(sensor.get("name") or "")))
            scored_sensors.sort(key=lambda item: (-item[0], item[1]))
            assigned_sensors = [name for _, name in scored_sensors[:2] if name]
            if not assigned_sensors:
                for token in goal_tokens:
                    if token in {"edge", "edge_ai", "inference", "local", "gpu", "datacenter", "rss", "trend"}:
                        sensor_recommendations.append(token)
        preferred_caps = {"cpu", "py", "ai"}
        if any(token in goal_tokens for token in ["gpu", "vision", "transformer", "embedding"]):
            preferred_caps.add("gpu")
        if member.genome.traits.get("swarm_affinity", 0.0) >= 0.55 and mesh_caps:
            preferred_caps.update(cap for cap in mesh_caps if cap in {"cpu", "py", "ai", "gpu"})
        if "gpu" in preferred_caps and "gpu" not in mesh_caps:
            preferred_caps.discard("gpu")
        use_swarm = bool(population.allow_swarm and mesh_caps and member.genome.traits.get("swarm_affinity", 0.0) >= 0.55)
        member.genome.tool_names = assigned_tools
        member.genome.preferred_caps = sorted(preferred_caps)
        member.genome.module_affinity = {
            "tools": _clamp_unit(member.genome.traits.get("tool_affinity", 0.0)),
            "sensors": _clamp_unit(member.genome.traits.get("sensor_affinity", 0.0)),
            "memory": _clamp_unit(member.genome.traits.get("memory_affinity", 0.0)),
            "swarm": _clamp_unit(member.genome.traits.get("swarm_affinity", 0.0)),
        }
        member.assigned_modules = {
            "tools": assigned_tools,
            "sensors": assigned_sensors,
            "sensor_recommendations": list(dict.fromkeys(sensor_recommendations)),
            "memory_scope": {"namespace": memory_scope.get("namespace", "default"), "project": memory_scope.get("project", "default")},
            "preferred_caps": sorted(preferred_caps),
            "use_swarm": use_swarm,
        }
        member.updated_at = time.time()
        self._save_state()
        return copy.deepcopy(member.assigned_modules)

    def compose_member_input(
        self,
        population_name: str,
        member_id: str,
        *,
        task_input: str,
        memory_hits: list[dict[str, Any]],
        sensor_rows: list[dict[str, Any]],
    ) -> str:
        population = self.get_population(population_name)
        member = self.get_member(member_id)
        if population is None or member is None:
            raise KeyError(population_name if population is None else member_id)
        assigned = dict(member.assigned_modules or {})
        lines = [
            "Nova-shell Mycelia execution context",
            f"Population: {population.name}",
            f"Goal: {population.goal}",
            f"Member: {member.role_name} ({member.member_id})",
            f"Generation: {member.generation}",
            f"Species: {member.species_id or 'unassigned'}",
        ]
        if assigned.get("tools"):
            lines.append("Assigned tools: " + ", ".join(str(item) for item in assigned.get("tools", [])))
        if assigned.get("preferred_caps"):
            lines.append("Preferred execution caps: " + ", ".join(str(item) for item in assigned.get("preferred_caps", [])))
        if assigned.get("sensors"):
            sensor_notes = []
            sensor_names = set(str(item) for item in assigned.get("sensors", []))
            for sensor in sensor_rows:
                if str(sensor.get("name") or "") not in sensor_names:
                    continue
                summary = str(sensor.get("last_summary") or "").strip()
                category = str(sensor.get("category") or "")
                if summary:
                    sensor_notes.append(f"{sensor['name']} ({category}): {summary}")
                else:
                    sensor_notes.append(f"{sensor['name']} ({category})")
            if sensor_notes:
                lines.append("Sensor context: " + " | ".join(sensor_notes))
        if memory_hits:
            previews = []
            for hit in memory_hits[:3]:
                text = str(hit.get("text") or hit.get("text_preview") or "").strip().replace("\n", " ")
                previews.append(f"{hit.get('id')}: {text[:140]}")
            if previews:
                lines.append("Memory context: " + " | ".join(previews))
        if assigned.get("sensor_recommendations"):
            lines.append("Autonomous module recommendation: " + ", ".join(str(item) for item in assigned.get("sensor_recommendations", [])))
        lines.append("")
        lines.append("Task input:")
        lines.append(task_input)
        return "\n".join(lines).strip()

    def score_execution(
        self,
        population_name: str,
        member_id: str,
        *,
        task_input: str,
        output_text: str,
        error_text: str,
        memory_hits: list[dict[str, Any]],
        atheria_hits: list[dict[str, Any]],
    ) -> dict[str, Any]:
        population = self.get_population(population_name)
        member = self.get_member(member_id)
        if population is None or member is None:
            raise KeyError(population_name if population is None else member_id)
        goal_tokens = _tokenize(" ".join([population.goal, task_input]))
        output_tokens = _tokenize(output_text)
        overlap = _jaccard(goal_tokens, output_tokens)
        success = 1.0 if not error_text else 0.0
        richness = min(1.0, len(output_tokens) / 80.0)
        diversity = min(1.0, len(set(output_tokens)) / max(1.0, len(output_tokens)))
        memory_alignment = 0.0
        if memory_hits:
            memory_alignment = max(0.0, min(1.0, (float(memory_hits[0].get("score") or 0.0) + 1.0) / 2.0))
        atheria_alignment = 0.0
        if atheria_hits:
            atheria_alignment = max(0.0, min(1.0, float(atheria_hits[0].get("score") or 0.0)))
        module_bonus = min(1.0, (len(member.assigned_modules.get("tools", [])) + len(member.assigned_modules.get("sensors", []))) / 4.0) * 0.08
        caution_bonus = 0.04 if member.genome.traits.get("caution_bias", 0.0) >= 0.55 and not error_text else 0.0
        score = (
            0.38 * success
            + 0.22 * overlap
            + 0.14 * richness
            + 0.06 * diversity
            + 0.10 * memory_alignment
            + 0.10 * atheria_alignment
            + module_bonus
            + caution_bonus
        )
        score = max(0.0, min(1.0, score))
        return {
            "fitness": round(score, 6),
            "metrics": {
                "success": round(success, 6),
                "goal_overlap": round(overlap, 6),
                "richness": round(richness, 6),
                "diversity": round(diversity, 6),
                "memory_alignment": round(memory_alignment, 6),
                "atheria_alignment": round(atheria_alignment, 6),
                "module_bonus": round(module_bonus, 6),
                "caution_bonus": round(caution_bonus, 6),
            },
        }

    def record_evaluation(
        self,
        population_name: str,
        member_id: str,
        *,
        output_text: str,
        error_text: str,
        score_payload: dict[str, Any],
        summary: str,
    ) -> dict[str, Any]:
        member = self.get_member(member_id)
        if member is None:
            raise KeyError(member_id)
        fitness = float(score_payload.get("fitness") or 0.0)
        member.last_fitness = fitness
        member.fitness_samples += 1
        member.average_fitness = ((member.average_fitness * max(0, member.fitness_samples - 1)) + fitness) / max(1, member.fitness_samples)
        if error_text:
            member.error_count += 1
            member.last_error = error_text
        else:
            member.success_count += 1
            member.last_error = ""
        member.last_output = output_text[:1200]
        member.last_tick_at = time.time()
        member.updated_at = member.last_tick_at
        event = self._append_lineage_event(
            population=population_name,
            action="evaluation",
            member_id=member.member_id,
            parent_ids=member.parent_ids,
            species_id=member.species_id,
            details={
                "fitness": round(fitness, 6),
                "summary": str(summary or "")[:240],
                "error": str(error_text or "")[:240],
                "metrics": dict(score_payload.get("metrics") or {}),
            },
        )
        self._save_state()
        return event

    def _mutate_traits(self, traits: dict[str, float], *, mutation_rate: float, rng: random.Random) -> dict[str, float]:
        mutated = {}
        amplitude = 0.08 + (mutation_rate * 0.25)
        for key in self.TRAIT_KEYS:
            base = _clamp_unit(traits.get(key), 0.5)
            delta = (rng.random() * 2.0 - 1.0) * amplitude
            mutated[key] = _clamp_unit(base + delta, base)
        return mutated

    def _mutate_genome(
        self,
        population: MyceliaPopulation,
        primary: MyceliaMember,
        secondary: MyceliaMember | None,
        *,
        available_tools: list[dict[str, Any]],
        available_sensors: list[dict[str, Any]],
    ) -> MyceliaGenome:
        seed_text = "|".join(
            [
                population.name,
                primary.member_id,
                secondary.member_id if secondary is not None else "",
                str(time.time_ns()),
            ]
        )
        rng = random.Random(int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest(), 16))
        base_prompt = primary.genome.prompt_template
        if secondary is not None and rng.random() >= 0.55:
            base_prompt = secondary.genome.prompt_template
        system_base = primary.genome.system_prompt
        if secondary is not None and secondary.genome.system_prompt and rng.random() >= 0.45:
            system_base = secondary.genome.system_prompt
        averaged_traits: dict[str, float] = {}
        for key in self.TRAIT_KEYS:
            left = _clamp_unit(primary.genome.traits.get(key), 0.5)
            right = _clamp_unit(secondary.genome.traits.get(key), left) if secondary is not None else left
            averaged_traits[key] = (left + right) / 2.0
        mutated_traits = self._mutate_traits(averaged_traits, mutation_rate=population.mutation_rate, rng=rng)
        available_tool_names = [str(item.get("name") or "") for item in available_tools if str(item.get("name") or "").strip()]
        inherited_tools = list(primary.genome.tool_names)
        if secondary is not None:
            inherited_tools.extend(secondary.genome.tool_names)
        inherited_tools = [value for value in list(dict.fromkeys(inherited_tools)) if value]
        if available_tool_names and population.allow_tool_autowire:
            candidate = available_tool_names[rng.randrange(len(available_tool_names))]
            if candidate not in inherited_tools and mutated_traits.get("tool_affinity", 0.0) >= 0.5:
                inherited_tools.append(candidate)
        inherited_tools = inherited_tools[: min(4, max(1, int(1 + mutated_traits.get("tool_affinity", 0.0) * 4)))]
        preferred_caps = set(primary.genome.preferred_caps)
        if secondary is not None:
            preferred_caps.update(secondary.genome.preferred_caps)
        if any(str(item.get("hardware_anchor") or "") == "gpu" for item in available_sensors):
            if mutated_traits.get("swarm_affinity", 0.0) >= 0.55:
                preferred_caps.add("gpu")
        preferred_caps.update({"cpu", "py", "ai"})
        module_affinity = {
            "tools": _clamp_unit(mutated_traits.get("tool_affinity", 0.0)),
            "sensors": _clamp_unit(mutated_traits.get("sensor_affinity", 0.0)),
            "memory": _clamp_unit(mutated_traits.get("memory_affinity", 0.0)),
            "swarm": _clamp_unit(mutated_traits.get("swarm_affinity", 0.0)),
        }
        genome = MyceliaGenome(
            prompt_template=base_prompt,
            provider=primary.genome.provider,
            model=primary.genome.model,
            system_prompt=self._build_system_prompt_from_traits(system_base, mutated_traits),
            tool_names=inherited_tools,
            preferred_caps=sorted(preferred_caps),
            module_affinity=module_affinity,
            traits=mutated_traits,
            mutation_rate=population.mutation_rate,
        )
        self._validate_genome(genome)
        return genome

    def breed(
        self,
        population_name: str,
        *,
        count: int = 1,
        available_tools: list[dict[str, Any]],
        available_sensors: list[dict[str, Any]],
        reason: str = "manual",
    ) -> dict[str, Any]:
        population = self.get_population(population_name)
        if population is None:
            raise KeyError(population_name)
        active = self.members_for_population(population_name, active_only=True)
        if not active:
            raise ValueError("mycelia population has no active members to breed")
        created: list[dict[str, Any]] = []
        sorted_members = sorted(active, key=lambda item: (float(item.average_fitness), float(item.last_fitness), -item.generation), reverse=True)
        for index in range(max(1, int(count))):
            primary = sorted_members[index % len(sorted_members)]
            secondary = None
            for candidate in sorted_members:
                if candidate.member_id == primary.member_id:
                    continue
                if candidate.species_id != primary.species_id:
                    secondary = candidate
                    break
            if secondary is None and len(sorted_members) > 1:
                secondary = sorted_members[(index + 1) % len(sorted_members)]
            genome = self._mutate_genome(population, primary, secondary, available_tools=available_tools, available_sensors=available_sensors)
            role_name = f"{primary.role_name}_g{primary.generation + 1}"
            member = self._new_member(
                population,
                role_name=role_name,
                genome=genome,
                parent_ids=[primary.member_id, *([secondary.member_id] if secondary is not None else [])],
                generation=max(primary.generation, secondary.generation if secondary is not None else primary.generation) + 1,
                lineage_depth=max(primary.lineage_depth, secondary.lineage_depth if secondary is not None else primary.lineage_depth) + 1,
            )
            self.members[member.member_id] = member
            created.append(self._member_row(member))
            self._append_lineage_event(
                population=population.name,
                action="member_bred",
                member_id=member.member_id,
                parent_ids=member.parent_ids,
                species_id=member.species_id,
                details={"reason": reason, "role_name": member.role_name},
            )
        species = self._reassign_species(population.name)
        self._save_state()
        return {"created": created, "species": species}

    def select(self, population_name: str, *, keep: int | None = None, reason: str = "manual") -> dict[str, Any]:
        population = self.get_population(population_name)
        if population is None:
            raise KeyError(population_name)
        active = self.members_for_population(population_name, active_only=True)
        if not active:
            return {"kept": [], "archived": [], "species": self.list_species(population_name)}
        keep_count = max(population.elitism, int(keep or population.target_size))
        ranking = sorted(active, key=lambda item: (float(item.average_fitness), float(item.last_fitness), -item.generation), reverse=True)
        champions: dict[str, str] = {}
        for member in ranking:
            champions.setdefault(member.species_id or "species_unknown", member.member_id)
        protected: list[str] = []
        for member in ranking[: population.elitism]:
            protected.append(member.member_id)
        for member_id in champions.values():
            if member_id not in protected:
                protected.append(member_id)
        for member in ranking:
            if len(protected) >= keep_count:
                break
            if member.member_id not in protected:
                protected.append(member.member_id)
        archived: list[str] = []
        for member in ranking:
            if member.member_id in protected:
                continue
            member.status = "archived"
            member.updated_at = time.time()
            archived.append(member.member_id)
            self._append_lineage_event(
                population=population.name,
                action="member_archived",
                member_id=member.member_id,
                parent_ids=member.parent_ids,
                species_id=member.species_id,
                details={"reason": reason, "average_fitness": round(float(member.average_fitness), 6)},
            )
        species = self._reassign_species(population.name)
        self._save_state()
        return {"kept": protected, "archived": archived, "species": species}

    def summarize_fitness(self, population_name: str) -> list[dict[str, Any]]:
        rows = []
        for member in self.members_for_population(population_name, active_only=False):
            rows.append(
                {
                    "member_id": member.member_id,
                    "role_name": member.role_name,
                    "status": member.status,
                    "generation": member.generation,
                    "species_id": member.species_id,
                    "average_fitness": round(float(member.average_fitness), 6),
                    "last_fitness": round(float(member.last_fitness), 6),
                    "fitness_samples": member.fitness_samples,
                    "success_count": member.success_count,
                    "error_count": member.error_count,
                }
            )
        rows.sort(key=lambda item: (-float(item["average_fitness"]), -float(item["last_fitness"]), item["member_id"]))
        return rows

    def lineage(self, population_name: str, *, member_id: str = "", limit: int = 50) -> list[dict[str, Any]]:
        if not self.lineage_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with self.lineage_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                with contextlib.suppress(Exception):
                    item = json.loads(line)
                    if str(item.get("population") or "") != population_name:
                        continue
                    if member_id and str(item.get("member_id") or "") != member_id:
                        continue
                    rows.append(item)
        rows.sort(key=lambda item: float(item.get("created_at") or 0.0), reverse=True)
        return rows[: max(1, int(limit))]

    def mark_population_tick(self, population_name: str, *, input_text: str, summary: str = "") -> dict[str, Any]:
        population = self.get_population(population_name)
        if population is None:
            raise KeyError(population_name)
        population.tick_count += 1
        population.last_input = input_text
        population.last_summary = summary[:600]
        population.last_tick_at = time.time()
        self._append_lineage_event(
            population=population.name,
            action="population_tick",
            details={"tick_count": population.tick_count, "summary": population.last_summary},
        )
        self._save_state()
        return self._population_row(population)

    def stop_population(self, population_name: str) -> dict[str, Any]:
        population = self.get_population(population_name)
        if population is None:
            raise KeyError(population_name)
        population.status = "stopped"
        self._append_lineage_event(population=population.name, action="population_stopped")
        self._save_state()
        return self._population_row(population)

    def population_snapshot(self, population_name: str) -> dict[str, Any]:
        population = self.get_population(population_name)
        if population is None:
            raise KeyError(population_name)
        return {
            "population": self._population_row(population),
            "members": self.list_members(population_name, active_only=False),
            "species": self.list_species(population_name),
            "fitness": self.summarize_fitness(population_name),
        }
