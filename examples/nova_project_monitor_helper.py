"""Nova-shell project monitor helper.

This module scans a project tree, detects file changes, records line-level
diff hunks, and writes a live-updating HTML report plus JSON analysis files.
It is designed to be embedded into a single self-bootstrapping `.ns` script.
"""

from __future__ import annotations

import datetime as dt
import difflib
import hashlib
import html
import importlib
import importlib.util
import json
import os
import pathlib
import queue
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from typing import Any

VERSION = "1.0"
MAX_HISTORY = 80
MAX_FILE_BYTES = 1024 * 1024
MAX_DIFF_HUNKS = 24
MAX_HUNK_LINES = 14
MAX_SNAPSHOT_TEXT_BYTES = 8 * 1024 * 1024
EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".mypy_cache",
    ".next",
    ".nox",
    ".nova",
    ".nova_lens",
    "node_modules",
    ".pytest_cache",
    "dist",
    ".ruff_cache",
    ".tox",
    ".turbo",
    ".venv",
    "venv",
    "build",
    "coverage",
    "__pycache__",
    ".nova_project_monitor",
    ".nova_shell_memory",
}
EXCLUDED_FILES = {
    "nova_project_monitor.ns",
}
TEXT_NAMES = {
    ".env",
    ".env.local",
    ".env.development",
    ".env.production",
    ".gitignore",
    ".gitattributes",
    "Dockerfile",
    "Makefile",
}
TEXT_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".css",
    ".csv",
    ".env",
    ".go",
    ".graphql",
    ".h",
    ".hpp",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".kt",
    ".less",
    ".lua",
    ".md",
    ".mjs",
    ".ns",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".scss",
    ".sh",
    ".sql",
    ".svg",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".vue",
    ".xml",
    ".yaml",
    ".yml",
}
AI_PROVIDER_SPECS: dict[str, dict[str, Any]] = {
    "atheria": {
        "kind": "atheria-core",
        "base_url": "local://atheria",
        "base_url_env": "ATHERIA_BASE_URL",
        "api_key_env": "",
        "model_env": "ATHERIA_MODEL",
        "default_model": "atheria-core",
        "requires_api_key": False,
    },
    "openai": {
        "kind": "openai-chat",
        "base_url": "https://api.openai.com/v1",
        "base_url_env": "OPENAI_BASE_URL",
        "api_key_env": "OPENAI_API_KEY",
        "model_env": "OPENAI_MODEL",
        "default_model": "gpt-4o-mini",
        "requires_api_key": True,
    },
    "openrouter": {
        "kind": "openai-chat",
        "base_url": "https://openrouter.ai/api/v1",
        "base_url_env": "OPENROUTER_BASE_URL",
        "api_key_env": "OPENROUTER_API_KEY",
        "model_env": "OPENROUTER_MODEL",
        "default_model": "openai/gpt-4o-mini",
        "requires_api_key": True,
    },
    "groq": {
        "kind": "openai-chat",
        "base_url": "https://api.groq.com/openai/v1",
        "base_url_env": "GROQ_BASE_URL",
        "api_key_env": "GROQ_API_KEY",
        "model_env": "GROQ_MODEL",
        "default_model": "llama-3.3-70b-versatile",
        "requires_api_key": True,
    },
    "lmstudio": {
        "kind": "openai-chat",
        "base_url": "http://127.0.0.1:1234/v1",
        "base_url_env": "LM_STUDIO_BASE_URL",
        "api_key_env": "LM_STUDIO_API_KEY",
        "model_env": "LM_STUDIO_MODEL",
        "default_model": "",
        "requires_api_key": False,
    },
    "ollama": {
        "kind": "ollama-chat",
        "base_url": "http://127.0.0.1:11434",
        "base_url_env": "OLLAMA_BASE_URL",
        "api_key_env": "",
        "model_env": "OLLAMA_MODEL",
        "default_model": "llama3.2",
        "requires_api_key": False,
    },
}
_ATHERIA_RUNTIME: Any = None
_ATHERIA_RUNTIME_ERROR = ""

WATCHDOG_AVAILABLE = bool(importlib.util.find_spec("watchdog"))


def env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def fmt_ts(ts: float | None = None) -> str:
    moment = dt.datetime.fromtimestamp(ts or time.time())
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def fmt_size(size: int | None) -> str:
    size = int(size or 0)
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024.0
    return f"{size} B"


def severity_label(score: int) -> str:
    if score >= 75:
        return "critical"
    if score >= 55:
        return "high"
    if score >= 30:
        return "medium"
    return "low"


def tail_text(value: str, *, max_chars: int = 4000) -> str:
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def load_json(path: pathlib.Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: pathlib.Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def is_text_candidate(path: pathlib.Path) -> bool:
    suffix = path.suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        return True
    if path.name in TEXT_NAMES or path.name.startswith("."):
        return True
    return False


def sha1_file(path: pathlib.Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def read_text_payload(path: pathlib.Path) -> tuple[str | None, str, int]:
    try:
        data = path.read_bytes()
    except Exception as exc:
        return None, f"unreadable:{exc.__class__.__name__}", 0
    if len(data) > MAX_FILE_BYTES:
        return None, "too_large", len(data)
    if b"\x00" in data[:8192]:
        return None, "binary", len(data)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            return None, "binary", len(data)
    return text, "text", len(data)


def snapshot_entry(root: pathlib.Path, path: pathlib.Path, *, remaining_text_budget: int) -> tuple[dict[str, Any] | None, int, bool]:
    rel_path = path.relative_to(root).as_posix()
    try:
        stat = path.stat()
        sha_value = sha1_file(path)
    except OSError:
        return None, 0, False
    text = None
    text_state = "skipped"
    text_bytes = 0
    if is_text_candidate(path):
        text, text_state, text_bytes = read_text_payload(path)
    parsed_lines = text.splitlines() if text is not None else []
    stored_lines: list[str] = []
    omitted_for_budget = False
    captured_bytes = 0
    if text_state == "text":
        if text_bytes <= max(0, remaining_text_budget):
            stored_lines = parsed_lines
            captured_bytes = text_bytes
        else:
            text_state = "text_budget_skipped"
            omitted_for_budget = True
    return {
        "relative_path": rel_path,
        "name": path.name,
        "extension": path.suffix.lower() or "[no extension]",
        "size": stat.st_size,
        "modified_at": stat.st_mtime,
        "sha1": sha_value,
        "line_count": len(parsed_lines),
        "text_state": text_state,
        "lines": stored_lines,
    }, captured_bytes, omitted_for_budget


def scan_project(root: pathlib.Path) -> dict[str, Any]:
    files: dict[str, dict[str, Any]] = {}
    extension_counts: Counter[str] = Counter()
    directory_counts: Counter[str] = Counter()
    text_budget = int(float(os.environ.get("NOVA_PROJECT_MONITOR_MAX_TEXT_BYTES") or MAX_SNAPSHOT_TEXT_BYTES))
    captured_text_bytes = 0
    omitted_text_files = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in EXCLUDED_DIRS for part in rel_parts[:-1]):
            continue
        if path.name in EXCLUDED_FILES:
            continue
        remaining_budget = max(0, text_budget - captured_text_bytes)
        entry, consumed_bytes, omitted_for_budget = snapshot_entry(root, path, remaining_text_budget=remaining_budget)
        if not entry:
            continue
        files[entry["relative_path"]] = entry
        captured_text_bytes += consumed_bytes
        if omitted_for_budget:
            omitted_text_files += 1
        extension_counts[entry["extension"]] += 1
        parent_key = pathlib.Path(entry["relative_path"]).parent.as_posix()
        directory_counts[parent_key if parent_key != "." else "/"] += 1
    return {
        "generated_at": time.time(),
        "root": str(root),
        "file_count": len(files),
        "files": files,
        "extension_counts": dict(sorted(extension_counts.items())),
        "directory_counts": dict(directory_counts),
        "text_capture_budget_bytes": text_budget,
        "text_capture_bytes": captured_text_bytes,
        "text_capture_omitted_files": omitted_text_files,
    }


def summarize_hunks(before_lines: list[str], after_lines: list[str]) -> tuple[list[dict[str, Any]], int, int]:
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines)
    hunks: list[dict[str, Any]] = []
    added_total = 0
    removed_total = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        removed = before_lines[i1:i2]
        added = after_lines[j1:j2]
        added_total += len(added)
        removed_total += len(removed)
        if len(hunks) >= MAX_DIFF_HUNKS:
            continue
        hunks.append(
            {
                "tag": tag,
                "before_start": i1 + 1,
                "before_end": i2,
                "after_start": j1 + 1,
                "after_end": j2,
                "removed": removed[:MAX_HUNK_LINES],
                "added": added[:MAX_HUNK_LINES],
                "removed_truncated": max(0, len(removed) - MAX_HUNK_LINES),
                "added_truncated": max(0, len(added) - MAX_HUNK_LINES),
            }
        )
    return hunks, added_total, removed_total


