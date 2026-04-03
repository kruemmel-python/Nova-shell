from __future__ import annotations

import ast
import fnmatch
import json
import re
import shutil
from pathlib import Path
from typing import Any


DEFAULT_GOAL = (
    "Verbessere Lesbarkeit, Robustheit und Wartbarkeit, ohne das beabsichtigte Verhalten "
    "oder die oeffentliche Schnittstelle unnoetig zu brechen."
)
DEFAULT_MAX_SOURCE_CHARS = 7000
DEFAULT_MAX_PROJECT_FILES = 6
DEFAULT_MAX_FILE_CHARS = 3000
DEFAULT_PROJECT_EXCLUDES = [
    ".git/**",
    ".nova/**",
    ".nova_code_improve/**",
    "generated/**",
    "__pycache__/**",
    "node_modules/**",
    "dist/**",
    "build/**",
]
LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".c": "c",
    ".cs": "csharp",
    ".json": "json",
    ".md": "markdown",
    ".txt": "text",
}
SUFFIX_BY_LANGUAGE = {
    "python": ".py",
    "javascript": ".js",
    "typescript": ".ts",
    "java": ".java",
    "go": ".go",
    "rust": ".rs",
    "cpp": ".cpp",
    "c": ".c",
    "csharp": ".cs",
    "json": ".json",
    "markdown": ".md",
    "text": ".txt",
}
VARIANT_PROFILES = {
    "refactor": {
        "title": "Struktur und Lesbarkeit",
        "focus": "Reduziere unnoetige Komplexitaet, verbessere Benennungen und zerlege den Ablauf in klarere Schritte.",
    },
    "reliability": {
        "title": "Korrektheit und Robustheit",
        "focus": "Staerke defensive Behandlung von Randfaellen, Eingabevalidierung, Fehlerverhalten und Verhaltenstreue.",
    },
    "simplify": {
        "title": "Direktheit und Wartbarkeit",
        "focus": "Mache den Code kuerzer und direkter, aber behalte das Zielverhalten und die Lesbarkeit im Blick.",
    },
}


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


def _coerce_request_object(request_like: Any) -> dict[str, Any]:
    if isinstance(request_like, dict):
        return dict(request_like)
    if isinstance(request_like, list):
        if len(request_like) == 1 and isinstance(request_like[0], dict):
            return dict(request_like[0])
        return {"source_code": json.dumps(request_like, ensure_ascii=False, indent=2)}
    if isinstance(request_like, str):
        stripped = request_like.strip()
        if not stripped:
            return {}
        if stripped.startswith("{"):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                return {"source_code": request_like}
            if isinstance(parsed, dict):
                return parsed
        return {"source_code": request_like}
    if request_like is None:
        return {}
    return {"source_code": str(request_like)}


def _resolve_path(base_path: Path, raw_path: Any) -> Path:
    candidate = Path(str(raw_path))
    if candidate.is_absolute():
        return candidate
    return (base_path / candidate).resolve(strict=False)


def _default_output_path(base_path: Path, input_name: str, language: str) -> Path:
    suffix = Path(input_name).suffix or SUFFIX_BY_LANGUAGE.get(language, ".txt")
    stem = Path(input_name).stem or "source"
    return (base_path / "generated" / f"{stem}.improved{suffix}").resolve(strict=False)


def _default_project_output_path(base_path: Path, input_name: str) -> Path:
    stem = Path(input_name).stem or "project"
    return (base_path / "generated" / f"{stem}.improved").resolve(strict=False)


def _default_report_path(base_path: Path, input_name: str) -> Path:
    stem = Path(input_name).stem or "source"
    return (base_path / ".nova_code_improve" / f"{stem}.report.json").resolve(strict=False)


def _infer_language(source_path: Path | None, request: dict[str, Any]) -> str:
    explicit = str(request.get("language") or "").strip().lower()
    if explicit:
        return explicit
    if source_path is not None:
        inferred = LANGUAGE_BY_SUFFIX.get(source_path.suffix.lower())
        if inferred:
            return inferred
    return "text"


