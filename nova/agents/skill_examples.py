from __future__ import annotations

import json
import re
from pathlib import Path


DEFAULT_PROVIDER = "atheria"
DEFAULT_MODEL = "atheria-core"
NON_PORTABLE_SKILLS = {
    "deploy-to-vercel": "requires Vercel deployment infrastructure and external deploy/link flows that are not native Nova-shell capabilities",
    "vercel-cli-with-tokens": "requires Vercel CLI token workflows, .vercel project state, and external Vercel service access",
    "web-design-guidelines": "requires fetching live guidelines from a separate upstream repository instead of carrying self-contained local rule content",
}
NON_PORTABLE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\bvercel\s+(deploy|login|link|inspect|teams|ls|whoami|env|domains)\b", re.IGNORECASE),
        "contains Vercel CLI operational steps instead of Nova-shell-native logic",
    ),
    (
        re.compile(r"VERCEL_TOKEN|\.vercel/|vercel\.com/account/tokens|claim URL|/mnt/skills/|resources/deploy", re.IGNORECASE),
        "references external Vercel credentials, project state, or upstream deploy scripts",
    ),
    (
        re.compile(r"Use WebFetch|raw\.githubusercontent\.com/.+/command\.md|Fetch fresh guidelines before each review", re.IGNORECASE),
        "requires live retrieval of external guideline content instead of local self-contained skill data",
    ),
)


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value.strip().lower()).strip("_")
    return cleaned or "skill"


def ns_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    metadata: dict[str, str] = {}
    end_index = None
    for index in range(1, len(lines)):
        line = lines[index]
        if line.strip() == "---":
            end_index = index
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"')
    if end_index is None:
        return {}, text
    body = "\n".join(lines[end_index + 1 :]).strip()
    return metadata, body