def diff_snapshots(previous: dict[str, Any] | None, current: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    if not previous or not previous.get("files"):
        baseline = {
            "id": f"baseline-{int(current['generated_at'])}",
            "timestamp": current["generated_at"],
            "kind": "baseline",
            "summary": f"Erster Snapshot erstellt. {current['file_count']} Dateien werden ueberwacht.",
            "created": [
                {
                    "path": path,
                    "size": entry.get("size", 0),
                    "line_count": entry.get("line_count", 0),
                    "extension": entry.get("extension", "[no extension]"),
                }
                for path, entry in sorted(current["files"].items())
            ],
            "modified": [],
            "deleted": [],
            "stats": {
                "created": current["file_count"],
                "modified": 0,
                "deleted": 0,
                "added_lines": 0,
                "removed_lines": 0,
            },
        }
        baseline["review_agent"] = build_review_agent(baseline)
        return baseline, True

    prev_files = previous.get("files", {})
    curr_files = current.get("files", {})
    created_paths = sorted(set(curr_files) - set(prev_files))
    deleted_paths = sorted(set(prev_files) - set(curr_files))
    common_paths = sorted(set(curr_files) & set(prev_files))
    created: list[dict[str, Any]] = []
    deleted: list[dict[str, Any]] = []
    modified: list[dict[str, Any]] = []
    added_lines_total = 0
    removed_lines_total = 0

    for path in created_paths:
        entry = curr_files[path]
        created.append(
            {
                "path": path,
                "size": entry.get("size", 0),
                "line_count": entry.get("line_count", 0),
                "extension": entry.get("extension", "[no extension]"),
            }
        )
        added_lines_total += entry.get("line_count", 0)

    for path in deleted_paths:
        entry = prev_files[path]
        deleted.append(
            {
                "path": path,
                "size": entry.get("size", 0),
                "line_count": entry.get("line_count", 0),
                "extension": entry.get("extension", "[no extension]"),
            }
        )
        removed_lines_total += entry.get("line_count", 0)

    for path in common_paths:
        prev_entry = prev_files[path]
        curr_entry = curr_files[path]
        if prev_entry.get("sha1") == curr_entry.get("sha1"):
            continue
        hunks: list[dict[str, Any]] = []
        added_lines = 0
        removed_lines = 0
        if prev_entry.get("text_state") == "text" and curr_entry.get("text_state") == "text":
            hunks, added_lines, removed_lines = summarize_hunks(prev_entry.get("lines", []), curr_entry.get("lines", []))
        modified.append(
            {
                "path": path,
                "extension": curr_entry.get("extension", "[no extension]"),
                "before_size": prev_entry.get("size", 0),
                "after_size": curr_entry.get("size", 0),
                "before_line_count": prev_entry.get("line_count", 0),
                "after_line_count": curr_entry.get("line_count", 0),
                "before_state": prev_entry.get("text_state"),
                "after_state": curr_entry.get("text_state"),
                "added_lines": added_lines,
                "removed_lines": removed_lines,
                "hunks": hunks,
            }
        )
        added_lines_total += added_lines
        removed_lines_total += removed_lines

    if not created and not deleted and not modified:
        stable_event = {
            "id": f"scan-{int(current['generated_at'])}",
            "timestamp": current["generated_at"],
            "kind": "no_change",
            "summary": f"Keine Aenderung erkannt. {current['file_count']} Dateien im Blick.",
            "created": [],
            "modified": [],
            "deleted": [],
            "stats": {"created": 0, "modified": 0, "deleted": 0, "added_lines": 0, "removed_lines": 0},
        }
        stable_event["review_agent"] = build_review_agent(stable_event)
        return stable_event, False

    summary_parts: list[str] = []
    if created:
        summary_parts.append(f"{len(created)} neu")
    if modified:
        summary_parts.append(f"{len(modified)} geaendert")
    if deleted:
        summary_parts.append(f"{len(deleted)} entfernt")
    event = {
        "id": f"change-{int(current['generated_at'])}",
        "timestamp": current["generated_at"],
        "kind": "change",
        "summary": "Aenderung erkannt: " + ", ".join(summary_parts) + f" | +{added_lines_total} / -{removed_lines_total} Zeilen",
        "created": created,
        "modified": modified,
        "deleted": deleted,
        "stats": {
            "created": len(created),
            "modified": len(modified),
            "deleted": len(deleted),
            "added_lines": added_lines_total,
            "removed_lines": removed_lines_total,
        },
    }
    event["review_agent"] = build_review_agent(event)
    return event, True


def build_analysis(history_events: list[dict[str, Any]], snapshot: dict[str, Any]) -> dict[str, Any]:
    hotspot_counter: Counter[str] = Counter()
    hotspot_churn: Counter[str] = Counter()
    directory_touch_counter: Counter[str] = Counter()
    directory_churn_counter: Counter[str] = Counter()
    recent_change_events = [event for event in history_events if event.get("kind") == "change"][-20:]
    for event in recent_change_events:
        for item in event.get("modified", []):
            hotspot_counter[item.get("path", "")] += 1
            hotspot_churn[item.get("path", "")] += int(item.get("added_lines", 0)) + int(item.get("removed_lines", 0))
            directory = str(pathlib.Path(item.get("path", "")).parent.as_posix() or "/")
            directory_touch_counter[directory if directory != "." else "/"] += 1
            directory_churn_counter[directory if directory != "." else "/"] += int(item.get("added_lines", 0)) + int(item.get("removed_lines", 0))
        for item in event.get("created", []):
            hotspot_counter[item.get("path", "")] += 1
            hotspot_churn[item.get("path", "")] += int(item.get("line_count", 0))
            directory = str(pathlib.Path(item.get("path", "")).parent.as_posix() or "/")
            directory_touch_counter[directory if directory != "." else "/"] += 1
            directory_churn_counter[directory if directory != "." else "/"] += int(item.get("line_count", 0))
        for item in event.get("deleted", []):
            hotspot_counter[item.get("path", "")] += 1
            hotspot_churn[item.get("path", "")] += int(item.get("line_count", 0))
            directory = str(pathlib.Path(item.get("path", "")).parent.as_posix() or "/")
            directory_touch_counter[directory if directory != "." else "/"] += 1
            directory_churn_counter[directory if directory != "." else "/"] += int(item.get("line_count", 0))
    warnings: list[str] = []
    if recent_change_events:
        last_event = recent_change_events[-1]
        changed_files = last_event.get("stats", {}).get("modified", 0) + last_event.get("stats", {}).get("created", 0)
        changed_lines = last_event.get("stats", {}).get("added_lines", 0) + last_event.get("stats", {}).get("removed_lines", 0)
        if changed_files >= 6:
            warnings.append(
                "Viele Dateien wurden in einer einzelnen Aenderung veraendert. Pruefe, ob ein groesserer Umbau oder eine Seiteneffekt-Kaskade vorliegt."
            )
        if changed_lines >= 120:
            warnings.append("Der letzte Aenderungsblock ist gross. Eine Review der betroffenen Bereiche ist sinnvoll.")
    top_hotspots = [{"path": path, "touches": count} for path, count in hotspot_counter.most_common(10)]
    directory_ranking = sorted(snapshot.get("directory_counts", {}).items(), key=lambda item: (-item[1], item[0]))[:12]
    extension_ranking = sorted(snapshot.get("extension_counts", {}).items(), key=lambda item: (-item[1], item[0]))[:12]
    hottest_file_score = max([hotspot_counter[path] * 20 + hotspot_churn[path] for path in hotspot_counter] or [1])
    hottest_dir_score = max([directory_touch_counter[directory] * 20 + directory_churn_counter[directory] for directory in directory_touch_counter] or [1])
    file_hotspots = [
        {
            "path": path,
            "touches": count,
            "line_churn": hotspot_churn[path],
            "intensity": max(8, int(((count * 20) + hotspot_churn[path]) / hottest_file_score * 100)),
        }
        for path, count in hotspot_counter.most_common(10)
    ]
    directory_hotspots = [
        {
            "directory": directory,
            "touches": count,
            "line_churn": directory_churn_counter[directory],
            "intensity": max(8, int(((count * 20) + directory_churn_counter[directory]) / hottest_dir_score * 100)),
        }
        for directory, count in directory_touch_counter.most_common(10)
    ]
    insight_lines: list[str] = []
    if file_hotspots:
        insight_lines.append(f"Aktivste Datei: {file_hotspots[0]['path']} ({file_hotspots[0]['touches']} Aenderungen)")
    if directory_hotspots:
        insight_lines.append(
            f"Aktivster Ordner: {directory_hotspots[0]['directory']} ({directory_hotspots[0]['touches']} Aenderungsereignisse)"
        )
    if extension_ranking:
        ext, count = extension_ranking[0]
        insight_lines.append(f"Dominanter Dateityp im Projekt: {ext} ({count} Dateien)")
    if directory_ranking:
        folder, count = directory_ranking[0]
        insight_lines.append(f"Groesster Ordner im Scan: {folder} ({count} Dateien)")
    omitted_text_files = int(snapshot.get("text_capture_omitted_files", 0) or 0)
    if omitted_text_files > 0:
        warnings.append(
            f"Fuer {omitted_text_files} Textdateien wurden aus Speichergruenden keine Vollzeilen im Snapshot gespeichert. Diff-Hunks koennen dort eingeschraenkt sein."
        )
    return {
        "generated_at": snapshot.get("generated_at"),
        "warnings": warnings,
        "insights": insight_lines,
        "hotspots": top_hotspots,
        "file_hotspots": file_hotspots,
        "directory_hotspots": directory_hotspots,
        "directory_ranking": [{"directory": directory, "file_count": count} for directory, count in directory_ranking],
        "extension_ranking": [{"extension": ext, "file_count": count} for ext, count in extension_ranking],
        "recent_change_count": len(recent_change_events),
    }


def resolve_watch_mode() -> dict[str, Any]:
    requested = str(os.environ.get("NOVA_PROJECT_MONITOR_WATCH_MODE") or "auto").strip().lower()
    if requested in {"off", "none"}:
        return {"mode": "poll", "requested": requested, "available": WATCHDOG_AVAILABLE, "reason": "watching disabled"}
    if requested == "watchdog":
        return {
            "mode": "watchdog" if WATCHDOG_AVAILABLE else "poll",
            "requested": requested,
            "available": WATCHDOG_AVAILABLE,
            "reason": "" if WATCHDOG_AVAILABLE else "watchdog not installed",
        }
    if requested == "poll":
        return {"mode": "poll", "requested": requested, "available": WATCHDOG_AVAILABLE, "reason": ""}
    if WATCHDOG_AVAILABLE:
        return {"mode": "watchdog", "requested": requested or "auto", "available": True, "reason": ""}
    return {"mode": "poll", "requested": requested or "auto", "available": False, "reason": "watchdog not installed"}


def should_run_automation(event: dict[str, Any]) -> bool:
    mode = str(os.environ.get("NOVA_PROJECT_MONITOR_AUTOMATION") or "auto").strip().lower()
    if mode in {"0", "off", "false", "none"}:
        return False
    if event.get("kind") != "change":
        return mode in {"force", "always"}
    if mode in {"1", "on", "true", "force", "always"}:
        return True
    touched = [
        *(item.get("path", "") for item in event.get("modified", [])),
        *(item.get("path", "") for item in event.get("created", [])),
        *(item.get("path", "") for item in event.get("deleted", [])),
    ]
    relevant_suffixes = {".js", ".jsx", ".ts", ".tsx", ".json", ".css", ".scss", ".py", ".toml", ".yaml", ".yml", ".html"}
    for path_text in touched:
        suffix = pathlib.Path(path_text).suffix.lower()
        if suffix in relevant_suffixes or pathlib.Path(path_text).name in {"package.json", "pyproject.toml", "vite.config.ts", "tsconfig.json"}:
            return True
    return False


def detect_project_automation(root: pathlib.Path) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    package_json = root / "package.json"
    if package_json.exists():
        try:
            payload = json.loads(package_json.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        scripts = payload.get("scripts") if isinstance(payload, dict) else {}
        if isinstance(scripts, dict):
            package_manager = "npm"
            if (root / "pnpm-lock.yaml").exists():
                package_manager = "pnpm"
            elif (root / "yarn.lock").exists():
                package_manager = "yarn"
            if "build" in scripts:
                commands.append(
                    {
                        "name": "Frontend Build",
                        "category": "build",
                        "command": [package_manager, "run", "build"],
                        "display": f"{package_manager} run build",
                    }
                )
            if "test" in scripts:
                commands.append(
                    {
                        "name": "Frontend Tests",
                        "category": "test",
                        "command": [package_manager, "run", "test"],
                        "display": f"{package_manager} run test",
                    }
                )
    if (root / "tests").is_dir() and any(root.glob("tests/test_*.py")):
        commands.append(
            {
                "name": "Python Unit Tests",
                "category": "test",
                "command": [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
                "display": f"{sys.executable} -m unittest discover -s tests -p test_*.py",
            }
        )
    return commands


def run_automation_checks(root: pathlib.Path, event: dict[str, Any]) -> dict[str, Any]:
    if not should_run_automation(event):
        return {"enabled": False, "reason": "automation skipped for this event", "runs": []}
    commands = detect_project_automation(root)
    if not commands:
        return {"enabled": False, "reason": "no build or test commands detected", "runs": []}
    timeout_seconds = int(float(os.environ.get("NOVA_PROJECT_MONITOR_AUTOMATION_TIMEOUT") or 600))
    runs: list[dict[str, Any]] = []
    started = time.time()
    for command in commands:
        item_started = time.time()
        try:
            completed = subprocess.run(
                command["command"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
            runs.append(
                {
                    "name": command["name"],
                    "category": command["category"],
                    "command": command["display"],
                    "success": completed.returncode == 0,
                    "exit_code": int(completed.returncode),
                    "duration_seconds": round(time.time() - item_started, 3),
                    "stdout_tail": tail_text(completed.stdout),
                    "stderr_tail": tail_text(completed.stderr),
                }
            )
        except FileNotFoundError as exc:
            runs.append(
                {
                    "name": command["name"],
                    "category": command["category"],
                    "command": command["display"],
                    "success": False,
                    "exit_code": -1,
                    "duration_seconds": round(time.time() - item_started, 3),
                    "stdout_tail": "",
                    "stderr_tail": str(exc),
                }
            )
        except subprocess.TimeoutExpired as exc:
            runs.append(
                {
                    "name": command["name"],
                    "category": command["category"],
                    "command": command["display"],
                    "success": False,
                    "exit_code": -2,
                    "duration_seconds": round(time.time() - item_started, 3),
                    "stdout_tail": tail_text(exc.stdout or ""),
                    "stderr_tail": f"timeout after {timeout_seconds}s\n{tail_text(exc.stderr or '')}".strip(),
                }
            )
    succeeded = sum(1 for item in runs if item["success"])
    failed = len(runs) - succeeded
    status = "passed" if failed == 0 else ("failed" if succeeded == 0 else "partial")
    return {
        "enabled": True,
        "status": status,
        "succeeded": succeeded,
        "failed": failed,
        "duration_seconds": round(time.time() - started, 3),
        "runs": runs,
    }


def get_atheria_runtime() -> Any:
    global _ATHERIA_RUNTIME
    global _ATHERIA_RUNTIME_ERROR
    if _ATHERIA_RUNTIME is not None:
        return _ATHERIA_RUNTIME
    try:
        module = importlib.import_module("nova_shell")
        runtime = module.NovaAtheriaRuntime({}, pathlib.Path.cwd())
        if not runtime.is_available():
            _ATHERIA_RUNTIME_ERROR = "Atheria source folder not found"
            return None
        _ATHERIA_RUNTIME = runtime
        return _ATHERIA_RUNTIME
    except Exception as exc:
        _ATHERIA_RUNTIME_ERROR = str(exc).strip() or exc.__class__.__name__
        return None


def atheria_runtime_available() -> bool:
    return get_atheria_runtime() is not None


def resolve_ai_provider_config() -> dict[str, Any]:
    requested_mode = str(
        os.environ.get("NOVA_PROJECT_MONITOR_AI_MODE")
        or os.environ.get("NOVA_PROJECT_MONITOR_AI_PROVIDER")
        or os.environ.get("NOVA_AI_PROVIDER")
        or "auto"
    ).strip().lower()
    provider = ""
    if requested_mode and requested_mode != "auto":
        provider = requested_mode
    if not provider:
        if atheria_runtime_available():
            provider = "atheria"
        for candidate in ("openai", "openrouter", "groq"):
            if provider:
                break
            key_name = AI_PROVIDER_SPECS[candidate]["api_key_env"]
            if key_name and os.environ.get(key_name):
                provider = candidate
        if not provider and (os.environ.get("LM_STUDIO_MODEL") or os.environ.get("LM_STUDIO_BASE_URL")):
            provider = "lmstudio"
        if not provider and (os.environ.get("OLLAMA_MODEL") or os.environ.get("OLLAMA_BASE_URL")):
            provider = "ollama"
    spec = AI_PROVIDER_SPECS.get(provider)
    if not spec:
        return {"enabled": False, "provider": "", "reason": "no supported ai provider configured", "mode": requested_mode or "auto"}
    if provider == "atheria":
        if not atheria_runtime_available():
            return {
                "enabled": False,
                "provider": provider,
                "reason": _ATHERIA_RUNTIME_ERROR or "atheria unavailable",
                "mode": requested_mode or "auto",
            }
        return {
            "enabled": True,
            "provider": provider,
            "kind": spec["kind"],
            "base_url": "local://atheria",
            "api_key": "",
            "model": str(os.environ.get("ATHERIA_MODEL") or spec.get("default_model", "atheria-core")).strip() or "atheria-core",
            "timeout": int(float(os.environ.get("NOVA_PROJECT_MONITOR_AI_TIMEOUT") or 45)),
            "mode": requested_mode or "auto",
        }
    api_key = str(os.environ.get(spec["api_key_env"], "")).strip() if spec.get("api_key_env") else ""
    if spec.get("requires_api_key") and not api_key:
        return {
            "enabled": False,
            "provider": provider,
            "reason": f"missing {spec['api_key_env']}",
            "mode": requested_mode or "auto",
        }
    model = str(
        os.environ.get("NOVA_PROJECT_MONITOR_AI_MODEL")
        or os.environ.get("NOVA_AI_MODEL")
        or os.environ.get(spec["model_env"], "")
        or spec.get("default_model", "")
    ).strip()
    if not model:
        return {"enabled": False, "provider": provider, "reason": "no model configured", "mode": requested_mode or "auto"}
    timeout = int(float(os.environ.get("NOVA_PROJECT_MONITOR_AI_TIMEOUT") or os.environ.get("NOVA_AI_TIMEOUT") or (120 if provider in {"lmstudio", "ollama"} else 45)))
    return {
        "enabled": True,
        "provider": provider,
        "kind": spec["kind"],
        "base_url": str(os.environ.get(spec["base_url_env"]) or spec["base_url"]).rstrip("/"),
        "api_key": api_key,
        "model": model,
        "timeout": timeout,
        "mode": requested_mode or "auto",
    }


def http_json(url: str, payload: dict[str, Any], *, headers: dict[str, str] | None = None, timeout: int = 45) -> Any:
    body = json.dumps(payload).encode("utf-8")
    merged_headers = {"User-Agent": f"nova-project-monitor/{VERSION}", "Content-Type": "application/json"}
    if headers:
        merged_headers.update(headers)
    request = urllib.request.Request(url, data=body, headers=merged_headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        text = response.read().decode(charset)
    return json.loads(text) if text else {}


def extract_json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    snippet = text[start : end + 1]
    try:
        value = json.loads(snippet)
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def validate_review_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    severity = str(payload.get("severity") or "").strip().lower()
    if severity not in {"low", "medium", "high", "critical"}:
        return None
    headline = str(payload.get("headline") or "").strip()
    summary = str(payload.get("summary") or "").strip()
    findings = payload.get("findings")
    recommendations = payload.get("recommendations")
    if not headline or not summary:
        return None
    if findings is not None and not isinstance(findings, list):
        return None
    if recommendations is not None and not isinstance(recommendations, list):
        return None
    return {
        "severity": severity,
        "headline": headline,
        "summary": summary,
        "findings": [str(item) for item in (findings or [])],
        "recommendations": [str(item) for item in (recommendations or [])],
    }


def build_ai_review_prompt(event: dict[str, Any], analysis: dict[str, Any], heuristic: dict[str, Any]) -> tuple[str, str]:
    modified = []
    for item in event.get("modified", [])[:6]:
        modified.append(
            {
                "path": item.get("path"),
                "added_lines": item.get("added_lines", 0),
                "removed_lines": item.get("removed_lines", 0),
                "hunks": item.get("hunks", [])[:3],
            }
        )
    prompt_payload = {
        "event_summary": event.get("summary"),
        "stats": event.get("stats", {}),
        "created": [item.get("path") for item in event.get("created", [])[:6]],
        "deleted": [item.get("path") for item in event.get("deleted", [])[:6]],
        "modified": modified,
        "analysis": {
            "warnings": analysis.get("warnings", [])[:5],
            "insights": analysis.get("insights", [])[:5],
            "file_hotspots": analysis.get("file_hotspots", [])[:5],
            "directory_hotspots": analysis.get("directory_hotspots", [])[:5],
        },
        "heuristic_review": {
            "severity": heuristic.get("severity"),
            "score": heuristic.get("score"),
            "summary": heuristic.get("summary"),
            "findings": heuristic.get("findings", []),
            "recommendations": heuristic.get("recommendations", []),
        },
    }
    system_prompt = (
        "Du bist ein strenger Senior-Reviewer fuer Softwareaenderungen. "
        "Bewerte nur die gelieferten Aenderungsdaten. "
        "Antworte ausschliesslich mit JSON im Format "
        '{"severity":"low|medium|high|critical","headline":"...","summary":"...",'
        '"findings":["..."],"recommendations":["..."]}.'
    )
    user_prompt = json.dumps(prompt_payload, ensure_ascii=False)
    return system_prompt, user_prompt


def ai_review(event: dict[str, Any], analysis: dict[str, Any], heuristic: dict[str, Any]) -> dict[str, Any] | None:
    config = resolve_ai_provider_config()
    if not config.get("enabled") or event.get("kind") != "change":
        return None
    system_prompt, user_prompt = build_ai_review_prompt(event, analysis, heuristic)
    try:
        if config["kind"] == "atheria-core":
            runtime = get_atheria_runtime()
            if runtime is None:
                return None
            data = runtime.complete_prompt(user_prompt, model=str(config["model"]), system_prompt=system_prompt)
            text = str(data.get("text") or "")
        elif config["kind"] == "openai-chat":
            headers = {}
            if config.get("api_key"):
                headers["Authorization"] = f"Bearer {config['api_key']}"
            payload = {
                "model": config["model"],
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
            data = http_json(f"{config['base_url']}/chat/completions", payload, headers=headers, timeout=int(config["timeout"]))
            text = str((((data.get("choices") or [{}])[0]).get("message") or {}).get("content") or "")
        elif config["kind"] == "ollama-chat":
            payload = {
                "model": config["model"],
                "stream": False,
                "prompt": f"{system_prompt}\n\n{user_prompt}",
            }
            data = http_json(f"{config['base_url']}/api/generate", payload, timeout=int(config["timeout"]))
            text = str(data.get("response") or "")
        else:
            return None
        parsed = extract_json_object(text)
        validated = validate_review_payload(parsed) if parsed else None
        if not validated:
            return None
        return {
            "agent": "review-agent",
            "severity": str(validated.get("severity") or heuristic.get("severity") or "medium").lower(),
            "score": int(heuristic.get("score", 0)),
            "headline": str(validated.get("headline") or heuristic.get("headline") or "AI Review"),
            "summary": str(validated.get("summary") or heuristic.get("summary") or ""),
            "findings": [str(item) for item in (validated.get("findings") or heuristic.get("findings") or [])][:6],
            "recommendations": [str(item) for item in (validated.get("recommendations") or heuristic.get("recommendations") or [])][:4],
            "changed_paths": heuristic.get("changed_paths", []),
            "touched_directories": heuristic.get("touched_directories", []),
            "touched_extensions": heuristic.get("touched_extensions", []),
            "source": "ai",
            "provider": config["provider"],
            "model": config["model"],
            "mode": config.get("mode", "auto"),
        }
    except Exception as exc:
        fallback = dict(heuristic)
        fallback["source"] = "heuristic"
        fallback["provider_error"] = str(exc)
        return fallback


def build_review_agent(event: dict[str, Any], analysis: dict[str, Any] | None = None) -> dict[str, Any]:
    kind = event.get("kind", "scan")
    if kind == "baseline":
        return {
            "agent": "review-agent",
            "severity": "low",
            "score": 10,
            "headline": "Baseline steht.",
            "summary": "Der erste Snapshot wurde erstellt. Ab jetzt werden Veraenderungen als Review-Ereignisse bewertet.",
            "findings": ["Die aktuelle Dateibasis wurde als Ausgangspunkt gespeichert."],
            "recommendations": ["Fuehre die Datei erneut aus, sobald Codeaenderungen im Projekt auftreten."],
            "source": "heuristic",
            "mode": str(resolve_ai_provider_config().get("mode") or "auto"),
        }
    if kind == "no_change":
        return {
            "agent": "review-agent",
            "severity": "low",
            "score": 5,
            "headline": "Keine neue Review noetig.",
            "summary": "Seit dem letzten Snapshot wurde keine relevante Aenderung erkannt.",
            "findings": ["Der Projektzustand ist stabil geblieben."],
            "recommendations": ["Keine Aktion erforderlich."],
            "source": "heuristic",
            "mode": str(resolve_ai_provider_config().get("mode") or "auto"),
        }

    score = 10
    findings: list[str] = []
    recommendations: list[str] = []
    stats = event.get("stats", {})
    changed_paths = [item.get("path", "") for item in event.get("modified", [])]
    created_paths = [item.get("path", "") for item in event.get("created", [])]
    deleted_paths = [item.get("path", "") for item in event.get("deleted", [])]
    all_paths = [path for path in changed_paths + created_paths + deleted_paths if path]
    touched_dirs = {str(pathlib.Path(path).parent.as_posix() or "/") for path in all_paths}
    touched_exts = {pathlib.Path(path).suffix.lower() or "[no extension]" for path in all_paths}

    modified_count = int(stats.get("modified", 0))
    created_count = int(stats.get("created", 0))
    deleted_count = int(stats.get("deleted", 0))
    line_churn = int(stats.get("added_lines", 0)) + int(stats.get("removed_lines", 0))

    if modified_count + created_count >= 4:
        score += 18
        findings.append("Mehrere Dateien wurden gleichzeitig veraendert. Das erhoeht die Integrationsflaeche.")
    if line_churn >= 80:
        score += 20
        findings.append("Der Aenderungsumfang ist groesser. Eine gezielte Review der Logik und Seiteneffekte ist sinnvoll.")
    if deleted_count:
        score += 12
        findings.append("Es wurden Dateien entfernt. Pruefe Referenzen, Imports und Build-Pfade.")
    if len(touched_dirs) >= 2:
        score += 10
        findings.append("Die Aenderung betrifft mehrere Ordnerbereiche. Das spricht fuer uebergreifende Auswirkungen.")
    if any(path in {"package.json", "tsconfig.json", "vite.config.ts"} for path in all_paths):
        score += 15
        findings.append("Build- oder Tooling-Konfiguration wurde veraendert.")
        recommendations.append("Fuehre nach der Aenderung einen Build und gegebenenfalls die Testsuite aus.")
    if any(path.startswith("services/") for path in all_paths):
        score += 12
        findings.append("Service-Code wurde veraendert. Schnittstellen und Fehlerpfade sollten explizit geprueft werden.")
        recommendations.append("Verifiziere API-Antworten und Fehlerfaelle fuer den geaenderten Service-Code.")
    if any(path.startswith("components/") for path in all_paths):
        score += 8
        findings.append("UI-Komponenten sind betroffen. Renderpfade und Statuswechsel sollten visuell geprueft werden.")
        recommendations.append("Pruefe den betroffenen UI-Fluss im Browser auf Regressionssymptome.")
    if ".json" in touched_exts:
        score += 5
        findings.append("JSON-Dateien wurden angepasst. Datenstrukturen und Serialisierung koennen betroffen sein.")
    if any(item.get("added_lines", 0) + item.get("removed_lines", 0) >= 40 for item in event.get("modified", [])):
        score += 10
        findings.append("Mindestens eine Datei hat einen grossen Zeilen-Diff.")
    if not findings:
        findings.append("Die Aenderung ist lokal und ueberschaubar.")
    if not recommendations:
        recommendations.append("Fuehre eine kurze Review der geaenderten Dateien durch und pruefe angrenzende Aufrufpfade.")
    if modified_count and line_churn <= 20:
        recommendations.append("Ein fokussierter Smoke-Test fuer die betroffenen Dateien sollte ausreichen.")

    score = min(score, 95)
    severity = severity_label(score)
    primary_path = changed_paths[0] if changed_paths else (created_paths[0] if created_paths else (deleted_paths[0] if deleted_paths else "Projekt"))
    summary = (
        f"Review-Agent bewertet dieses Ereignis als {severity}. "
        f"Betroffen sind {modified_count} geaenderte, {created_count} neue und {deleted_count} entfernte Dateien "
        f"bei insgesamt {line_churn} Zeilen Churn."
    )
    heuristic = {
        "agent": "review-agent",
        "severity": severity,
        "score": score,
        "headline": f"Review fuer {primary_path}",
        "summary": summary,
        "findings": findings[:6],
        "recommendations": recommendations[:4],
        "changed_paths": all_paths[:10],
        "touched_directories": sorted(touched_dirs),
        "touched_extensions": sorted(touched_exts),
        "source": "heuristic",
        "mode": str(resolve_ai_provider_config().get("mode") or "auto"),
    }
    if analysis is not None:
        return ai_review(event, analysis, heuristic) or heuristic
    return heuristic


def render_review_agent(review: dict[str, Any]) -> str:
    severity = review.get("severity", "low")
    provider = str(review.get("provider") or "")
    model = str(review.get("model") or "")
    source = str(review.get("source") or "heuristic")
    mode = str(review.get("mode") or "auto")
    provider_label = "Atheria" if provider == "atheria" else provider or ("heuristic" if source == "heuristic" else "unknown")
    meta_bits = [f"Quelle: {source}"]
    if provider:
        meta_bits.append(f"Provider: {provider_label}")
    if model:
        meta_bits.append(f"Modell: {model}")
    meta_bits.append(f"Modus: {mode}")
    findings_html = "".join(f"<li>{html.escape(item)}</li>" for item in review.get("findings", [])) or "<li>Keine Befunde.</li>"
    recommendations_html = "".join(f"<li>{html.escape(item)}</li>" for item in review.get("recommendations", [])) or "<li>Keine Empfehlungen.</li>"
    changed_paths_html = "".join(f"<li>{html.escape(item)}</li>" for item in review.get("changed_paths", [])) or "<li>Keine Pfade.</li>"
    return (
        f"<div class='review-card severity-{html.escape(severity)}'>"
        "<div class='review-head'>"
        f"<span class='review-badge'>{html.escape(severity.upper())}</span>"
        f"<div><h2>Review-Agent</h2><h3>{html.escape(review.get('headline', 'Review'))}</h3></div>"
        f"<div class='review-score'>{int(review.get('score', 0))}</div>"
        "</div>"
        f"<p class='lead'>{html.escape(review.get('summary', ''))}</p>"
        f"<p class='review-meta'>{html.escape(' | '.join(meta_bits))}</p>"
        "<div class='review-grid'>"
        f"<div><h4>Befunde</h4><ul>{findings_html}</ul></div>"
        f"<div><h4>Empfehlungen</h4><ul>{recommendations_html}</ul></div>"
        f"<div><h4>Betroffene Pfade</h4><ul>{changed_paths_html}</ul></div>"
        "</div></div>"
    )


def render_automation_panel(automation: dict[str, Any]) -> str:
    if not automation.get("enabled"):
        return (
            "<div class='panel'><h2>Build und Tests</h2>"
            f"<p>{html.escape(str(automation.get('reason') or 'Keine Automation ausgefuehrt.'))}</p>"
            "</div>"
        )
    runs_html = []
    for item in automation.get("runs", []):
        status = "ok" if item.get("success") else "failed"
        stdout_block = (
            f"<details><summary>stdout</summary><pre class='automation-pre'>{html.escape(str(item.get('stdout_tail') or ''))}</pre></details>"
            if item.get("stdout_tail")
            else ""
        )
        stderr_block = (
            f"<details><summary>stderr</summary><pre class='automation-pre'>{html.escape(str(item.get('stderr_tail') or ''))}</pre></details>"
            if item.get("stderr_tail")
            else ""
        )
        runs_html.append(
            f"<div class='automation-run {status}'>"
            f"<div class='automation-head'><strong>{html.escape(str(item.get('name') or ''))}</strong>"
            f"<span>{html.escape(str(item.get('command') or ''))}</span></div>"
            f"<div class='automation-meta'>Status: {status} | Exit: {item.get('exit_code')} | Dauer: {item.get('duration_seconds')}s</div>"
            f"{stdout_block}{stderr_block}</div>"
        )
    return (
        "<div class='panel'><h2>Build und Tests</h2>"
        f"<p class='lead'>Status: {html.escape(str(automation.get('status') or 'unknown'))} | "
        f"{automation.get('succeeded', 0)} erfolgreich | {automation.get('failed', 0)} fehlgeschlagen | "
        f"{automation.get('duration_seconds', 0)}s</p>"
        f"{''.join(runs_html) or '<p>Keine Automationsergebnisse.</p>'}"
        "</div>"
    )


def detail_page_name(event_id: str, relative_path: str) -> str:
    safe = relative_path.replace("/", "__").replace("\\", "__").replace(":", "_")
    digest = hashlib.sha1(relative_path.encode("utf-8")).hexdigest()[:8]
    return f"{event_id}--{safe}--{digest}.html"


def render_text_preview(lines: list[str], *, fallback: str) -> str:
    if not lines:
        return f"<p>{html.escape(fallback)}</p>"
    preview = "\n".join(lines[:240])
    if len(lines) > 240:
        preview += f"\n... {len(lines) - 240} weitere Zeilen"
    return f"<pre class='detail-pre'>{html.escape(preview)}</pre>"


def render_file_detail_page(
    root: pathlib.Path,
    event: dict[str, Any],
    item: dict[str, Any],
    *,
    previous_entry: dict[str, Any] | None,
    current_entry: dict[str, Any] | None,
) -> str:
    path_text = str(item.get("path", ""))
    previous_lines = list(previous_entry.get("lines", [])) if previous_entry else []
    current_lines = list(current_entry.get("lines", [])) if current_entry else []
    if previous_entry and current_entry and previous_entry.get("text_state") == "text" and current_entry.get("text_state") == "text":
        unified_diff = "\n".join(
            difflib.unified_diff(
                previous_lines,
                current_lines,
                fromfile=f"before/{path_text}",
                tofile=f"after/{path_text}",
                lineterm="",
            )
        )
    else:
        unified_diff = ""
    detail_summary = item.get("detail_summary") or event.get("summary", "")
    css = """
body { font-family: Segoe UI, Arial, sans-serif; background: #09111f; color: #e5e7eb; margin: 0; }
.wrap { max-width: 1200px; margin: 0 auto; padding: 28px 24px 60px; }
.top { display: flex; justify-content: space-between; gap: 20px; align-items: start; margin-bottom: 22px; }
.top h1 { margin: 0 0 8px; font-size: 32px; }
.muted { color: #94a3b8; }
.pill { display: inline-block; padding: 6px 10px; border-radius: 999px; background: rgba(59,130,246,.18); color: #bfdbfe; }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 18px; margin-bottom: 20px; }
.panel { background: rgba(15,23,42,.8); border: 1px solid rgba(148,163,184,.15); border-radius: 16px; padding: 18px; }
.panel h2 { margin-top: 0; }
.detail-pre, .diff-pre { white-space: pre-wrap; font-family: Consolas, monospace; background: rgba(2,6,23,.68); padding: 16px; border-radius: 14px; overflow: auto; }
.diff-pre { border: 1px solid rgba(125,211,252,.14); }
a { color: #7dd3fc; }
@media (max-width: 900px) { .grid { grid-template-columns: 1fr; } .top { flex-direction: column; } }
"""
    return (
        "<!DOCTYPE html><html lang='de'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{html.escape(path_text)} | Nova-shell Detaildiff</title><style>{css}</style></head><body><div class='wrap'>"
        "<div class='top'><div>"
        f"<span class='pill'>{html.escape(event.get('kind', 'change'))}</span>"
        f"<h1>{html.escape(path_text)}</h1>"
        f"<p class='muted'>{html.escape(detail_summary)}</p>"
        "</div><div><a href='../project_monitor_report.html'>Zurueck zum Hauptreport</a></div></div>"
        "<div class='grid'>"
        f"<section class='panel'><h2>Metadaten</h2><p><strong>Ereignis:</strong> {html.escape(event.get('id', ''))}</p>"
        f"<p><strong>Zeit:</strong> {fmt_ts(event.get('timestamp'))}</p>"
        f"<p><strong>Groesse:</strong> {fmt_size(item.get('before_size')) if 'before_size' in item else fmt_size(item.get('size'))}"
        f"{' -> ' + fmt_size(item.get('after_size')) if 'after_size' in item else ''}</p></section>"
        f"<section class='panel'><h2>Review-Kontext</h2><p>{html.escape((event.get('review_agent') or {}).get('summary', 'Keine Review-Zusammenfassung.'))}</p></section>"
        "</div>"
        "<div class='grid'>"
        f"<section class='panel'><h2>Vorher</h2>{render_text_preview(previous_lines, fallback='Keine Textansicht verfuegbar.')}</section>"
        f"<section class='panel'><h2>Nachher</h2>{render_text_preview(current_lines, fallback='Keine Textansicht verfuegbar.')}</section>"
        "</div>"
        f"<section class='panel'><h2>Kompletter Diff</h2>{f'<pre class=\"diff-pre\">{html.escape(unified_diff)}</pre>' if unified_diff else '<p>Kein textbasierter Diff verfuegbar.</p>'}</section>"
        "</div></body></html>"
    )


def attach_detail_pages(
    root: pathlib.Path,
    state_dir: pathlib.Path,
    event: dict[str, Any],
    previous_files: dict[str, Any],
    current_files: dict[str, Any],
) -> dict[str, Any]:
    if event.get("kind") != "change":
        return event
    detail_dir = state_dir / "files"
    detail_dir.mkdir(parents=True, exist_ok=True)
    for category in ("modified", "created", "deleted"):
        for item in event.get(category, []):
            path_text = str(item.get("path", ""))
            if not path_text:
                continue
            page_name = detail_page_name(str(event.get("id", "event")), path_text)
            previous_entry = previous_files.get(path_text)
            current_entry = current_files.get(path_text)
            if category == "created":
                item["detail_summary"] = "Neue Datei im Projekt."
                previous_entry = None
            elif category == "deleted":
                item["detail_summary"] = "Datei wurde aus dem Projekt entfernt."
                current_entry = None
            else:
                item["detail_summary"] = f"Datei geaendert: +{item.get('added_lines', 0)} / -{item.get('removed_lines', 0)} Zeilen."
            detail_path = detail_dir / page_name
            detail_path.write_text(
                render_file_detail_page(root, event, item, previous_entry=previous_entry, current_entry=current_entry),
                encoding="utf-8",
            )
            item["detail_page"] = f"files/{page_name}"
    return event


def create_watch_queue(root: pathlib.Path) -> tuple[Any, queue.Queue[str]] | tuple[None, queue.Queue[str]]:
    event_queue: queue.Queue[str] = queue.Queue()
    if not WATCHDOG_AVAILABLE:
        return None, event_queue
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    class MonitorEventHandler(FileSystemEventHandler):
        def _record(self, path_text: str) -> None:
            try:
                path = pathlib.Path(path_text).resolve()
                rel = path.relative_to(root)
            except Exception:
                return
            rel_parts = rel.parts
            if any(part in EXCLUDED_DIRS for part in rel_parts[:-1]):
                return
            if path.name in EXCLUDED_FILES:
                return
            event_queue.put(rel.as_posix())

        def on_created(self, event: Any) -> None:
            if not event.is_directory:
                self._record(event.src_path)

        def on_modified(self, event: Any) -> None:
            if not event.is_directory:
                self._record(event.src_path)

        def on_deleted(self, event: Any) -> None:
            if not event.is_directory:
                self._record(event.src_path)

        def on_moved(self, event: Any) -> None:
            if not event.is_directory:
                self._record(event.src_path)
                self._record(event.dest_path)

    observer = Observer()
    observer.schedule(MonitorEventHandler(), str(root), recursive=True)
    observer.start()
    return observer, event_queue


def wait_for_watch_batch(event_queue: queue.Queue[str], *, debounce_seconds: float) -> list[str]:
    first = event_queue.get()
    paths = {first}
    while True:
        try:
            item = event_queue.get(timeout=debounce_seconds)
            paths.add(item)
        except queue.Empty:
            break
    return sorted(paths)


def render_hotspot_bars(items: list[dict[str, Any]], label_key: str, title_key: str) -> str:
    if not items:
        return f"<div class='heat-block'><h3>{html.escape(title_key)}</h3><p>Noch keine Hotspot-Daten.</p></div>"
    rows = []
    for item in items:
        label = html.escape(str(item.get(label_key, "")))
        intensity = max(6, min(100, int(item.get("intensity", 0))))
        touches = int(item.get("touches", 0))
        churn = int(item.get("line_churn", 0))
        rows.append(
            "<div class='heat-item'>"
            f"<div class='heat-head'><strong>{label}</strong><span>{touches} Ereignisse | {churn} Zeilen Churn</span></div>"
            f"<div class='heat-bar'><span style='width:{intensity}%'></span></div>"
            "</div>"
        )
    return f"<div class='heat-block'><h3>{html.escape(title_key)}</h3>{''.join(rows)}</div>"


def render_list_entry(item: dict[str, Any]) -> str:
    detail_link = (
        f" <a class='detail-link' href='{html.escape(str(item.get('detail_page', '')))}' target='_blank' rel='noopener'>Detailseite</a>"
        if item.get("detail_page")
        else ""
    )
    return (
        f"<li>{html.escape(item.get('path', ''))}{detail_link} "
        f"<span>{fmt_size(item.get('size'))}, {item.get('line_count', 0)} Zeilen</span></li>"
    )


def render_diff_hunk(hunk: dict[str, Any]) -> str:
    removed = []
    for index, line in enumerate(hunk.get("removed", []), start=hunk.get("before_start", 1)):
        removed.append(f"<li><span class='ln'>{index}</span><code>{html.escape(line)}</code></li>")
    added = []
    for index, line in enumerate(hunk.get("added", []), start=hunk.get("after_start", 1)):
        added.append(f"<li><span class='ln'>{index}</span><code>{html.escape(line)}</code></li>")
    if hunk.get("removed_truncated"):
        removed.append(f"<li><em>... {hunk['removed_truncated']} weitere entfernte Zeilen</em></li>")
    if hunk.get("added_truncated"):
        added.append(f"<li><em>... {hunk['added_truncated']} weitere hinzugefuegte Zeilen</em></li>")
    return (
        "<div class='hunk'>"
        f"<div class='hunk-meta'>{html.escape(hunk.get('tag', 'change'))}: Alt {hunk.get('before_start')} bis {hunk.get('before_end')} | "
        f"Neu {hunk.get('after_start')} bis {hunk.get('after_end')}</div>"
        f"<div class='hunk-columns'><div><h5>Entfernt</h5><ol class='removed'>{''.join(removed) or '<li><em>Keine entfernten Zeilen</em></li>'}</ol></div>"
        f"<div><h5>Hinzugefuegt</h5><ol class='added'>{''.join(added) or '<li><em>Keine hinzugefuegten Zeilen</em></li>'}</ol></div></div>"
        "</div>"
    )


def render_html(
    root: pathlib.Path,
    snapshot: dict[str, Any],
    history_events: list[dict[str, Any]],
    analysis: dict[str, Any],
    current_event: dict[str, Any],
    runtime_status: dict[str, Any],
) -> str:
    latest_change = next((event for event in reversed(history_events) if event.get("kind") == "change"), None)
    current_stats = current_event.get("stats", {})
    latest_stats = latest_change.get("stats", {}) if latest_change else {}
    review_html = render_review_agent(current_event.get("review_agent", {}))
    automation_html = render_automation_panel(current_event.get("automation", {}))
    summary_cards = [
        ("Projektordner", str(root)),
        ("Letzter Scan", fmt_ts(snapshot.get("generated_at"))),
        ("Ueberwachte Dateien", str(snapshot.get("file_count", 0))),
        ("Historie", str(len(history_events))),
        ("Watch-Modus", str(runtime_status.get("watch_mode", "poll"))),
    ]
    cards_html = "".join(
        f"<div class='card'><div class='label'>{html.escape(label)}</div><div class='value'>{html.escape(value)}</div></div>"
        for label, value in summary_cards
    )
    current_status_html = (
        f"<p class='lead'>{html.escape(current_event.get('summary', 'Keine Aenderung erkannt.'))}</p>"
        f"<ul class='stat-list'><li>Neu: {current_stats.get('created', 0)}</li><li>Geaendert: {current_stats.get('modified', 0)}</li>"
        f"<li>Entfernt: {current_stats.get('deleted', 0)}</li><li>+Zeilen: {current_stats.get('added_lines', 0)}</li>"
        f"<li>-Zeilen: {current_stats.get('removed_lines', 0)}</li></ul>"
    )
    last_change_html = "<p>Noch keine aufgezeichnete Aenderung.</p>"
    if latest_change:
        last_change_html = (
            f"<p class='lead'>{html.escape(latest_change.get('summary', ''))}</p>"
            f"<ul class='stat-list'><li>Neu: {latest_stats.get('created', 0)}</li><li>Geaendert: {latest_stats.get('modified', 0)}</li>"
            f"<li>Entfernt: {latest_stats.get('deleted', 0)}</li><li>+Zeilen: {latest_stats.get('added_lines', 0)}</li>"
            f"<li>-Zeilen: {latest_stats.get('removed_lines', 0)}</li></ul>"
        )
    warnings_html = "".join(f"<li>{html.escape(item)}</li>" for item in analysis.get("warnings", [])) or "<li>Keine akuten Warnhinweise.</li>"
    insights_html = "".join(f"<li>{html.escape(item)}</li>" for item in analysis.get("insights", [])) or "<li>Noch keine Analyse-Hinweise.</li>"
    extension_rows = "".join(
        f"<tr><td>{html.escape(item['extension'])}</td><td>{item['file_count']}</td></tr>"
        for item in analysis.get("extension_ranking", [])
    ) or "<tr><td colspan='2'>Keine Daten</td></tr>"
    hotspot_rows = "".join(
        f"<tr><td>{html.escape(item['path'])}</td><td>{item['touches']}</td></tr>"
        for item in analysis.get("hotspots", [])
    ) or "<tr><td colspan='2'>Noch keine Hotspots</td></tr>"
    directory_rows = "".join(
        f"<tr><td>{html.escape(item['directory'])}</td><td>{item['touches']}</td></tr>"
        for item in analysis.get("directory_hotspots", [])
    ) or "<tr><td colspan='2'>Keine Daten</td></tr>"
    hotspot_bar_html = (
        render_hotspot_bars(analysis.get("file_hotspots", []), "path", "Datei-Hotspots")
        + render_hotspot_bars(analysis.get("directory_hotspots", []), "directory", "Ordner-Hotspots")
    )

    event_sections: list[str] = []
    for event in reversed(history_events[-20:]):
        modified_parts = []
        event_review = event.get("review_agent", {})
        event_meta = []
        if event_review.get("provider"):
            event_meta.append(f"Provider: {event_review.get('provider')}")
        if event_review.get("model"):
            event_meta.append(f"Modell: {event_review.get('model')}")
        event_meta.append(f"Quelle: {event_review.get('source', 'heuristic')}")
        event_meta.append(f"Modus: {event_review.get('mode', 'auto')}")
        event_review_html = (
            f"<div class='event-review severity-{html.escape(event_review.get('severity', 'low'))}'>"
            f"<strong>Review-Agent:</strong> {html.escape(event_review.get('summary', 'Keine Review-Zusammenfassung.'))}"
            f"<div class='event-review-meta'>{html.escape(' | '.join(event_meta))}</div></div>"
        )
        automation = event.get("automation", {})
        automation_summary = ""
        if automation.get("enabled"):
            automation_summary = (
                f"<div class='event-automation'><strong>Automation:</strong> "
                f"{html.escape(str(automation.get('status') or 'unknown'))} | "
                f"{automation.get('succeeded', 0)} ok | {automation.get('failed', 0)} failed</div>"
            )
        for item in event.get("modified", []):
            hunks_html = "".join(render_diff_hunk(hunk) for hunk in item.get("hunks", [])) or "<p>Keine Zeilen-Hunks verfuegbar (binaer oder zu gross).</p>"
            detail_link = (
                f" <a class='detail-link' href='{html.escape(str(item.get('detail_page', '')))}' target='_blank' rel='noopener'>Detailseite</a>"
                if item.get("detail_page")
                else ""
            )
            modified_parts.append(
                "<details class='file-change' open>"
                f"<summary>{html.escape(item.get('path', ''))}{detail_link} <span>+{item.get('added_lines', 0)} / -{item.get('removed_lines', 0)} Zeilen</span></summary>"
                f"<div class='file-meta'>Groesse: {fmt_size(item.get('before_size'))} -> {fmt_size(item.get('after_size'))} | "
                f"Zeilen: {item.get('before_line_count', 0)} -> {item.get('after_line_count', 0)}</div>"
                f"{hunks_html}"
                "</details>"
            )
        created_list = "".join(render_list_entry(item) for item in event.get("created", [])) or "<li>Keine neuen Dateien</li>"
        deleted_list = "".join(render_list_entry(item) for item in event.get("deleted", [])) or "<li>Keine entfernten Dateien</li>"
        event_sections.append(
            "<section class='event'>"
            f"<header><h3>{html.escape(event.get('summary', ''))}</h3><p>{fmt_ts(event.get('timestamp'))} | {html.escape(event.get('kind', 'scan'))}</p></header>"
            f"{event_review_html}"
            f"{automation_summary}"
            "<div class='event-grid'>"
            f"<div><h4>Neu</h4><ul>{created_list}</ul></div>"
            f"<div><h4>Entfernt</h4><ul>{deleted_list}</ul></div>"
            "</div>"
            f"<div class='modified-block'><h4>Geaenderte Dateien</h4>{''.join(modified_parts) or '<p>Keine geaenderten Dateien in diesem Ereignis.</p>'}</div>"
            "</section>"
        )

    css = """
body { font-family: Segoe UI, Arial, sans-serif; background: linear-gradient(180deg, #0f172a, #111827 45%, #030712); color: #e5e7eb; margin: 0; }
a { color: #7dd3fc; }
.container { max-width: 1500px; margin: 0 auto; padding: 32px 28px 80px; }
.hero { display: flex; justify-content: space-between; gap: 24px; align-items: end; margin-bottom: 24px; }
.hero h1 { margin: 0 0 8px; font-size: 40px; }
.hero p { margin: 0; color: #cbd5e1; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin: 24px 0 32px; }
.card { background: rgba(15, 23, 42, 0.78); border: 1px solid rgba(148, 163, 184, 0.18); border-radius: 18px; padding: 18px; box-shadow: 0 18px 50px rgba(0,0,0,0.28); }
.label { font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; color: #94a3b8; margin-bottom: 8px; }
.value { font-size: 22px; font-weight: 700; }
.panel-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; margin-bottom: 24px; }
.review-card, .panel, .event { background: rgba(15, 23, 42, 0.72); border: 1px solid rgba(148, 163, 184, 0.16); border-radius: 18px; padding: 20px; }
.review-head { display: flex; justify-content: space-between; align-items: center; gap: 18px; margin-bottom: 14px; }
.review-head h2 { margin: 0; font-size: 13px; letter-spacing: 0.08em; text-transform: uppercase; color: #94a3b8; }
.review-head h3 { margin: 6px 0 0; font-size: 24px; }
.review-badge { display: inline-block; padding: 6px 12px; border-radius: 999px; font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; }
.review-score { min-width: 60px; min-height: 60px; border-radius: 999px; display: grid; place-items: center; font-size: 22px; font-weight: 700; }
.review-meta { color: #94a3b8; margin: 8px 0 18px; }
.review-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; }
.panel, .event { background: rgba(15, 23, 42, 0.72); border: 1px solid rgba(148, 163, 184, 0.16); border-radius: 18px; padding: 20px; }
.panel h2, .event h3 { margin-top: 0; }
.lead { font-size: 18px; color: #f8fafc; }
.stat-list { display: flex; flex-wrap: wrap; gap: 14px; padding: 0; margin: 14px 0 0; list-style: none; color: #cbd5e1; }
.tables { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; margin-bottom: 28px; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 10px 12px; border-bottom: 1px solid rgba(148, 163, 184, 0.12); text-align: left; }
th { color: #93c5fd; font-size: 13px; letter-spacing: 0.06em; text-transform: uppercase; }
ul { padding-left: 18px; }
.event { margin-bottom: 18px; }
.event header p { color: #94a3b8; margin-top: 6px; }
.event-review { margin: 12px 0 16px; padding: 12px 14px; border-radius: 14px; font-size: 14px; }
.event-review-meta { margin-top: 8px; color: #cbd5e1; font-size: 13px; }
.event-automation { margin: -6px 0 16px; color: #cbd5e1; font-size: 13px; }
.event-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.file-change { background: rgba(2, 6, 23, 0.55); border: 1px solid rgba(125, 211, 252, 0.14); border-radius: 14px; padding: 12px 14px; margin-bottom: 14px; }
.file-change summary { cursor: pointer; font-weight: 700; }
.file-change summary span { color: #93c5fd; margin-left: 8px; font-weight: 500; }
.detail-link { color: #7dd3fc; margin-left: 10px; font-size: 13px; }
.file-meta { color: #94a3b8; margin: 10px 0 14px; }
.automation-run { margin-top: 14px; padding: 12px 14px; border-radius: 14px; background: rgba(2, 6, 23, 0.52); border: 1px solid rgba(148,163,184,.12); }
.automation-run.ok { border-color: rgba(16,185,129,.25); }
.automation-run.failed { border-color: rgba(239,68,68,.25); }
.automation-head { display: flex; justify-content: space-between; gap: 16px; margin-bottom: 8px; }
.automation-head span { color: #94a3b8; font-size: 13px; }
.automation-meta { color: #cbd5e1; font-size: 13px; margin-bottom: 8px; }
.automation-pre { white-space: pre-wrap; font-family: Consolas, monospace; background: rgba(2,6,23,.68); padding: 12px; border-radius: 10px; overflow: auto; }
.hunk { border-top: 1px solid rgba(148, 163, 184, 0.12); padding-top: 12px; margin-top: 12px; }
.hunk-meta { color: #fbbf24; margin-bottom: 10px; }
.hunk-columns { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.removed, .added { list-style: none; padding: 0; margin: 0; }
.removed li, .added li { display: grid; grid-template-columns: 64px 1fr; gap: 10px; padding: 6px 8px; border-radius: 10px; margin-bottom: 6px; }
.removed li { background: rgba(127, 29, 29, 0.38); }
.added li { background: rgba(20, 83, 45, 0.38); }
.ln { color: #f8fafc; opacity: 0.75; font-family: Consolas, monospace; }
code { white-space: pre-wrap; font-family: Consolas, monospace; color: #e2e8f0; }
.footer { margin-top: 28px; color: #94a3b8; font-size: 13px; }
.badge { display: inline-block; background: rgba(59, 130, 246, 0.18); color: #bfdbfe; border: 1px solid rgba(125,211,252,0.2); padding: 8px 12px; border-radius: 999px; font-size: 13px; }
.heat-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; margin-bottom: 28px; }
.heat-item { padding: 10px 0; }
.heat-head { display: flex; justify-content: space-between; gap: 14px; margin-bottom: 8px; color: #cbd5e1; }
.heat-head span { color: #94a3b8; font-size: 13px; }
.heat-bar { height: 12px; background: rgba(51, 65, 85, 0.55); border-radius: 999px; overflow: hidden; }
.heat-bar span { display: block; height: 100%; border-radius: 999px; background: linear-gradient(90deg, #38bdf8, #f59e0b, #ef4444); }
.severity-low { border-color: rgba(52, 211, 153, 0.25); }
.severity-medium { border-color: rgba(251, 191, 36, 0.3); }
.severity-high, .severity-critical { border-color: rgba(248, 113, 113, 0.35); }
.severity-low .review-badge, .severity-low .review-score, .severity-low.event-review { background: rgba(16, 185, 129, 0.18); color: #bbf7d0; }
.severity-medium .review-badge, .severity-medium .review-score, .severity-medium.event-review { background: rgba(245, 158, 11, 0.18); color: #fde68a; }
.severity-high .review-badge, .severity-high .review-score, .severity-high.event-review,
.severity-critical .review-badge, .severity-critical .review-score, .severity-critical.event-review { background: rgba(239, 68, 68, 0.18); color: #fecaca; }
@media (max-width: 1100px) { .panel-grid, .tables, .event-grid, .hunk-columns, .review-grid, .heat-grid { grid-template-columns: 1fr; } .hero { flex-direction: column; align-items: start; } }
"""
    return (
        "<!DOCTYPE html><html lang='de'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<meta http-equiv='refresh' content='3'><title>Nova-shell Projektmonitor</title>"
        f"<style>{css}</style></head><body><div class='container'>"
        "<div class='hero'><div><span class='badge'>Nova-shell Live Project Monitor</span>"
        f"<h1>Projektueberwachung fuer {html.escape(root.name)}</h1>"
        "<p>Automatische Aenderungserkennung, Zeilen-Diffs und Live-Analyse fuer den Projektordner.</p></div>"
        "<div><p><strong>Report-Datei:</strong> .nova_project_monitor/project_monitor_report.html</p>"
        "<p><strong>Analyse-Datei:</strong> .nova_project_monitor/project_monitor_analysis.json</p></div></div>"
        f"<section class='cards'>{cards_html}</section>"
        f"{review_html}"
        f"{automation_html}"
        "<section class='panel-grid'>"
        f"<div class='panel'><h2>Aktueller Scan</h2>{current_status_html}</div>"
        f"<div class='panel'><h2>Letzte aufgezeichnete Aenderung</h2>{last_change_html}</div>"
        f"<div class='panel'><h2>Analyse</h2><ul>{insights_html}</ul><h3>Warnungen</h3><ul>{warnings_html}</ul></div>"
        "</section>"
        f"<section class='tables'><div class='panel'><h2>Dateitypen</h2><table><thead><tr><th>Extension</th><th>Dateien</th></tr></thead><tbody>{extension_rows}</tbody></table></div>"
        f"<div class='panel'><h2>Hotspots</h2><table><thead><tr><th>Datei</th><th>Aenderungen</th></tr></thead><tbody>{hotspot_rows}</tbody></table></div>"
        f"<div class='panel'><h2>Ordner-Hotspots</h2><table><thead><tr><th>Ordner</th><th>Aenderungen</th></tr></thead><tbody>{directory_rows}</tbody></table></div></section>"
        f"<section class='panel heat-grid'>{hotspot_bar_html}</section>"
        f"<section class='panel'><h2>Aenderungshistorie</h2>{''.join(event_sections) or '<p>Noch keine Aenderungsereignisse.</p>'}</section>"
        f"<div class='footer'>Generiert von Nova-shell Projektmonitor v{VERSION} | Letzte Aktualisierung: {fmt_ts()}</div>"
        "</div></body></html>"
    )


def open_report_once(report_path: pathlib.Path, flag_path: pathlib.Path) -> None:
    if flag_path.exists() or not env_flag("NOVA_PROJECT_MONITOR_OPEN", True):
        return
    try:
        if os.name == "nt":
            os.startfile(str(report_path))
        elif sys.platform == "darwin":
            os.system(f'open "{report_path}"')
        else:
            os.system(f'xdg-open "{report_path}" >/dev/null 2>&1 &')
        flag_path.write_text(fmt_ts(), encoding="utf-8")
    except Exception:
        pass


def monitor_once(root: pathlib.Path, state_dir: pathlib.Path, *, runtime_status: dict[str, Any] | None = None) -> dict[str, Any]:
    snapshot_path = state_dir / "snapshot.json"
    history_path = state_dir / "history.json"
    analysis_path = state_dir / "project_monitor_analysis.json"
    report_path = state_dir / "project_monitor_report.html"
    status_path = state_dir / "latest_status.json"
    browser_flag = state_dir / ".browser_opened"
    runtime_payload = dict(runtime_status or {})
    previous = load_json(snapshot_path, {})
    history_payload = load_json(history_path, {"events": []})
    current = scan_project(root)
    current_event, changed = diff_snapshots(previous, current)
    current_event = attach_detail_pages(root, state_dir, current_event, previous.get("files", {}), current.get("files", {}))
    events = history_payload.get("events", [])
    if changed:
        events.append(current_event)
        events = events[-MAX_HISTORY:]
    history_payload = {"generated_at": current.get("generated_at"), "events": events}
    analysis = build_analysis(events, current)
    current_event["review_agent"] = build_review_agent(current_event, analysis)
    current_event["automation"] = run_automation_checks(root, current_event)
    if changed and events:
        events[-1]["review_agent"] = current_event["review_agent"]
        events[-1]["automation"] = current_event["automation"]
    save_json(snapshot_path, current)
    save_json(history_path, history_payload)
    save_json(analysis_path, analysis)
    report_path.write_text(render_html(root, current, events, analysis, current_event, runtime_payload), encoding="utf-8")
    payload = {
        "generated_at": current.get("generated_at"),
        "changed": changed,
        "event": current_event,
        "review_agent": current_event.get("review_agent", {}),
        "automation": current_event.get("automation", {}),
        "runtime": runtime_payload,
        "tracked_files": current.get("file_count", 0),
        "report_path": str(report_path),
        "analysis_path": str(analysis_path),
        "status_line": current_event.get("summary", "Keine Aenderung erkannt."),
    }
    save_json(status_path, payload)
    open_report_once(report_path, browser_flag)
    return payload


def main() -> dict[str, Any]:
    helper_path = pathlib.Path(__file__).resolve()
    root = pathlib.Path(os.environ.get("NOVA_PROJECT_MONITOR_ROOT") or helper_path.parent.parent).resolve()
    state_dir = root / ".nova_project_monitor"
    state_dir.mkdir(parents=True, exist_ok=True)
    interval = float(os.environ.get("NOVA_PROJECT_MONITOR_INTERVAL", "2"))
    debounce_seconds = float(os.environ.get("NOVA_PROJECT_MONITOR_DEBOUNCE", "1.0"))
    oneshot = env_flag("NOVA_PROJECT_MONITOR_ONESHOT", False)
    watch_config = resolve_watch_mode()
    latest: dict[str, Any] | None = None
    runtime_status = {
        "watch_mode": watch_config["mode"],
        "watch_requested": watch_config["requested"],
        "watch_reason": watch_config.get("reason", ""),
        "watchdog_available": WATCHDOG_AVAILABLE,
    }
    if oneshot:
        return monitor_once(root, state_dir, runtime_status=runtime_status)
    if watch_config["mode"] == "watchdog":
        observer, event_queue = create_watch_queue(root)
        try:
            latest = monitor_once(root, state_dir, runtime_status=runtime_status)
            while True:
                batch = wait_for_watch_batch(event_queue, debounce_seconds=debounce_seconds)
                runtime_status["last_trigger_paths"] = batch[:20]
                latest = monitor_once(root, state_dir, runtime_status=runtime_status)
        except KeyboardInterrupt:
            return latest or {"changed": False, "status_line": "Projektmonitor beendet.", "runtime": runtime_status}
        finally:
            if observer is not None:
                observer.stop()
                observer.join(timeout=5)
    while True:
        latest = monitor_once(root, state_dir, runtime_status=runtime_status)
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            return latest or {"changed": False, "status_line": "Projektmonitor beendet.", "runtime": runtime_status}


if __name__ == "__main__":
    main()