def _normalize_constraints(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []


def _normalize_patterns(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []


def _line_count(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + 1


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    clipped = text[: max(0, max_chars - 80)].rstrip()
    return clipped + "\n# ... source truncated for prompt budget ...\n", True


def _strip_list_prefix(line: str) -> str:
    return re.sub(r"^\s*(?:[-*+]\s+|\d+\.\s+)?", "", line).strip()


def _strip_heading_prefix(line: str) -> str:
    return re.sub(r"^\s*#{1,6}\s*", "", line).strip()


def _extract_label_from_line(line: str, label: str) -> str | None:
    cleaned = _strip_list_prefix(_strip_heading_prefix(line))
    if not cleaned:
        return None
    label_lower = label.lower()
    lower = cleaned.lower()
    prefixes = (
        f"{label_lower}:",
        f"**{label_lower}:**",
        f"**{label_lower}**:",
        f"__{label_lower}:__",
        f"__{label_lower}__:",
    )
    for prefix in prefixes:
        if lower.startswith(prefix):
            return cleaned[len(prefix) :].strip()
    return None


def _line_has_any_label(line: str, labels: list[str] | tuple[str, ...]) -> bool:
    return any(_extract_label_from_line(line, label) is not None for label in labels)


def _extract_label(text: str, label: str) -> str:
    for line in text.splitlines():
        value = _extract_label_from_line(line, label)
        if value is not None:
            return value
    return ""


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _clamp_score(value: float) -> float:
    return max(0.0, min(1.0, value))


def _strip_fence_markers(text: str) -> str:
    lines = text.strip().splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_labeled_section(text: str, label: str, stop_labels: list[str] | tuple[str, ...]) -> str:
    lines = text.splitlines()
    collecting = False
    collected: list[str] = []
    for line in lines:
        if not collecting:
            value = _extract_label_from_line(line, label)
            if value is not None:
                collecting = True
                if value:
                    collected.append(value)
                continue
        else:
            if _line_has_any_label(line, stop_labels):
                break
            collected.append(line)
    return "\n".join(collected).strip()


def _extract_balanced_json_object(text: str) -> str:
    start = -1
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if start < 0:
            if char == "{":
                start = index
                depth = 1
                in_string = False
                escaped = False
            continue
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""


def _extract_code_block(text: str) -> str:
    match = re.search(r"```[^\n]*\n(.*?)```", text, flags=re.DOTALL)
    if match:
        return match.group(1).strip("\n")
    section = _extract_labeled_section(text, "Code", ["Begruendung", "Tests", "Warum", "Dateien", "Titel", "Score", "Strategie"])
    if section:
        return _strip_fence_markers(section)
    lines = text.splitlines()
    stop_pattern = re.compile(
        r"^\s*(?:[-*+]\s+|\d+\.\s+)?(?:#{1,6}\s*)?(?:\*\*|__)?(?:titel|score|strategie|begruendung|tests|warum|dateien|code)(?:\*\*|__)?\s*:",
        flags=re.IGNORECASE,
    )
    code_pattern = re.compile(
        r"^\s*(?:def |class |if |for |while |try:|with |import |from |return\b|const\b|let\b|var\b|function\b|public\b|private\b|package\b|#include\b|fn\b|type\b|interface\b|enum\b)"
    )
    start_index = -1
    for index, line in enumerate(lines):
        if stop_pattern.match(line):
            continue
        if code_pattern.match(line):
            start_index = index
            break
    if start_index < 0:
        return ""
    collected: list[str] = []
    for line in lines[start_index:]:
        if _line_has_any_label(line, ["Begruendung", "Tests", "Warum", "Titel", "Score", "Strategie", "Dateien"]):
            break
        collected.append(line)
    return "\n".join(collected).strip()


def _recover_python_code_slice(text: str) -> str:
    lines = text.splitlines()
    if not lines:
        return ""
    code_pattern = re.compile(
        r"^\s*(?:@|async\s+def |def |class |import |from |if __name__\s*==\s*['\"]__main__['\"]\s*:|[A-Za-z_][A-Za-z0-9_]*\s*=)"
    )
    candidate_starts: list[int] = []
    for index, raw_line in enumerate(lines):
        line = _strip_heading_prefix(raw_line).rstrip()
        if not line.strip():
            continue
        if _line_has_any_label(line, ["Begruendung", "Tests", "Warum", "Titel", "Score", "Strategie", "Dateien", "Code"]):
            continue
        if code_pattern.match(line):
            candidate_starts.append(index)
    if 0 not in candidate_starts:
        candidate_starts.append(0)
    tried: set[tuple[int, int]] = set()
    for start in sorted(set(candidate_starts)):
        for end in range(len(lines), start, -1):
            key = (start, end)
            if key in tried:
                continue
            tried.add(key)
            candidate = "\n".join(lines[start:end]).strip()
            if not candidate:
                continue
            try:
                compile(candidate, "<recovered>", "exec")
                return candidate
            except Exception:
                continue
    return ""


def _candidate_is_actionable(candidate_like: Any) -> bool:
    candidate = dict(candidate_like or {})
    return bool(candidate.get("has_code")) and bool(candidate.get("syntax_ok")) and bool(candidate.get("changed"))


def build_candidate_repair_prompt(
    request_like: Any,
    review_text_like: Any,
    candidate_text_like: Any,
    candidate_like: Any,
    variant: str,
) -> str:
    request = dict(request_like)
    review_text = extract_agent_text(review_text_like)
    candidate_text = extract_agent_text(candidate_text_like)
    candidate = dict(candidate_like or {})
    primary_prompt = build_candidate_prompt(request, review_text, variant)
    if _candidate_is_actionable(candidate):
        status_note = (
            "Die vorige Antwort war bereits brauchbar. Wiederhole dieselbe Loesung jetzt strikt nur im geforderten Ausgabeformat, ohne Einleitung oder Zusatztext."
        )
    else:
        status_note = (
            "Die vorige Antwort war nicht parsebar oder nicht syntaktisch valide. Wiederhole die Aufgabe jetzt strikt im geforderten Ausgabeformat."
        )
    if request.get("request_mode") == "project":
        rules = "\n".join(
            [
                "- Antworte nur mit Titel, Score, Strategie, Dateien, Begruendung, Tests.",
                "- Im Feld Dateien darf nur ein JSON-Objekt mit relativen Dateipfaden stehen.",
                "- Keine Einleitung vor dem JSON-Block und keine prose im JSON.",
                "- Keine Diffs, keine Platzhalter, keine TODOs.",
            ]
        )
    else:
        rules = "\n".join(
            [
                "- Antworte nur mit Titel, Score, Strategie, Code, Begruendung, Tests.",
                "- Vor dem Codeblock keine Einleitung wie 'Hier ist...' oder Erklaerungen.",
                "- Im Feld Code nur vollstaendiger kompilierbarer Dateiinhalt.",
                "- Keine Diffs, keine Platzhalter, keine TODOs.",
            ]
        )
    previous_excerpt = _truncate(candidate_text, 1800)[0]
    return (
        f"{status_note}\n"
        f"Strikte Regeln:\n{rules}\n\n"
        "Vorige Antwort:\n"
        f"{previous_excerpt}\n\n"
        f"{primary_prompt}"
    )


def select_candidate_version(candidate_id: str, request_like: Any, primary_candidate_like: Any, repair_text_like: Any) -> dict[str, Any]:
    primary = dict(primary_candidate_like or {})
    if _candidate_is_actionable(primary):
        primary["repair_used"] = False
        return primary
    repaired = parse_candidate_response(candidate_id, request_like, repair_text_like)
    repaired["repair_used"] = _candidate_is_actionable(repaired)
    if _candidate_is_actionable(repaired):
        return repaired
    primary["repair_used"] = False
    return primary


def _extract_project_json_block(text: str) -> str:
    match = re.search(r"```json\s*\n(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r"```[^\n]*\n(.*?)```", text, flags=re.DOTALL)
    if match:
        fenced = _extract_balanced_json_object(match.group(1).strip())
        if fenced:
            return fenced
    section = _extract_labeled_section(text, "Dateien", ["Begruendung", "Tests", "Warum", "Titel", "Score", "Strategie"])
    if section:
        balanced = _extract_balanced_json_object(_strip_fence_markers(section))
        if balanced:
            return balanced
    return _extract_balanced_json_object(text)


def _normalize_code(text: str) -> str:
    if not text:
        return ""
    return "\n".join(line.rstrip() for line in text.strip().splitlines()).strip()


def _validate_code(code: str, language: str, input_name: str) -> tuple[bool, str]:
    if not code.strip():
        return False, "empty candidate code"
    normalized_language = (language or "").strip().lower()
    try:
        if normalized_language == "python":
            tree = ast.parse(code, filename=input_name or "<generated>", mode="exec")
            body = list(tree.body)
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
                body = body[1:]
            substantive_nodes = [node for node in body if not isinstance(node, ast.Pass)]
            if not substantive_nodes:
                return False, "python candidate contains no substantive code"
        elif normalized_language == "json":
            json.loads(code)
    except Exception as exc:
        return False, str(exc)
    return True, ""


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": str(candidate.get("candidate_id") or ""),
        "title": str(candidate.get("title") or ""),
        "strategy": str(candidate.get("strategy") or ""),
        "reasoning": str(candidate.get("reasoning") or ""),
        "tests": str(candidate.get("tests") or ""),
        "self_score": _clamp_score(_safe_float(candidate.get("self_score"), 0.0)),
        "final_score": _clamp_score(_safe_float(candidate.get("final_score"), 0.0)),
        "syntax_ok": bool(candidate.get("syntax_ok")),
        "syntax_error": str(candidate.get("syntax_error") or ""),
        "changed": bool(candidate.get("changed")),
        "has_code": bool(candidate.get("has_code")),
        "changed_files": list(candidate.get("changed_files") or []),
        "changed_file_count": int(candidate.get("changed_file_count") or 0),
    }


def _infer_language_from_name(path_like: str) -> str:
    return LANGUAGE_BY_SUFFIX.get(Path(path_like).suffix.lower(), "text")


def _normalize_relative_project_path(relative_path: Any) -> str:
    path_text = str(relative_path or "").strip().replace("\\", "/")
    if not path_text:
        raise ValueError("empty relative project path")
    candidate = Path(path_text)
    if candidate.is_absolute():
        raise ValueError(f"absolute project path is not allowed: {path_text}")
    normalized_parts: list[str] = []
    for part in candidate.parts:
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError(f"parent traversal is not allowed: {path_text}")
        normalized_parts.append(part)
    if not normalized_parts:
        raise ValueError(f"invalid relative project path: {path_text}")
    return Path(*normalized_parts).as_posix()


def _is_excluded_project_path(relative_path: str, exclude_patterns: list[str]) -> bool:
    path_text = relative_path.replace("\\", "/")
    for pattern in exclude_patterns:
        normalized = pattern.replace("\\", "/")
        if fnmatch.fnmatch(path_text, normalized) or (normalized.startswith("**/") and fnmatch.fnmatch(path_text, normalized[3:])):
            return True
    return False


def _should_include_project_path(relative_path: str, include_patterns: list[str], exclude_patterns: list[str]) -> bool:
    path_text = relative_path.replace("\\", "/")
    if _is_excluded_project_path(path_text, exclude_patterns):
        return False
    if not include_patterns:
        return Path(path_text).suffix.lower() in LANGUAGE_BY_SUFFIX
    for pattern in include_patterns:
        normalized = pattern.replace("\\", "/")
        if fnmatch.fnmatch(path_text, normalized) or (normalized.startswith("**/") and fnmatch.fnmatch(path_text, normalized[3:])):
            return True
    return False


def _collect_project_files(base_path: Path, source_dir: Path, request: dict[str, Any]) -> list[dict[str, Any]]:
    include_patterns = _normalize_patterns(request.get("include"))
    exclude_patterns = _normalize_patterns(request.get("exclude")) or list(DEFAULT_PROJECT_EXCLUDES)
    max_files = int(request.get("max_files") or DEFAULT_MAX_PROJECT_FILES)
    max_file_chars = int(request.get("max_file_chars") or DEFAULT_MAX_FILE_CHARS)
    selected: list[dict[str, Any]] = []
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source_dir).as_posix()
        if not _should_include_project_path(relative, include_patterns, exclude_patterns):
            continue
        try:
            source_code = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        excerpt, truncated = _truncate(source_code, max_file_chars)
        selected.append(
            {
                "relative_path": relative,
                "absolute_path": str(path.resolve(strict=False)),
                "language": _infer_language_from_name(relative),
                "source_code": source_code,
                "source_excerpt": excerpt,
                "source_truncated": truncated,
                "char_count": len(source_code),
                "line_count": _line_count(source_code),
            }
        )
        if len(selected) >= max_files:
            break
    return selected


def _project_manifest(files: list[dict[str, Any]]) -> str:
    lines = []
    for file_record in files:
        lines.append(
            "- {path} ({language}, {lines} Zeilen, {chars} Zeichen{truncated})".format(
                path=file_record["relative_path"],
                language=file_record["language"],
                lines=file_record["line_count"],
                chars=file_record["char_count"],
                truncated=", gekuerzt" if file_record.get("source_truncated") else "",
            )
        )
    return "\n".join(lines)


def _project_excerpt(files: list[dict[str, Any]]) -> str:
    sections: list[str] = []
    for file_record in files:
        sections.append(
            "\n".join(
                [
                    f"Datei: {file_record['relative_path']}",
                    f"```{file_record['language']}",
                    str(file_record["source_excerpt"]),
                    "```",
                ]
            )
        )
    return "\n\n".join(sections)


def load_request(base_path_like: Any, request_like: Any) -> dict[str, Any]:
    base_path = Path(str(base_path_like or ".")).resolve(strict=False)
    request = _coerce_request_object(request_like)

    goal = str(request.get("goal") or DEFAULT_GOAL).strip()
    constraints = _normalize_constraints(request.get("constraints"))
    if not constraints:
        constraints = [
            "Gib immer vollstaendige verwertbare Ausgaben aus.",
            "Vermeide Platzhalter, TODOs, Auslassungen und ellipsenartige Marker.",
            "Breche die oeffentliche Schnittstelle nur, wenn es im Ziel explizit verlangt ist.",
        ]

    source_dir_text = str(request.get("source_dir") or request.get("project_dir") or "").strip()
    if source_dir_text:
        source_dir = _resolve_path(base_path, source_dir_text)
        if not source_dir.is_dir():
            raise ValueError(f"source_dir is not a directory: {source_dir}")
        files = _collect_project_files(base_path, source_dir, request)
        if not files:
            raise ValueError(f"no source files selected in project directory: {source_dir}")
        input_name = source_dir.name or "project"
        output_path = _resolve_path(base_path, request["output_path"]) if request.get("output_path") else _default_project_output_path(base_path, input_name)
        report_path = _resolve_path(base_path, request["report_path"]) if request.get("report_path") else _default_report_path(base_path, input_name)
        total_chars = sum(int(item.get("char_count") or 0) for item in files)
        total_lines = sum(int(item.get("line_count") or 0) for item in files)
        return {
            "request_mode": "project",
            "base_path": str(base_path),
            "input_name": input_name,
            "source_dir": str(source_dir),
            "source_path": "",
            "source_code": "",
            "source_excerpt": _project_excerpt(files),
            "source_char_count": total_chars,
            "source_line_count": total_lines,
            "source_file_count": len(files),
            "source_truncated": any(bool(item.get("source_truncated")) for item in files),
            "language": "multi",
            "goal": goal,
            "constraints": constraints,
            "output_path": str(output_path),
            "report_path": str(report_path),
            "files": files,
            "project_manifest": _project_manifest(files),
        }

    source_path_text = str(request.get("source_path") or request.get("path") or request.get("file") or "").strip()
    source_path = _resolve_path(base_path, source_path_text) if source_path_text else None
    source_code = _coerce_text(request.get("source_code") or request.get("code"))
    if not source_code and source_path is not None:
        source_code = source_path.read_text(encoding="utf-8")
    if not source_code:
        raise ValueError("code improvement request requires source_path/source_code or source_dir")

    language = _infer_language(source_path, request)
    input_name = source_path.name if source_path is not None else f"inline{SUFFIX_BY_LANGUAGE.get(language, '.txt')}"
    output_path = _resolve_path(base_path, request["output_path"]) if request.get("output_path") else _default_output_path(base_path, input_name, language)
    report_path = _resolve_path(base_path, request["report_path"]) if request.get("report_path") else _default_report_path(base_path, input_name)
    max_source_chars = int(request.get("max_source_chars") or DEFAULT_MAX_SOURCE_CHARS)
    source_excerpt, source_truncated = _truncate(source_code, max_source_chars)

    return {
        "request_mode": "single_file",
        "base_path": str(base_path),
        "input_name": input_name,
        "source_path": str(source_path) if source_path is not None else "",
        "source_dir": "",
        "source_code": source_code,
        "source_excerpt": source_excerpt,
        "source_char_count": len(source_code),
        "source_line_count": _line_count(source_code),
        "source_file_count": 1,
        "source_truncated": source_truncated,
        "language": language,
        "goal": goal,
        "constraints": constraints,
        "output_path": str(output_path),
        "report_path": str(report_path),
        "files": [],
        "project_manifest": "",
    }


def build_review_prompt(request_like: Any) -> str:
    request = dict(request_like)
    constraints_text = "\n".join(f"- {item}" for item in request.get("constraints", []))
    if request.get("request_mode") == "project":
        truncation_note = (
            "Einzelne Dateien wurden fuer den Prompt gekuerzt; beachte die Ausschnitte als Arbeitsfenster."
            if request.get("source_truncated")
            else "Alle eingebetteten Dateien sind vollstaendig enthalten."
        )
        return (
            f"Ziel: {request['goal']}\n"
            f"Projekt: {request['input_name']}\n"
            f"Modus: Projektverzeichnis\n"
            f"{truncation_note}\n"
            f"Dateien:\n{request['project_manifest']}\n\n"
            f"Randbedingungen:\n{constraints_text}\n\n"
            "Pruefe dieses Projekt und verdichte die wichtigsten Risiken, Architekturthemen, Chancen und Testhebel.\n\n"
            f"{request['source_excerpt']}"
        )
    truncation_note = (
        "Der Quellcode wurde fuer den Prompt gekuerzt; beachte diesen Ausschnitt als Arbeitsfenster."
        if request.get("source_truncated")
        else "Der Quellcode ist vollstaendig enthalten."
    )
    return (
        f"Ziel: {request['goal']}\n"
        f"Datei: {request['input_name']}\n"
        f"Sprache: {request['language']}\n"
        f"{truncation_note}\n"
        f"Randbedingungen:\n{constraints_text}\n\n"
        "Pruefe diesen Quellcode und verdichte die wichtigsten Risiken, Chancen und noetigen Testhinweise.\n\n"
        f"```{request['language']}\n{request['source_excerpt']}\n```"
    )


def build_candidate_prompt(request_like: Any, review_text_like: Any, variant: str) -> str:
    request = dict(request_like)
    review_text = extract_agent_text(review_text_like)
    profile = VARIANT_PROFILES.get(variant, VARIANT_PROFILES["refactor"])
    constraints_text = "\n".join(f"- {item}" for item in request.get("constraints", []))
    if request.get("request_mode") == "project":
        return (
            f"Variante: {variant}\n"
            f"Schwerpunkt: {profile['title']}\n"
            f"Fokus: {profile['focus']}\n"
            f"Ziel: {request['goal']}\n"
            f"Projekt: {request['input_name']}\n"
            f"Dateien:\n{request['project_manifest']}\n"
            f"Randbedingungen:\n{constraints_text}\n\n"
            "Review-Zusammenfassung:\n"
            f"{_truncate(review_text, 2000)[0]}\n\n"
            "Erzeuge eine verbesserte Projektvariante. Gib nur geaenderte Dateien als JSON-Objekt aus.\n"
            "Ausgabeformat:\n"
            "Titel: <kurz>\n"
            "Score: <0.00-1.00>\n"
            "Strategie: <kurz>\n"
            "Dateien:\n"
            "```json\n"
            "{\"relative/pfad.py\": \"vollstaendiger neuer Dateiinhalt\", \"weitere/datei.ts\": \"...\"}\n"
            "```\n"
            "Wenn keine Datei geaendert werden soll, gib im JSON-Block {} aus.\n"
            "Begruendung: <kurz>\n"
            "Tests: <kurz>\n\n"
            "Projektquellen:\n"
            f"{request['source_excerpt']}"
        )
    return (
        f"Variante: {variant}\n"
        f"Schwerpunkt: {profile['title']}\n"
        f"Fokus: {profile['focus']}\n"
        f"Ziel: {request['goal']}\n"
        f"Datei: {request['input_name']}\n"
        f"Sprache: {request['language']}\n"
        f"Randbedingungen:\n{constraints_text}\n\n"
        "Review-Zusammenfassung:\n"
        f"{_truncate(review_text, 1800)[0]}\n\n"
        "Erzeuge nun eine vollstaendige verbesserte Dateivariante.\n"
        "Ausgabeformat:\n"
        "Titel: <kurz>\n"
        "Score: <0.00-1.00>\n"
        "Strategie: <kurz>\n"
        "Code:\n"
        f"```{request['language']}\n"
        "<vollstaendiger verbesserter Dateiinhalt>\n"
        "```\n"
        "Begruendung: <kurz>\n"
        "Tests: <kurz>\n\n"
        "Originalcode:\n"
        f"```{request['language']}\n{request['source_excerpt']}\n```"
    )


def extract_agent_text(result_like: Any) -> str:
    if isinstance(result_like, dict):
        memory_record = result_like.get("memory_record")
        if isinstance(memory_record, dict) and str(memory_record.get("text") or "").strip():
            return str(memory_record.get("text") or "").strip()
        data = result_like.get("data")
        if isinstance(data, dict):
            nested_memory = data.get("memory_record")
            if isinstance(nested_memory, dict) and str(nested_memory.get("text") or "").strip():
                return str(nested_memory.get("text") or "").strip()
        for key in ("output", "response", "text"):
            value = result_like.get(key)
            if str(value or "").strip():
                return str(value or "").strip()
    return _coerce_text(result_like).strip()


def _project_file_lookup(request: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["relative_path"]): dict(item) for item in request.get("files", []) if isinstance(item, dict)}


def parse_candidate_response(candidate_id: str, request_like: Any, response_text_like: Any) -> dict[str, Any]:
    request = dict(request_like)
    response_text = extract_agent_text(response_text_like)
    score_text = _extract_label(response_text, "Score")

    if request.get("request_mode") == "project":
        block = _extract_project_json_block(response_text)
        file_changes: dict[str, str] = {}
        syntax_ok = True
        syntax_errors: list[str] = []
        has_code = bool(block.strip())
        changed = False
        changed_files: list[str] = []
        file_lookup = _project_file_lookup(request)
        if block.strip():
            try:
                parsed = json.loads(block)
                if not isinstance(parsed, dict):
                    raise ValueError("project candidate block must be a JSON object")
                for relative_path, new_code_like in parsed.items():
                    relative_text = _normalize_relative_project_path(relative_path)
                    new_code = _normalize_code(_coerce_text(new_code_like))
                    file_changes[relative_text] = new_code
                    original = file_lookup.get(relative_text)
                    language = _infer_language_from_name(relative_text if original is None else str(original.get("relative_path") or relative_text))
                    ok, error = _validate_code(new_code, language, relative_text)
                    if not ok:
                        syntax_ok = False
                        syntax_errors.append(f"{relative_text}: {error}")
                    original_code = str((original or {}).get("source_code") or "")
                    if new_code != _normalize_code(original_code):
                        changed = True
                        changed_files.append(relative_text)
            except Exception as exc:
                syntax_ok = False
                syntax_errors.append(str(exc))
        self_score = _clamp_score(
            _safe_float(score_text, 0.55 if not score_text and has_code and syntax_ok and changed else 0.0)
        )
        final_score = _clamp_score(self_score * 0.65 + (0.25 if syntax_ok else 0.0) + (0.10 if changed else 0.0))
        preview = ", ".join(changed_files[:6]) if changed_files else "keine Aenderungen"
        return {
            "candidate_id": candidate_id,
            "title": _extract_label(response_text, "Titel") or VARIANT_PROFILES.get(candidate_id, {}).get("title", candidate_id),
            "self_score": round(self_score, 6),
            "final_score": round(final_score, 6),
            "strategy": _extract_label(response_text, "Strategie"),
            "reasoning": _extract_label(response_text, "Begruendung"),
            "tests": _extract_label(response_text, "Tests"),
            "file_changes": file_changes,
            "changed_files": changed_files,
            "changed_file_count": len(changed_files),
            "has_code": has_code,
            "syntax_ok": syntax_ok,
            "syntax_error": "; ".join(syntax_errors),
            "changed": changed,
            "response_text": response_text,
            "preview": preview,
        }

    language = str(request.get("language") or "")
    code = _extract_code_block(response_text)
    if not code and language.strip().lower() == "python":
        code = _recover_python_code_slice(response_text)
    has_code = bool(code.strip())
    normalized_code = _normalize_code(code if has_code else request.get("source_code", ""))
    syntax_ok, syntax_error = _validate_code(normalized_code, language, str(request.get("input_name") or "generated.txt"))
    if has_code and not syntax_ok and language.strip().lower() == "python":
        recovered = _recover_python_code_slice(code) or _recover_python_code_slice(response_text)
        if recovered:
            recovered_code = _normalize_code(recovered)
            recovered_ok, recovered_error = _validate_code(recovered_code, language, str(request.get("input_name") or "generated.txt"))
            if recovered_ok:
                normalized_code = recovered_code
                syntax_ok = True
                syntax_error = ""
            else:
                syntax_error = recovered_error
    changed = normalized_code != _normalize_code(str(request.get("source_code") or ""))
    self_score = _clamp_score(
        _safe_float(score_text, 0.55 if not score_text and has_code and syntax_ok and changed else 0.0)
    )
    if not has_code:
        final_score = 0.02 if syntax_ok else 0.0
    else:
        final_score = _clamp_score(self_score * 0.65 + (0.25 if syntax_ok else 0.0) + (0.10 if changed else 0.0))
    return {
        "candidate_id": candidate_id,
        "title": _extract_label(response_text, "Titel") or VARIANT_PROFILES.get(candidate_id, {}).get("title", candidate_id),
        "self_score": round(self_score, 6),
        "final_score": round(final_score, 6),
        "strategy": _extract_label(response_text, "Strategie"),
        "reasoning": _extract_label(response_text, "Begruendung"),
        "tests": _extract_label(response_text, "Tests"),
        "code": normalized_code,
        "has_code": has_code,
        "syntax_ok": syntax_ok,
        "syntax_error": syntax_error,
        "changed": changed,
        "changed_files": [str(request.get("input_name") or "")] if changed else [],
        "changed_file_count": 1 if changed else 0,
        "response_text": response_text,
        "preview": _truncate(normalized_code, 420)[0],
    }


def build_selector_prompt(
    request_like: Any,
    review_text_like: Any,
    refactor_candidate_like: Any,
    reliability_candidate_like: Any,
    simplify_candidate_like: Any,
) -> str:
    request = dict(request_like)
    review_text = extract_agent_text(review_text_like)
    candidates = [
        _candidate_summary(refactor_candidate_like),
        _candidate_summary(reliability_candidate_like),
        _candidate_summary(simplify_candidate_like),
    ]
    candidate_lines: list[str] = []
    for candidate in candidates:
        changed_files = ", ".join(candidate.get("changed_files") or []) or "keine"
        candidate_lines.extend(
            [
                f"- {candidate['candidate_id']}: {candidate['title']}",
                f"  final_score={candidate['final_score']:.3f}, self_score={candidate['self_score']:.3f}, syntax_ok={str(bool(candidate['syntax_ok'])).lower()}, changed={str(bool(candidate['changed'])).lower()}",
                f"  changed_files={changed_files}",
                f"  reasoning={candidate['reasoning'] or '-'}",
                f"  tests={candidate['tests'] or '-'}",
            ]
        )
    original_hint = (
        "original ist erlaubt, wenn keine Variante das Ziel verlaesslich verbessert."
        if request.get("request_mode") == "project"
        else "original ist erlaubt, wenn keine Dateivariante das Ziel verlaesslich verbessert."
    )
    context_lines = [
        f"Ziel: {request['goal']}",
        f"Input: {request['input_name']}",
        f"Modus: {request['request_mode']}",
        original_hint,
        "",
        "Review-Zusammenfassung:",
        _truncate(review_text, 1800)[0],
        "",
        "Kandidaten:",
        *candidate_lines,
        "",
        "Waehle genau einen Gewinner aus: refactor, reliability, simplify oder original.",
        "Bevorzuge Robustheit, Verhaltenstreue, Nutzwert der Aenderungen und technische Realisierbarkeit.",
        "Ausgabeformat:",
        "Gewinner: <refactor/reliability/simplify/original>",
        "Score: <0.00-1.00>",
        "Warum: <kurz>",
    ]
    return "\n".join(context_lines)


def _build_original_candidate(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("request_mode") == "project":
        syntax_ok = True
        syntax_errors: list[str] = []
        for file_record in request.get("files", []):
            language = str(file_record.get("language") or "")
            code = str(file_record.get("source_code") or "")
            file_name = str(file_record.get("relative_path") or request.get("input_name") or "project")
            ok, error = _validate_code(code, language, file_name)
            if not ok:
                syntax_ok = False
                syntax_errors.append(f"{file_name}: {error}")
        final_score = 0.45 if syntax_ok else 0.08
        return {
            "candidate_id": "original",
            "title": "Originalzustand beibehalten",
            "self_score": round(final_score, 6),
            "final_score": round(final_score, 6),
            "strategy": "Keine Aenderung",
            "reasoning": "Behalte den bestehenden Projektstand bei.",
            "tests": "Bestehende Projekt-Tests erneut ausfuehren.",
            "file_changes": {},
            "changed_files": [],
            "changed_file_count": 0,
            "has_code": True,
            "syntax_ok": syntax_ok,
            "syntax_error": "; ".join(syntax_errors),
            "changed": False,
            "response_text": "",
            "preview": request.get("project_manifest") or request.get("input_name") or "original",
        }

    code = _normalize_code(str(request.get("source_code") or ""))
    syntax_ok, syntax_error = _validate_code(code, str(request.get("language") or ""), str(request.get("input_name") or "generated.txt"))
    final_score = 0.45 if syntax_ok else 0.08
    return {
        "candidate_id": "original",
        "title": "Originalzustand beibehalten",
        "self_score": round(final_score, 6),
        "final_score": round(final_score, 6),
        "strategy": "Keine Aenderung",
        "reasoning": "Behalte den bestehenden Dateiinhalt bei.",
        "tests": "Bestehende Datei- und Integrations-Tests erneut ausfuehren.",
        "code": code,
        "has_code": True,
        "syntax_ok": syntax_ok,
        "syntax_error": syntax_error,
        "changed": False,
        "changed_files": [],
        "changed_file_count": 0,
        "response_text": "",
        "preview": _truncate(code, 420)[0],
    }


def _rank_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _sort_key(candidate: dict[str, Any]) -> tuple[int, int, float, float, str]:
        return (
            1 if bool(candidate.get("syntax_ok")) else 0,
            1 if bool(candidate.get("changed")) else 0,
            _clamp_score(_safe_float(candidate.get("final_score"), 0.0)),
            _clamp_score(_safe_float(candidate.get("self_score"), 0.0)),
            str(candidate.get("candidate_id") or ""),
        )

    return sorted((dict(item) for item in candidates), key=_sort_key, reverse=True)


def _resolve_selection(selector_text_like: Any, candidates: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    selector_text = extract_agent_text(selector_text_like)
    warnings: list[str] = []
    ranked = _rank_candidates(candidates)
    if not ranked:
        raise ValueError("no candidates available")

    winner = _extract_label(selector_text, "Gewinner").strip().lower()
    candidate_by_id = {str(item.get("candidate_id") or "").lower(): dict(item) for item in candidates}
    selected = candidate_by_id.get(winner)
    selection_mode = "selector"
    if selected is None:
        if winner:
            warnings.append(f"selector winner not recognized: {winner}")
        else:
            warnings.append("selector winner missing; fallback ranking used")
        selected = dict(ranked[0])
        selection_mode = "fallback"
    elif winner != "original" and (not selected.get("has_code") or not selected.get("syntax_ok")):
        warnings.append(f"selector chose invalid candidate '{winner}'; fallback ranking used")
        selected = dict(ranked[0])
        selection_mode = "fallback"

    selected["selection_mode"] = selection_mode
    selected["selector_reason"] = _extract_label(selector_text, "Warum")
    selected["selector_score"] = round(_clamp_score(_safe_float(_extract_label(selector_text, "Score"), selected.get("final_score"))), 6)
    selected["selector_text"] = selector_text
    return selected, warnings


def _copy_project_source_tree(source_dir: Path, output_dir: Path, exclude_patterns: list[str]) -> list[str]:
    copied_files: list[str] = []
    source_dir_resolved = source_dir.resolve(strict=False)
    output_dir_resolved = output_dir.resolve(strict=False)
    output_prefix = ""
    if output_dir_resolved.is_relative_to(source_dir_resolved):
        output_prefix = output_dir_resolved.relative_to(source_dir_resolved).as_posix()
    for source_path in sorted(source_dir.rglob("*")):
        if not source_path.is_file():
            continue
        relative = source_path.relative_to(source_dir).as_posix()
        if output_prefix and (relative == output_prefix or relative.startswith(f"{output_prefix}/")):
            continue
        if _is_excluded_project_path(relative, exclude_patterns):
            continue
        target_path = output_dir / relative
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        copied_files.append(relative)
    return copied_files


def _write_project_output(request: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    source_dir = Path(str(request.get("source_dir") or ""))
    output_dir = Path(str(request.get("output_path") or ""))
    exclude_patterns = _normalize_patterns(request.get("exclude")) or list(DEFAULT_PROJECT_EXCLUDES)
    output_dir.mkdir(parents=True, exist_ok=True)
    copied_files = _copy_project_source_tree(source_dir, output_dir, exclude_patterns)
    changed_files: list[str] = []
    for relative_path, new_code_like in dict(candidate.get("file_changes") or {}).items():
        normalized_relative = _normalize_relative_project_path(relative_path)
        target_path = output_dir / normalized_relative
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(_coerce_text(new_code_like), encoding="utf-8")
        changed_files.append(normalized_relative)
    written_files = sorted({*copied_files, *changed_files})
    return {
        "output_path": str(output_dir),
        "output_kind": "directory",
        "written_files": written_files,
        "changed_files": sorted(set(changed_files)),
        "changed_file_count": len(set(changed_files)),
    }


def _persist_report(report_path: Path, payload: dict[str, Any]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def persist_best_candidate(
    base_path_like: Any,
    request_like: Any,
    review_text_like: Any,
    refactor_candidate_like: Any,
    reliability_candidate_like: Any,
    simplify_candidate_like: Any,
    selector_text_like: Any,
) -> dict[str, Any]:
    _ = Path(str(base_path_like or ".")).resolve(strict=False)
    request = dict(request_like)
    review_text = extract_agent_text(review_text_like)
    candidates = [
        dict(refactor_candidate_like),
        dict(reliability_candidate_like),
        dict(simplify_candidate_like),
    ]
    original_candidate = _build_original_candidate(request)
    selection_candidates = [*candidates, original_candidate]
    selected_candidate, warnings = _resolve_selection(selector_text_like, selection_candidates)

    if request.get("request_mode") == "project":
        write_result = _write_project_output(request, selected_candidate)
        output_preview = ", ".join(write_result["changed_files"]) or "Originalprojekt gespiegelt"
    else:
        output_path = Path(str(request.get("output_path") or ""))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        selected_code = _normalize_code(str(selected_candidate.get("code") or request.get("source_code") or ""))
        output_path.write_text(selected_code, encoding="utf-8")
        write_result = {
            "output_path": str(output_path),
            "output_kind": "file",
            "written_files": [output_path.name],
            "changed_files": list(selected_candidate.get("changed_files") or []),
            "changed_file_count": len(list(selected_candidate.get("changed_files") or [])),
        }
        output_preview = _truncate(selected_code, 420)[0]

    artifact_paths = {
        "output_path": str(write_result["output_path"]),
        "report_path": str(request.get("report_path") or ""),
        "output_kind": str(write_result["output_kind"]),
        "written_files": list(write_result.get("written_files") or []),
        "changed_files": list(write_result.get("changed_files") or []),
        "source_path": str(request.get("source_path") or ""),
        "source_dir": str(request.get("source_dir") or ""),
    }

    selected_summary = _candidate_summary(selected_candidate)
    selected_summary["selection_mode"] = str(selected_candidate.get("selection_mode") or "")
    selected_summary["selector_reason"] = str(selected_candidate.get("selector_reason") or "")
    selected_summary["selector_score"] = round(_clamp_score(_safe_float(selected_candidate.get("selector_score"), selected_candidate.get("final_score"))), 6)

    report_payload = {
        "request": {
            "mode": request.get("request_mode"),
            "goal": request.get("goal"),
            "input_name": request.get("input_name"),
            "source_path": request.get("source_path"),
            "source_dir": request.get("source_dir"),
            "output_path": request.get("output_path"),
            "report_path": request.get("report_path"),
            "source_file_count": request.get("source_file_count"),
        },
        "review_text": review_text,
        "candidates": [_candidate_summary(item) for item in candidates],
        "selected_candidate": selected_summary,
        "artifact_paths": artifact_paths,
        "warnings": warnings,
        "selector_text": str(selected_candidate.get("selector_text") or extract_agent_text(selector_text_like)),
    }
    _persist_report(Path(str(request.get("report_path") or "")), report_payload)

    return {
        "request_mode": str(request.get("request_mode") or ""),
        "artifact_paths": artifact_paths,
        "selected_candidate": selected_summary,
        "warnings": warnings,
        "output_preview": output_preview,
        "report_path": str(request.get("report_path") or ""),
    }


def extract_artifact_paths(result_like: Any) -> dict[str, Any]:
    if isinstance(result_like, dict):
        return dict(result_like.get("artifact_paths") or {})
    return {}


def extract_selected_candidate(result_like: Any) -> dict[str, Any]:
    if isinstance(result_like, dict):
        return dict(result_like.get("selected_candidate") or {})
    return {}