def strip_markdown(text: str, *, limit: int = 700) -> str:
    lines: list[str] = []
    in_code = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        line = re.sub(r"^#+\s*", "", line)
        line = re.sub(r"^[-*]\s*", "", line)
        line = re.sub(r"`([^`]*)`", r"\1", line)
        line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
        line = re.sub(r"\*([^*]+)\*", r"\1", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    payload = " ".join(lines)
    return payload[:limit].rstrip()


def read_skill_summary(skill_dir: Path) -> tuple[str, str]:
    skill_file = skill_dir / "SKILL.md"
    text = skill_file.read_text(encoding="utf-8")
    metadata, body = parse_front_matter(text)
    title = metadata.get("name") or skill_dir.name
    summary = strip_markdown(body, limit=900)
    return title, summary


def read_rule_payload(rule_path: Path) -> dict[str, str]:
    metadata, body = parse_front_matter(rule_path.read_text(encoding="utf-8"))
    title = metadata.get("title") or next((line.lstrip("# ").strip() for line in body.splitlines() if line.strip().startswith("#")), rule_path.stem.replace("-", " "))
    impact = metadata.get("impact", "").strip()
    tags = metadata.get("tags", "").strip()
    summary = strip_markdown(body, limit=650)
    return {
        "name": rule_path.stem,
        "title": title,
        "impact": impact,
        "tags": tags,
        "summary": summary,
    }


def build_router_agent(skill_slug: str, display_name: str, agent_catalog: list[dict[str, str]], memory_name: str) -> str:
    router_name = f"{skill_slug}_router"
    catalog_lines = [f"{item['agent_name']}: {item['title']}" for item in agent_catalog]
    system_prompt = (
        f"Du bist der Router fuer das Skill-Buendel {display_name}. "
        "Ordne jede Anfrage den passendsten spezialisierten Agenten zu. "
        "Antworte knapp und nenne 1 bis 3 Agentennamen mit Begruendung. "
        "Verwende nur Agenten aus diesem Katalog: "
        + "; ".join(catalog_lines[:80])
    )
    prompt = (
        "Ordne die Anfrage den relevantesten Spezialagenten zu. "
        "Format: Agenten: <name1>, <name2>. Grund: <kurz>. "
        "Anfrage:\n\n{{input}}"
    )
    return "\n".join(
        [
            f"agent {router_name} {{",
            f"  provider: {DEFAULT_PROVIDER}",
            f"  model: {DEFAULT_MODEL}",
            f"  memory: {memory_name}",
            f"  system_prompt: {ns_string(system_prompt)}",
            f"  prompts: {{v1: {ns_string(prompt)}}}",
            "  prompt_version: v1",
            "}",
            "",
        ]
    )


def build_rule_agent(skill_slug: str, skill_title: str, rule: dict[str, str], memory_name: str) -> str:
    agent_name = f"{skill_slug}_{slugify(rule['name'])}"
    parts = [
        f"Du bist ein spezialisierter Nova-shell-Agent fuer die Regel {rule['title']} aus dem Skill {skill_title}.",
    ]
    if rule["impact"]:
        parts.append(f"Wirkung: {rule['impact']}.")
    if rule["tags"]:
        parts.append(f"Tags: {rule['tags']}.")
    if rule["summary"]:
        parts.append(f"Hintergrund: {rule['summary']}")
    parts.append("Arbeite konkret, code-nah und mit klaren Verbesserungsschritten.")
    system_prompt = " ".join(parts)
    prompt = (
        f"Pruefe oder verbessere den folgenden Input strikt nach der Regel {rule['title']}. "
        "Antworte mit: 1. Befund 2. Empfohlene Aenderung 3. Beispiel oder Patch-Hinweis.\n\n{{input}}"
    )
    return "\n".join(
        [
            f"agent {agent_name} {{",
            f"  provider: {DEFAULT_PROVIDER}",
            f"  model: {DEFAULT_MODEL}",
            f"  memory: {memory_name}",
            f"  system_prompt: {ns_string(system_prompt)}",
            f"  prompts: {{v1: {ns_string(prompt)}}}",
            "  prompt_version: v1",
            "}",
            "",
        ]
    )


def build_single_skill_agent(skill_slug: str, display_name: str, summary: str, memory_name: str) -> str:
    agent_name = f"{skill_slug}_generalist"
    system_prompt = (
        f"Du bist der Generalist fuer das Skill {display_name}. "
        f"Nutze dieses Wissen als Grundlage: {summary} "
        "Antworte umsetzungsnah, knapp und mit konkreten Schritten."
    )
    prompt = "Bearbeite die Anfrage mit dem eingebetteten Skill-Wissen.\n\n{{input}}"
    return "\n".join(
        [
            f"agent {agent_name} {{",
            f"  provider: {DEFAULT_PROVIDER}",
            f"  model: {DEFAULT_MODEL}",
            f"  memory: {memory_name}",
            f"  system_prompt: {ns_string(system_prompt)}",
            f"  prompts: {{v1: {ns_string(prompt)}}}",
            "  prompt_version: v1",
            "}",
            "",
        ]
    )


def build_skill_program(skill_dir: Path) -> tuple[str, dict[str, object]]:
    skill_title, skill_summary = read_skill_summary(skill_dir)
    skill_slug = slugify(skill_dir.name)
    memory_name = f"{skill_slug}_memory"
    lines = [
        f"state {memory_name} {{",
        "  backend: atheria",
        f"  namespace: {skill_slug}",
        "}",
        "",
    ]

    rule_dir = skill_dir / "rules"
    agent_catalog: list[dict[str, str]] = []
    if rule_dir.exists():
        rules = [read_rule_payload(path) for path in sorted(rule_dir.glob("*.md")) if not path.name.startswith("_")]
        for rule in rules:
            agent_name = f"{skill_slug}_{slugify(rule['name'])}"
            agent_catalog.append({"agent_name": agent_name, "title": rule["title"]})
        if agent_catalog:
            lines.append(build_router_agent(skill_slug, skill_title, agent_catalog, memory_name))
        for rule in rules:
            lines.append(build_rule_agent(skill_slug, skill_title, rule, memory_name))
    else:
        lines.append(build_single_skill_agent(skill_slug, skill_title, skill_summary, memory_name))
        agent_catalog.append({"agent_name": f"{skill_slug}_generalist", "title": skill_title})

    text = "\n".join(lines).strip() + "\n"
    metadata = {
        "skill": skill_dir.name,
        "agent_count": len(agent_catalog) + (1 if rule_dir.exists() and agent_catalog else 0),
        "router": f"{skill_slug}_router" if rule_dir.exists() and agent_catalog else "",
        "agents": [item["agent_name"] for item in agent_catalog],
        "portable": True,
    }
    return text, metadata


def inspect_skills(skills_root: Path) -> dict[str, dict[str, dict[str, object]]]:
    portable: dict[str, dict[str, object]] = {}
    skipped: dict[str, dict[str, object]] = {}
    for skill_dir in sorted(path for path in skills_root.iterdir() if path.is_dir()):
        title, _summary = read_skill_summary(skill_dir)
        reasons: list[str] = []
        explicit_reason = NON_PORTABLE_SKILLS.get(skill_dir.name)
        if explicit_reason:
            reasons.append(explicit_reason)
        skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        for pattern, reason in NON_PORTABLE_PATTERNS:
            if pattern.search(skill_text) and reason not in reasons:
                reasons.append(reason)
        payload = {
            "skill": skill_dir.name,
            "title": title,
            "path": str(skill_dir),
            "portable": not reasons,
            "reasons": reasons,
        }
        if reasons:
            skipped[skill_dir.name] = payload
        else:
            portable[skill_dir.name] = payload
    return {"portable": portable, "skipped": skipped}


def generate_examples(skills_root: Path, output_dir: Path, *, include_nonportable: bool = False) -> dict[str, dict[str, object]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict[str, object]] = {}
    inventory = inspect_skills(skills_root)
    allowed_skills = set(inventory["portable"].keys())
    if include_nonportable:
        allowed_skills.update(inventory["skipped"].keys())
    for skill_dir in sorted(path for path in skills_root.iterdir() if path.is_dir()):
        if skill_dir.name not in allowed_skills:
            continue
        program_text, metadata = build_skill_program(skill_dir)
        file_name = f"{slugify(skill_dir.name)}_agents.ns"
        target = output_dir / file_name
        target.write_text(program_text, encoding="utf-8")
        manifest[skill_dir.name] = {
            **metadata,
            "file_name": file_name,
            "path": str(target),
        }
    return manifest
