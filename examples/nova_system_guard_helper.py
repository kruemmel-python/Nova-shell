"""Nova-shell Windows System Guard helper.

Focused host-integrity monitor for Windows persistence, temporary execution
paths and project integrity. It is designed to be embedded into a single
self-bootstrapping `.ns` file and updates an HTML report plus JSON state.
"""

from __future__ import annotations

import datetime as dt
import difflib
import hashlib
import html
import importlib.util
import json
import os
import pathlib
import queue
import shutil
import subprocess
import sys
import time
from collections import Counter
from typing import Any

VERSION = "1.0"
STATE_DIR_NAME = ".nova_system_guard"
MAX_HISTORY = 120
MAX_FILE_BYTES = 1024 * 1024
MAX_DIFF_HUNKS = 18
MAX_HUNK_LINES = 18
WATCHDOG_AVAILABLE = bool(importlib.util.find_spec("watchdog"))

PROJECT_EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "__pycache__",
    ".venv",
    "venv",
    STATE_DIR_NAME,
    ".nova_project_monitor",
}

SYSTEM_EXCLUDED_PARTS = {
    STATE_DIR_NAME,
}

TEXT_EXTENSIONS = {
    ".bat",
    ".cmd",
    ".conf",
    ".config",
    ".css",
    ".hta",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".log",
    ".md",
    ".ns",
    ".ps1",
    ".psd1",
    ".psm1",
    ".py",
    ".reg",
    ".sh",
    ".svg",
    ".toml",
    ".txt",
    ".vbs",
    ".wsf",
    ".xml",
    ".yaml",
    ".yml",
}

PROJECT_TEXT_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".go",
    ".graphql",
    ".h",
    ".hpp",
    ".java",
    ".jsx",
    ".kt",
    ".less",
    ".lua",
    ".mjs",
    ".php",
    ".rb",
    ".rs",
    ".scss",
    ".sql",
    ".ts",
    ".tsx",
    ".vue",
} | TEXT_EXTENSIONS

EXECUTABLE_EXTENSIONS = {
    ".appx",
    ".bat",
    ".cmd",
    ".com",
    ".dll",
    ".exe",
    ".hta",
    ".jar",
    ".jse",
    ".lnk",
    ".msi",
    ".msix",
    ".ps1",
    ".scr",
    ".sys",
    ".vbe",
    ".vbs",
    ".wsf",
}

DRIVER_EXTENSIONS = {".sys", ".cat"}
LIBRARY_EXTENSIONS = {".dll", ".ocx"}
SCRIPT_EXTENSIONS = {".bat", ".cmd", ".hta", ".js", ".jse", ".ps1", ".reg", ".vbe", ".vbs", ".wsf"}
BROWSER_EXTENSIONS = {".crx", ".dll", ".js", ".json"}
PROJECT_MARKERS = {
    ".git",
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "requirements.txt",
    "pom.xml",
    "build.gradle",
}
HIVE_NAMES = {"default", "sam", "security", "software", "system", "ntuser.dat"}
SIGNATURE_RELEVANT_KINDS = {"driver", "library", "executable", "script"}
SIGNATURE_CACHE: dict[str, dict[str, Any]] = {}


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
    if score >= 85:
        return "critical"
    if score >= 65:
        return "high"
    if score >= 35:
        return "medium"
    return "low"


def load_json(path: pathlib.Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: pathlib.Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_windows_path(path_text: str) -> pathlib.Path:
    expanded = os.path.expandvars(path_text.strip())
    return pathlib.Path(expanded).expanduser().resolve(strict=False)


def parse_env_paths(value: str) -> list[pathlib.Path]:
    items = [item.strip() for item in value.replace("\r", "\n").split("\n")]
    paths: list[pathlib.Path] = []
    for item in items:
        for segment in [part.strip() for part in item.split(";") if part.strip()]:
            paths.append(normalize_windows_path(segment))
    unique: list[pathlib.Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def run_powershell_json(script: str) -> list[dict[str, Any]] | dict[str, Any] | None:
    if os.name != "nt":
        return None
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    raw = (completed.stdout or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def ensure_list_payload(payload: list[dict[str, Any]] | dict[str, Any] | None) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def file_sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def read_text_payload(path: pathlib.Path) -> tuple[str | None, str]:
    try:
        data = path.read_bytes()
    except Exception as exc:
        return None, f"unreadable:{exc.__class__.__name__}"
    if len(data) > MAX_FILE_BYTES:
        return None, "too_large"
    if b"\x00" in data[:8192]:
        return None, "binary"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            return None, "binary"
    return text, "text"


def looks_like_project_root(path: pathlib.Path) -> bool:
    for marker in PROJECT_MARKERS:
        if (path / marker).exists():
            return True
    if any(path.glob("*.sln")):
        return True
    if any(path.glob("*.csproj")):
        return True
    if any(path.glob("tests")):
        return True
    return False


def default_scope_specs(root: pathlib.Path) -> list[dict[str, Any]]:
    home = pathlib.Path.home()
    appdata = pathlib.Path(os.environ.get("APPDATA") or (home / "AppData" / "Roaming"))
    localappdata = pathlib.Path(os.environ.get("LOCALAPPDATA") or (home / "AppData" / "Local"))
    system_root = pathlib.Path(os.environ.get("SystemRoot") or os.environ.get("WINDIR") or "C:/Windows")
    program_data = pathlib.Path(os.environ.get("ProgramData") or "C:/ProgramData")
    user_profile = pathlib.Path(os.environ.get("USERPROFILE") or home)

    specs: list[dict[str, Any]] = [
        {
            "name": "user_startup",
            "title": "User Startup",
            "path": appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup",
            "category": "persistence",
            "priority": "critical",
            "weight": 78,
            "recurse": True,
            "extensions": EXECUTABLE_EXTENSIONS,
        },
        {
            "name": "machine_startup",
            "title": "Machine Startup",
            "path": program_data / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup",
            "category": "persistence",
            "priority": "critical",
            "weight": 82,
            "recurse": True,
            "extensions": EXECUTABLE_EXTENSIONS,
        },
        {
            "name": "system_drivers",
            "title": "System32 Drivers",
            "path": system_root / "System32" / "drivers",
            "category": "kernel",
            "priority": "critical",
            "weight": 86,
            "recurse": True,
            "extensions": DRIVER_EXTENSIONS | {".dll", ".exe"},
        },
        {
            "name": "registry_hives",
            "title": "Registry Hives",
            "path": system_root / "System32" / "config",
            "category": "registry",
            "priority": "critical",
            "weight": 90,
            "recurse": True,
            "extensions": None,
        },
        {
            "name": "syswow64",
            "title": "SysWOW64",
            "path": system_root / "SysWOW64",
            "category": "system",
            "priority": "high",
            "weight": 62,
            "recurse": True,
            "extensions": {".dll", ".exe", ".ocx", ".com"},
        },
        {
            "name": "user_temp",
            "title": "User Temp",
            "path": localappdata / "Temp",
            "category": "temporary",
            "priority": "high",
            "weight": 56,
            "recurse": True,
            "extensions": EXECUTABLE_EXTENSIONS,
        },
        {
            "name": "windows_temp",
            "title": "Windows Temp",
            "path": system_root / "Temp",
            "category": "temporary",
            "priority": "high",
            "weight": 60,
            "recurse": True,
            "extensions": EXECUTABLE_EXTENSIONS,
        },
        {
            "name": "downloads",
            "title": "Downloads",
            "path": user_profile / "Downloads",
            "category": "downloads",
            "priority": "high",
            "weight": 48,
            "recurse": True,
            "extensions": EXECUTABLE_EXTENSIONS,
        },
        {
            "name": "chrome_extensions",
            "title": "Chrome Extensions",
            "path": localappdata / "Google" / "Chrome" / "User Data" / "Default" / "Extensions",
            "category": "browser_extensions",
            "priority": "high",
            "weight": 52,
            "recurse": True,
            "extensions": BROWSER_EXTENSIONS,
        },
        {
            "name": "roaming_profile",
            "title": "Roaming Profile",
            "path": appdata,
            "category": "profile",
            "priority": "high",
            "weight": 44,
            "recurse": True,
            "extensions": EXECUTABLE_EXTENSIONS,
        },
    ]

    project_mode = str(os.environ.get("NOVA_SYSTEM_GUARD_INCLUDE_PROJECT") or "auto").strip().lower()
    include_project = project_mode in {"1", "on", "true", "yes"}
    if project_mode == "auto":
        include_project = looks_like_project_root(root)
    if include_project:
        specs.append(
            {
                "name": "project_integrity",
                "title": "Project Integrity",
                "path": root,
                "category": "project",
                "priority": "medium",
                "weight": 28,
                "recurse": True,
                "extensions": None,
            }
        )

    return specs


def inventory_scope_specs() -> list[dict[str, Any]]:
    return [
        {
            "name": "scheduled_tasks",
            "title": "Scheduled Tasks",
            "path": pathlib.Path("inventory://scheduled_tasks"),
            "category": "persistence",
            "priority": "critical",
            "weight": 74,
            "recurse": False,
            "extensions": None,
            "scan_mode": "inventory",
        },
        {
            "name": "registry_run_keys",
            "title": "Registry Run Keys",
            "path": pathlib.Path("inventory://registry_run_keys"),
            "category": "persistence",
            "priority": "critical",
            "weight": 80,
            "recurse": False,
            "extensions": None,
            "scan_mode": "inventory",
        },
    ]


def classify_custom_scope(path: pathlib.Path) -> dict[str, Any]:
    normalized = str(path).replace("\\", "/").lower()
    if "startup" in normalized:
        return {"title": "Custom Startup Path", "category": "persistence", "priority": "critical", "weight": 76, "extensions": EXECUTABLE_EXTENSIONS}
    if normalized.endswith("/system32/config") or "/system32/config/" in normalized:
        return {"title": "Custom Registry Path", "category": "registry", "priority": "critical", "weight": 88, "extensions": None}
    if normalized.endswith("/system32/drivers") or "/drivers/" in normalized:
        return {"title": "Custom Driver Path", "category": "kernel", "priority": "critical", "weight": 82, "extensions": DRIVER_EXTENSIONS | {".dll", ".exe"}}
    if "downloads" in normalized:
        return {"title": "Custom Downloads Path", "category": "downloads", "priority": "high", "weight": 48, "extensions": EXECUTABLE_EXTENSIONS}
    if "/temp" in normalized or normalized.endswith("/temp"):
        return {"title": "Custom Temp Path", "category": "temporary", "priority": "high", "weight": 58, "extensions": EXECUTABLE_EXTENSIONS}
    if "chrome" in normalized and "extensions" in normalized:
        return {"title": "Custom Browser Extension Path", "category": "browser_extensions", "priority": "high", "weight": 52, "extensions": BROWSER_EXTENSIONS}
    if looks_like_project_root(path):
        return {"title": "Custom Project Integrity Path", "category": "project", "priority": "medium", "weight": 28, "extensions": None}
    return {"title": "Custom Path", "category": "custom", "priority": "high", "weight": 42, "extensions": None}


def resolve_scope_specs(root: pathlib.Path) -> list[dict[str, Any]]:
    include_defaults = env_flag("NOVA_SYSTEM_GUARD_INCLUDE_DEFAULTS", True)
    include_inventory = env_flag("NOVA_SYSTEM_GUARD_INCLUDE_WINDOWS_INVENTORY", True)
    custom_text = str(os.environ.get("NOVA_SYSTEM_GUARD_PATHS") or "").strip()
    scopes: list[dict[str, Any]] = []
    if include_defaults:
        scopes.extend(default_scope_specs(root))
    if include_inventory:
        scopes.extend(inventory_scope_specs())
    for index, path in enumerate(parse_env_paths(custom_text), start=1):
        descriptor = classify_custom_scope(path)
        scopes.append(
            {
                "name": f"custom_{index}",
                "title": f"{descriptor['title']} {index}",
                "path": path,
                "category": descriptor["category"],
                "priority": descriptor["priority"],
                "weight": descriptor["weight"],
                "recurse": True,
                "extensions": descriptor["extensions"],
            }
        )
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for spec in scopes:
        key = f"{spec['name']}::{str(spec['path']).lower()}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(spec)
    return unique


def get_authenticode_metadata(path: pathlib.Path) -> dict[str, Any]:
    cache_key = str(path).lower()
    if cache_key in SIGNATURE_CACHE:
        return dict(SIGNATURE_CACHE[cache_key])
    if os.name != "nt":
        payload = {"status": "unavailable", "publisher": "", "subject": "", "trusted": False}
        SIGNATURE_CACHE[cache_key] = payload
        return dict(payload)
    escaped = str(path).replace("'", "''")
    script = (
        "$sig = Get-AuthenticodeSignature -FilePath '" + escaped + "';"
        "$pub = '';"
        "if ($sig.SignerCertificate -and $sig.SignerCertificate.Subject) { $pub = [string]$sig.SignerCertificate.Subject };"
        "$obj = [pscustomobject]@{ "
        "Status = [string]$sig.Status; "
        "StatusMessage = [string]$sig.StatusMessage; "
        "Publisher = $pub; "
        "Thumbprint = if ($sig.SignerCertificate) { [string]$sig.SignerCertificate.Thumbprint } else { '' } "
        "};"
        "$obj | ConvertTo-Json -Compress"
    )
    payload = run_powershell_json(script)
    meta = {
        "status": str((payload or {}).get("Status") or "").strip() if isinstance(payload, dict) else "",
        "status_message": str((payload or {}).get("StatusMessage") or "").strip() if isinstance(payload, dict) else "",
        "publisher": str((payload or {}).get("Publisher") or "").strip() if isinstance(payload, dict) else "",
        "thumbprint": str((payload or {}).get("Thumbprint") or "").strip() if isinstance(payload, dict) else "",
    }
    status = meta["status"] or "unknown"
    meta["status"] = status
    meta["trusted"] = status.lower() in {"valid"}
    SIGNATURE_CACHE[cache_key] = meta
    return dict(meta)


def collect_scheduled_tasks() -> list[dict[str, Any]]:
    script = (
        "Get-ScheduledTask | "
        "Select-Object TaskName, TaskPath, State, Author, "
        "@{n='Actions';e={($_.Actions | ForEach-Object { ($_.Execute + ' ' + $_.Arguments).Trim() }) -join '; '}}, "
        "@{n='Principal';e={$_.Principal.UserId}} | ConvertTo-Json -Depth 4 -Compress"
    )
    rows = ensure_list_payload(run_powershell_json(script))
    result: list[dict[str, Any]] = []
    for row in rows:
        task_name = str(row.get("TaskName") or "").strip()
        if not task_name:
            continue
        task_path = str(row.get("TaskPath") or "\\").strip()
        actions = str(row.get("Actions") or "").strip()
        rel = f"{task_path}{task_name}".replace("\\", "/").strip("/") or task_name
        result.append(
            {
                "relative_path": rel,
                "path": rel,
                "absolute_path": f"task://{rel}",
                "name": task_name,
                "lines": [actions] if actions else [],
                "line_count": 1 if actions else 0,
                "state": str(row.get("State") or "").strip(),
                "author": str(row.get("Author") or "").strip(),
                "principal": str(row.get("Principal") or "").strip(),
                "command": actions,
            }
        )
    return result


def collect_run_keys() -> list[dict[str, Any]]:
    script = (
        "$paths = @("
        "'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run',"
        "'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\RunOnce',"
        "'HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run',"
        "'HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\RunOnce',"
        "'HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Run'"
        ");"
        "$items = foreach ($path in $paths) {"
        " if (Test-Path $path) {"
        "  $props = Get-ItemProperty -Path $path;"
        "  foreach ($prop in $props.PSObject.Properties) {"
        "   if ($prop.Name -notlike 'PS*') {"
        "    [pscustomobject]@{ KeyPath = $path; Name = [string]$prop.Name; Command = [string]$prop.Value }"
        "   }"
        "  }"
        " }"
        "};"
        "$items | ConvertTo-Json -Depth 4 -Compress"
    )
    rows = ensure_list_payload(run_powershell_json(script))
    result: list[dict[str, Any]] = []
    for row in rows:
        key_path = str(row.get("KeyPath") or "").strip()
        name = str(row.get("Name") or "").strip()
        command = str(row.get("Command") or "").strip()
        if not name:
            continue
        rel = f"{key_path}::{name}".replace("\\", "/")
        result.append(
            {
                "relative_path": rel,
                "path": rel,
                "absolute_path": f"reg://{rel}",
                "name": name,
                "lines": [command] if command else [],
                "line_count": 1 if command else 0,
                "key_path": key_path,
                "command": command,
            }
        )
    return result


def should_skip_path(scope: dict[str, Any], rel_path: pathlib.Path) -> bool:
    parts = rel_path.parts[:-1]
    blocked = PROJECT_EXCLUDED_DIRS if scope.get("category") == "project" else SYSTEM_EXCLUDED_PARTS
    return any(part in blocked for part in parts)


def scope_matches_file(scope: dict[str, Any], path: pathlib.Path) -> bool:
    extensions = scope.get("extensions")
    if not extensions:
        if scope.get("category") == "project":
            return path.suffix.lower() in PROJECT_TEXT_EXTENSIONS or path.suffix.lower() in EXECUTABLE_EXTENSIONS or not path.suffix
        return True
    suffix = path.suffix.lower()
    return suffix in extensions or path.name.lower() in HIVE_NAMES


def classify_kind(path: pathlib.Path, scope: dict[str, Any]) -> str:
    suffix = path.suffix.lower()
    name = path.name.lower()
    if name in HIVE_NAMES:
        return "registry_hive"
    if suffix in DRIVER_EXTENSIONS:
        return "driver"
    if suffix in LIBRARY_EXTENSIONS:
        return "library"
    if suffix in SCRIPT_EXTENSIONS:
        return "script"
    if suffix in EXECUTABLE_EXTENSIONS:
        return "executable"
    if scope.get("name") == "chrome_extensions" and suffix in {".js", ".json", ".crx"}:
        return "browser_extension"
    if suffix == ".lnk":
        return "shortcut"
    return "file"


def classify_inventory_kind(scope: dict[str, Any], record: dict[str, Any]) -> str:
    if scope.get("name") == "scheduled_tasks":
        command = str(record.get("command") or "").lower()
        if any(token in command for token in (".ps1", ".bat", ".cmd", ".vbs", ".js", "powershell", "wscript", "cscript", ".exe")):
            return "scheduled_task"
        return "scheduled_task"
    if scope.get("name") == "registry_run_keys":
        command = str(record.get("command") or "").lower()
        if any(token in command for token in (".ps1", ".bat", ".cmd", ".vbs", ".js", ".exe", "powershell", "wscript", "cscript")):
            return "run_key"
        return "run_key"
    return "inventory"


def compute_risk(scope: dict[str, Any], path: pathlib.Path, kind: str) -> tuple[int, list[str]]:
    score = int(scope.get("weight", 25))
    reasons: list[str] = [f"Scope {scope.get('title')} ist als {scope.get('priority')} priorisiert."]
    name = path.name.lower()
    suffix = path.suffix.lower()

    if kind == "registry_hive":
        score += 30
        reasons.append("Registry-Hive-Verzeichnis wurde beruehrt.")
    if kind == "driver":
        score += 28
        reasons.append("Treiberdatei in einem Kernel-nahen Pfad.")
    if kind == "library":
        score += 16
        reasons.append("Bibliothek in einem privilegierten Pfad.")
    if kind == "executable":
        score += 18
        reasons.append("Ausfuehrbare Datei erkannt.")
    if kind == "script":
        score += 15
        reasons.append("Ausfuehrbares Skript erkannt.")
    if scope.get("category") == "persistence":
        score += 18
        reasons.append("Persistenzpfad kann Autostart etablieren.")
    if scope.get("category") == "temporary" and suffix in EXECUTABLE_EXTENSIONS:
        score += 18
        reasons.append("Ausfuehrbare Datei in einem Temp-Verzeichnis.")
    if scope.get("category") == "downloads" and suffix in EXECUTABLE_EXTENSIONS:
        score += 14
        reasons.append("Neu eingetroffene ausfuehrbare Datei in Downloads.")
    if scope.get("category") == "browser_extensions" and suffix in {".js", ".dll", ".crx"}:
        score += 10
        reasons.append("Browser-Erweiterungsdatei kann Laufzeitcode beeinflussen.")
    if name.count(".") >= 2 and any(name.endswith(f"{extra}{suffix}") for extra in (".pdf", ".doc", ".txt", ".jpg", ".png")):
        score += 14
        reasons.append("Doppelte Dateiendung wirkt tauschend echt.")
    if any(token in name for token in ("autorun", "startup", "update", "patch", "svc", "driver", "inject")):
        score += 8
        reasons.append("Dateiname enthaelt ein fuer Persistenz oder Injektion typisches Muster.")
    return min(100, score), reasons


def compute_inventory_risk(scope: dict[str, Any], record: dict[str, Any], kind: str) -> tuple[int, list[str]]:
    score = int(scope.get("weight", 25))
    reasons = [f"Inventar-Quelle {scope.get('title')} ist als {scope.get('priority')} priorisiert."]
    command = str(record.get("command") or "").lower()
    name = str(record.get("name") or "").lower()
    if kind == "scheduled_task":
        score += 18
        reasons.append("Geplanter Task kann versteckte Persistenz oder spaetere Ausfuehrung etablieren.")
    if kind == "run_key":
        score += 24
        reasons.append("Registry-Run-Key startet Code bei Benutzer- oder Systemanmeldung.")
    if any(token in command for token in ("powershell", "wscript", "cscript", "mshta", "rundll32", "regsvr32")):
        score += 14
        reasons.append("Ausfuehrung ueber typische Living-off-the-Land-Binaries.")
    if any(token in command for token in (".ps1", ".bat", ".cmd", ".vbs", ".js", ".exe", ".dll")):
        score += 12
        reasons.append("Command verweist direkt auf ausfuehrbaren Code.")
    if any(token in name for token in ("update", "service", "helper", "autorun", "startup")):
        score += 6
        reasons.append("Name wirkt wie ein Tarnmuster fuer Persistenz.")
    return min(100, score), reasons


def snapshot_entry(scope: dict[str, Any], path: pathlib.Path) -> dict[str, Any] | None:
    scope_root = pathlib.Path(scope["path"])
    try:
        stat = path.stat()
        digest = file_sha256(path)
        rel_path = path.relative_to(scope_root).as_posix()
    except OSError:
        return None
    text = None
    text_state = "skipped"
    if path.suffix.lower() in TEXT_EXTENSIONS or (scope.get("category") == "project" and path.suffix.lower() in PROJECT_TEXT_EXTENSIONS):
        text, text_state = read_text_payload(path)
    lines = text.splitlines() if text is not None else []
    kind = classify_kind(path, scope)
    risk_score, risk_reasons = compute_risk(scope, path, kind)
    signature = {"status": "", "status_message": "", "publisher": "", "thumbprint": "", "trusted": False}
    if kind in SIGNATURE_RELEVANT_KINDS and path.suffix.lower() in {".exe", ".dll", ".sys", ".ocx", ".msi", ".ps1", ".bat", ".cmd"}:
        signature = get_authenticode_metadata(path)
        if signature.get("status"):
            status = str(signature.get("status") or "").lower()
            if status in {"notsigned", "unknownerror", "hashmismatch", "nottrusted", "unknown"}:
                risk_score = min(100, risk_score + 16)
                risk_reasons.append(f"Signaturstatus ist {signature.get('status')}.")
            elif status == "valid":
                risk_reasons.append("Datei besitzt eine gueltige Authenticode-Signatur.")
        if signature.get("publisher"):
            risk_reasons.append(f"Publisher: {signature.get('publisher')}.")
    return {
        "scope_name": scope["name"],
        "scope_title": scope["title"],
        "scope_category": scope["category"],
        "scope_priority": scope["priority"],
        "scope_path": str(scope_root),
        "relative_path": rel_path,
        "path": f"{scope['title']} :: {rel_path}",
        "absolute_path": str(path),
        "name": path.name,
        "extension": path.suffix.lower() or "[no extension]",
        "kind": kind,
        "size": stat.st_size,
        "modified_at": stat.st_mtime,
        "sha256": digest,
        "line_count": len(lines),
        "text_state": text_state,
        "lines": lines,
        "risk_score": risk_score,
        "risk_severity": severity_label(risk_score),
        "risk_reasons": risk_reasons,
        "signature_status": signature.get("status", ""),
        "signature_message": signature.get("status_message", ""),
        "publisher": signature.get("publisher", ""),
        "signature_thumbprint": signature.get("thumbprint", ""),
        "signature_trusted": bool(signature.get("trusted", False)),
    }


def snapshot_inventory_entry(scope: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    kind = classify_inventory_kind(scope, record)
    risk_score, risk_reasons = compute_inventory_risk(scope, record, kind)
    command = str(record.get("command") or "")
    digest = hashlib.sha256((record.get("relative_path", "") + "|" + command).encode("utf-8")).hexdigest()
    return {
        "scope_name": scope["name"],
        "scope_title": scope["title"],
        "scope_category": scope["category"],
        "scope_priority": scope["priority"],
        "scope_path": str(scope["path"]),
        "relative_path": str(record.get("relative_path") or record.get("name") or ""),
        "path": f"{scope['title']} :: {record.get('path') or record.get('relative_path') or record.get('name')}",
        "absolute_path": str(record.get("absolute_path") or ""),
        "name": str(record.get("name") or ""),
        "extension": "[inventory]",
        "kind": kind,
        "size": len(command.encode("utf-8")),
        "modified_at": time.time(),
        "sha256": digest,
        "line_count": int(record.get("line_count") or 0),
        "text_state": "text",
        "lines": list(record.get("lines") or []),
        "risk_score": risk_score,
        "risk_severity": severity_label(risk_score),
        "risk_reasons": risk_reasons,
        "command": command,
        "task_state": str(record.get("state") or ""),
        "task_author": str(record.get("author") or ""),
        "task_principal": str(record.get("principal") or ""),
        "registry_key_path": str(record.get("key_path") or ""),
        "publisher": "",
        "signature_status": "",
        "signature_message": "",
        "signature_thumbprint": "",
        "signature_trusted": False,
    }


def scan_scope(scope: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, int], dict[str, int]]:
    if scope.get("scan_mode") == "inventory":
        files: dict[str, dict[str, Any]] = {}
        extension_counts: Counter[str] = Counter()
        kind_counts: Counter[str] = Counter()
        records = collect_scheduled_tasks() if scope.get("name") == "scheduled_tasks" else collect_run_keys()
        for record in records:
            entry = snapshot_inventory_entry(scope, record)
            key = f"{scope['name']}::{entry['relative_path']}"
            files[key] = entry
            extension_counts[entry["extension"]] += 1
            kind_counts[entry["kind"]] += 1
        return files, dict(extension_counts), dict(kind_counts)

    root = pathlib.Path(scope["path"])
    files: dict[str, dict[str, Any]] = {}
    extension_counts: Counter[str] = Counter()
    kind_counts: Counter[str] = Counter()
    if not root.exists():
        return files, dict(extension_counts), dict(kind_counts)
    iterator = root.rglob("*") if scope.get("recurse", True) else root.iterdir()
    for path in iterator:
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(root)
        except Exception:
            continue
        if should_skip_path(scope, rel):
            continue
        if not scope_matches_file(scope, path):
            continue
        entry = snapshot_entry(scope, path)
        if not entry:
            continue
        key = f"{scope['name']}::{entry['relative_path']}"
        files[key] = entry
        extension_counts[entry["extension"]] += 1
        kind_counts[entry["kind"]] += 1
    return files, dict(extension_counts), dict(kind_counts)


def scan_targets(scopes: list[dict[str, Any]]) -> dict[str, Any]:
    files: dict[str, dict[str, Any]] = {}
    extension_counts: Counter[str] = Counter()
    kind_counts: Counter[str] = Counter()
    scope_counts: dict[str, dict[str, Any]] = {}
    for scope in scopes:
        scope_files, scope_exts, scope_kinds = scan_scope(scope)
        files.update(scope_files)
        for key, value in scope_exts.items():
            extension_counts[key] += int(value)
        for key, value in scope_kinds.items():
            kind_counts[key] += int(value)
        scope_counts[scope["name"]] = {
            "title": scope["title"],
            "path": str(scope["path"]),
            "category": scope["category"],
            "priority": scope["priority"],
            "exists": pathlib.Path(scope["path"]).exists(),
            "file_count": len(scope_files),
        }
    return {
        "generated_at": time.time(),
        "file_count": len(files),
        "files": files,
        "extension_counts": dict(sorted(extension_counts.items())),
        "kind_counts": dict(sorted(kind_counts.items())),
        "scope_counts": scope_counts,
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


def event_item_from_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": entry.get("path"),
        "absolute_path": entry.get("absolute_path"),
        "relative_path": entry.get("relative_path"),
        "scope_name": entry.get("scope_name"),
        "scope_title": entry.get("scope_title"),
        "scope_category": entry.get("scope_category"),
        "scope_priority": entry.get("scope_priority"),
        "kind": entry.get("kind"),
        "size": entry.get("size"),
        "line_count": entry.get("line_count"),
        "extension": entry.get("extension"),
        "risk_score": entry.get("risk_score"),
        "risk_severity": entry.get("risk_severity"),
        "risk_reasons": entry.get("risk_reasons", []),
        "publisher": entry.get("publisher", ""),
        "signature_status": entry.get("signature_status", ""),
        "signature_message": entry.get("signature_message", ""),
        "signature_trusted": bool(entry.get("signature_trusted", False)),
        "command": entry.get("command", ""),
        "task_state": entry.get("task_state", ""),
        "task_author": entry.get("task_author", ""),
        "task_principal": entry.get("task_principal", ""),
        "registry_key_path": entry.get("registry_key_path", ""),
    }


def build_review(event: dict[str, Any]) -> dict[str, Any]:
    changed_items = [*event.get("created", []), *event.get("modified", []), *event.get("deleted", [])]
    if not changed_items:
        return {
            "severity": "low",
            "score": 5,
            "headline": "Keine sicherheitsrelevante Aenderung",
            "summary": "System Guard hat keine neue sicherheitsrelevante Aenderung erkannt.",
            "findings": [],
            "recommendations": [],
            "source": "heuristic-security",
        }
    highest = max(int(item.get("risk_score", 0)) for item in changed_items)
    severity = severity_label(highest)
    findings: list[str] = []
    recommendations: list[str] = []
    critical_scopes = sorted({item.get("scope_title", "") for item in changed_items if item.get("risk_score", 0) >= 75})
    temp_execs = [item for item in changed_items if item.get("scope_name") in {"user_temp", "windows_temp", "downloads"} and item.get("kind") in {"executable", "script"}]
    persistence_hits = [item for item in changed_items if item.get("scope_category") == "persistence"]
    driver_hits = [item for item in changed_items if item.get("kind") in {"driver", "registry_hive"}]
    scheduled_hits = [item for item in changed_items if item.get("kind") == "scheduled_task"]
    run_key_hits = [item for item in changed_items if item.get("kind") == "run_key"]
    unsigned_hits = [item for item in changed_items if item.get("signature_status") and not item.get("signature_trusted")]

    if critical_scopes:
        findings.append("Kritische Scope-Beruehrung: " + ", ".join(critical_scopes))
    if persistence_hits:
        findings.append(f"{len(persistence_hits)} Persistenz-bezogene Datei(en) veraendert.")
        recommendations.append("Autostart-Eintraege und geplante Tasks gegenpruefen.")
    if scheduled_hits:
        findings.append(f"{len(scheduled_hits)} Scheduled-Task-Eintrag(e) geaendert oder neu erkannt.")
        recommendations.append("Task-Command, Benutzerkontext und Trigger pruefen.")
    if run_key_hits:
        findings.append(f"{len(run_key_hits)} Run-Key-Eintrag(e) geaendert oder neu erkannt.")
        recommendations.append("Run- und RunOnce-Keys gegen bekannte Persistenz pruefen.")
    if driver_hits:
        findings.append(f"{len(driver_hits)} Kernel- oder Registry-nahe Datei(en) betroffen.")
        recommendations.append("Windows-Update-/Treiber-Aktivitaet verifizieren und Hashes abgleichen.")
    if temp_execs:
        findings.append(f"{len(temp_execs)} ausfuehrbare Datei(en) in Temp/Downloads erkannt.")
        recommendations.append("Dateiherkunft, Signatur und Elternprozess pruefen.")
    if unsigned_hits:
        findings.append(f"{len(unsigned_hits)} Datei(en) mit fehlender oder nicht vertrauenswuerdiger Signatur erkannt.")
        recommendations.append("Publisher und Authenticode-Status explizit verifizieren.")
    if not findings:
        findings.append("Aenderungen sind sichtbar, aber ohne eindeutiges Hochrisiko-Muster.")
        recommendations.append("Betroffene Dateien stichprobenartig pruefen.")

    summary = (
        f"System Guard bewertet dieses Ereignis als {severity}. "
        f"{len(changed_items)} Datei(en) betroffen, hoechster Risiko-Score {highest}."
    )
    if critical_scopes:
        summary += " Kritische Bereiche: " + ", ".join(critical_scopes) + "."
    return {
        "severity": severity,
        "score": highest,
        "headline": "Nova System Guard",
        "summary": summary,
        "findings": findings[:6],
        "recommendations": recommendations[:6],
        "source": "heuristic-security",
    }


def diff_snapshots(previous: dict[str, Any] | None, current: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    if not previous or not previous.get("files"):
        baseline = {
            "id": f"baseline-{int(current['generated_at'])}",
            "timestamp": current["generated_at"],
            "kind": "baseline",
            "summary": f"Erster Sicherheits-Snapshot erstellt. {current['file_count']} Datei(en) in {len(current.get('scope_counts', {}))} Scope(s) im Blick.",
            "created": [event_item_from_entry(entry) for _, entry in sorted(current["files"].items())],
            "modified": [],
            "deleted": [],
            "stats": {
                "created": current["file_count"],
                "modified": 0,
                "deleted": 0,
                "added_lines": 0,
                "removed_lines": 0,
                "critical": sum(1 for item in current["files"].values() if item.get("risk_score", 0) >= 85),
                "high": sum(1 for item in current["files"].values() if 65 <= item.get("risk_score", 0) < 85),
            },
        }
        baseline["review"] = build_review(baseline)
        return baseline, True

    prev_files = previous.get("files", {})
    curr_files = current.get("files", {})
    created_keys = sorted(set(curr_files) - set(prev_files))
    deleted_keys = sorted(set(prev_files) - set(curr_files))
    common_keys = sorted(set(curr_files) & set(prev_files))
    created: list[dict[str, Any]] = []
    deleted: list[dict[str, Any]] = []
    modified: list[dict[str, Any]] = []
    added_lines_total = 0
    removed_lines_total = 0

    for key in created_keys:
        entry = curr_files[key]
        created.append(event_item_from_entry(entry))
        added_lines_total += int(entry.get("line_count", 0))

    for key in deleted_keys:
        entry = prev_files[key]
        deleted.append(event_item_from_entry(entry))
        removed_lines_total += int(entry.get("line_count", 0))

    for key in common_keys:
        before = prev_files[key]
        after = curr_files[key]
        if before.get("sha256") == after.get("sha256"):
            continue
        hunks: list[dict[str, Any]] = []
        added_lines = 0
        removed_lines = 0
        if before.get("text_state") == "text" and after.get("text_state") == "text":
            hunks, added_lines, removed_lines = summarize_hunks(before.get("lines", []), after.get("lines", []))
        item = event_item_from_entry(after)
        item.update(
            {
                "before_size": before.get("size", 0),
                "after_size": after.get("size", 0),
                "before_line_count": before.get("line_count", 0),
                "after_line_count": after.get("line_count", 0),
                "before_state": before.get("text_state"),
                "after_state": after.get("text_state"),
                "added_lines": added_lines,
                "removed_lines": removed_lines,
                "hunks": hunks,
            }
        )
        modified.append(item)
        added_lines_total += added_lines
        removed_lines_total += removed_lines

    if not created and not modified and not deleted:
        event = {
            "id": f"scan-{int(current['generated_at'])}",
            "timestamp": current["generated_at"],
            "kind": "no_change",
            "summary": f"Keine sicherheitsrelevante Aenderung erkannt. {current['file_count']} Datei(en) bleiben unter Beobachtung.",
            "created": [],
            "modified": [],
            "deleted": [],
            "stats": {"created": 0, "modified": 0, "deleted": 0, "added_lines": 0, "removed_lines": 0, "critical": 0, "high": 0},
        }
        event["review"] = build_review(event)
        return event, False

    changed_items = [*created, *modified, *deleted]
    critical_count = sum(1 for item in changed_items if item.get("risk_score", 0) >= 85)
    high_count = sum(1 for item in changed_items if 65 <= item.get("risk_score", 0) < 85)
    parts: list[str] = []
    if critical_count:
        parts.append(f"{critical_count} kritisch")
    if high_count:
        parts.append(f"{high_count} hoch")
    if created:
        parts.append(f"{len(created)} neu")
    if modified:
        parts.append(f"{len(modified)} geaendert")
    if deleted:
        parts.append(f"{len(deleted)} entfernt")
    event = {
        "id": f"change-{int(current['generated_at'])}",
        "timestamp": current["generated_at"],
        "kind": "change",
        "summary": "Sicherheitsrelevante Aenderung erkannt: " + ", ".join(parts) + f" | +{added_lines_total} / -{removed_lines_total} Zeilen",
        "created": created,
        "modified": modified,
        "deleted": deleted,
        "stats": {
            "created": len(created),
            "modified": len(modified),
            "deleted": len(deleted),
            "added_lines": added_lines_total,
            "removed_lines": removed_lines_total,
            "critical": critical_count,
            "high": high_count,
        },
    }
    event["review"] = build_review(event)
    return event, True


def build_analysis(history_events: list[dict[str, Any]], snapshot: dict[str, Any]) -> dict[str, Any]:
    hotspot_counter: Counter[str] = Counter()
    scope_counter: Counter[str] = Counter()
    critical_paths: list[dict[str, Any]] = []
    warnings: list[str] = []
    recent_changes = [event for event in history_events if event.get("kind") == "change"][-25:]

    for event in recent_changes:
        for category in ("created", "modified", "deleted"):
            for item in event.get(category, []):
                hotspot_counter[item.get("path", "")] += 1
                scope_counter[item.get("scope_title", "")] += 1

    for entry in snapshot.get("files", {}).values():
        if int(entry.get("risk_score", 0)) >= 75:
            critical_paths.append(
                {
                    "path": entry.get("path"),
                    "absolute_path": entry.get("absolute_path"),
                    "risk_score": entry.get("risk_score"),
                    "severity": entry.get("risk_severity"),
                    "kind": entry.get("kind"),
                }
            )
    critical_paths = sorted(critical_paths, key=lambda item: (-int(item["risk_score"]), str(item["path"])))[:15]
    unsigned_paths = [
        {
            "path": entry.get("path"),
            "absolute_path": entry.get("absolute_path"),
            "signature_status": entry.get("signature_status"),
            "publisher": entry.get("publisher"),
            "risk_score": entry.get("risk_score"),
        }
        for entry in snapshot.get("files", {}).values()
        if entry.get("signature_status") and not entry.get("signature_trusted")
    ]
    unsigned_paths = sorted(unsigned_paths, key=lambda item: (-int(item["risk_score"]), str(item["path"])))[:12]

    if critical_paths:
        warnings.append("Es existieren aktiv ueberwachte Hochrisiko-Dateien in kritischen Windows-Pfaden.")
    if unsigned_paths:
        warnings.append("Es wurden unsignierte oder nicht vertrauenswuerdige Binärdateien erkannt.")
    if recent_changes:
        last = recent_changes[-1]
        if last.get("stats", {}).get("critical", 0):
            warnings.append("Der letzte Aenderungsblock beruehrte mindestens eine kritische Datei.")
        if last.get("stats", {}).get("modified", 0) + last.get("stats", {}).get("created", 0) >= 6:
            warnings.append("Viele Dateien wurden in einem einzelnen Sicherheitsereignis veraendert.")

    scope_rows = [
        {
            "title": item["title"],
            "path": item["path"],
            "priority": item["priority"],
            "file_count": item["file_count"],
            "exists": item["exists"],
        }
        for item in snapshot.get("scope_counts", {}).values()
    ]
    scope_rows.sort(key=lambda item: (-item["file_count"], item["title"]))
    return {
        "generated_at": snapshot.get("generated_at"),
        "warnings": warnings,
        "critical_paths": critical_paths,
        "unsigned_paths": unsigned_paths,
        "hotspots": [{"path": path, "touches": count} for path, count in hotspot_counter.most_common(12)],
        "scope_activity": [{"scope": scope, "touches": count} for scope, count in scope_counter.most_common(12)],
        "scope_rows": scope_rows,
        "extension_ranking": [{"extension": ext, "file_count": count} for ext, count in sorted(snapshot.get("extension_counts", {}).items(), key=lambda item: (-item[1], item[0]))[:12]],
        "kind_ranking": [{"kind": kind, "file_count": count} for kind, count in sorted(snapshot.get("kind_counts", {}).items(), key=lambda item: (-item[1], item[0]))[:12]],
    }


def detail_page_name(event_id: str, path_key: str) -> str:
    digest = hashlib.sha1(f"{event_id}:{path_key}".encode("utf-8")).hexdigest()[:16]
    safe = "".join(ch for ch in path_key if ch.isalnum() or ch in {"-", "_"}).strip("-_")[:48] or "file"
    return f"{safe}-{digest}.html"


def render_text_preview(lines: list[str], *, fallback: str) -> str:
    if not lines:
        return f"<p>{html.escape(fallback)}</p>"
    body = "".join(f"<li><span>{index}</span><code>{html.escape(line)}</code></li>" for index, line in enumerate(lines[:120], start=1))
    if len(lines) > 120:
        body += f"<li><em>... {len(lines) - 120} weitere Zeilen</em></li>"
    return f"<ol class='preview'>{body}</ol>"


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
        f"<div class='hunk-meta'>{html.escape(hunk.get('tag', 'change'))}: "
        f"vorher {hunk.get('before_start', 0)}-{hunk.get('before_end', 0)} | "
        f"nachher {hunk.get('after_start', 0)}-{hunk.get('after_end', 0)}</div>"
        "<div class='hunk-columns'>"
        f"<div><h4>Entfernt</h4><ul class='removed'>{''.join(removed) or '<li><em>Keine entfernten Zeilen</em></li>'}</ul></div>"
        f"<div><h4>Hinzugefuegt</h4><ul class='added'>{''.join(added) or '<li><em>Keine neuen Zeilen</em></li>'}</ul></div>"
        "</div></div>"
    )


def render_detail_page(event: dict[str, Any], item: dict[str, Any], *, previous_entry: dict[str, Any] | None, current_entry: dict[str, Any] | None) -> str:
    hunks_html = "".join(render_diff_hunk(hunk) for hunk in item.get("hunks", [])) or "<p>Keine Zeilen-Hunks verfuegbar.</p>"
    before_lines = previous_entry.get("lines", []) if previous_entry else []
    after_lines = current_entry.get("lines", []) if current_entry else []
    severity = html.escape(str(item.get("risk_severity", "low")))
    reasons = "".join(f"<li>{html.escape(reason)}</li>" for reason in item.get("risk_reasons", [])) or "<li>Keine Gruende dokumentiert.</li>"
    css = """
body { font-family: Segoe UI, Arial, sans-serif; background: #0f172a; color: #e5e7eb; margin: 0; }
.container { max-width: 1200px; margin: 0 auto; padding: 28px; }
.panel { background: rgba(15, 23, 42, 0.82); border: 1px solid rgba(148,163,184,.18); border-radius: 18px; padding: 18px; margin-bottom: 18px; }
.severity-low { border-left: 6px solid #10b981; }
.severity-medium { border-left: 6px solid #f59e0b; }
.severity-high { border-left: 6px solid #fb7185; }
.severity-critical { border-left: 6px solid #ef4444; }
.meta { color: #94a3b8; margin-top: 8px; }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.preview, .removed, .added { padding-left: 18px; }
.preview li, .removed li, .added li { margin-bottom: 6px; }
.preview span, .ln { display: inline-block; min-width: 42px; color: #94a3b8; font-family: Consolas, monospace; }
code { white-space: pre-wrap; font-family: Consolas, monospace; }
.hunk-columns { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
@media (max-width: 960px) { .grid, .hunk-columns { grid-template-columns: 1fr; } }
"""
    return (
        "<!DOCTYPE html><html lang='de'><head><meta charset='utf-8'>"
        f"<title>{html.escape(str(item.get('path', 'Datei')))}</title>"
        f"<style>{css}</style></head><body><div class='container'>"
        f"<div class='panel severity-{severity}'><h1>{html.escape(str(item.get('path', '')))}</h1>"
        f"<p class='meta'>{fmt_ts(event.get('timestamp'))} | Risiko {item.get('risk_score', 0)} | {html.escape(str(item.get('kind', 'file')))}</p>"
        f"<p><strong>Absolute Datei:</strong> {html.escape(str(item.get('absolute_path', '')))}</p>"
        f"<p><strong>Publisher:</strong> {html.escape(str(item.get('publisher', '')) or 'unbekannt')} | <strong>Signatur:</strong> {html.escape(str(item.get('signature_status', '')) or 'n/a')}</p>"
        f"<p><strong>Command:</strong> {html.escape(str(item.get('command', '')) or 'n/a')}</p>"
        f"<h2>Bewertung</h2><ul>{reasons}</ul>"
        "<p><a href='../system_guard_report.html'>Zurueck zum Hauptreport</a></p></div>"
        "<div class='panel'><h2>Diff</h2>"
        f"{hunks_html}</div>"
        "<div class='grid'>"
        f"<div class='panel'><h2>Vorher</h2>{render_text_preview(before_lines, fallback='Kein vorheriger Textinhalt verfuegbar.')}</div>"
        f"<div class='panel'><h2>Nachher</h2>{render_text_preview(after_lines, fallback='Kein aktueller Textinhalt verfuegbar.')}</div>"
        "</div></div></body></html>"
    )


def attach_detail_pages(state_dir: pathlib.Path, event: dict[str, Any], previous_files: dict[str, Any], current_files: dict[str, Any]) -> dict[str, Any]:
    detail_dir = state_dir / "files"
    detail_dir.mkdir(parents=True, exist_ok=True)
    for category in ("modified", "created", "deleted"):
        for item in event.get(category, []):
            path_key = f"{item.get('scope_name', '')}::{item.get('relative_path', '')}"
            page_name = detail_page_name(str(event.get("id", "event")), path_key)
            previous_entry = previous_files.get(path_key)
            current_entry = current_files.get(path_key)
            detail_path = detail_dir / page_name
            detail_path.write_text(
                render_detail_page(event, item, previous_entry=previous_entry, current_entry=current_entry),
                encoding="utf-8",
            )
            item["detail_page"] = f"files/{page_name}"
    return event


def quarantine_mode() -> str:
    mode = str(os.environ.get("NOVA_SYSTEM_GUARD_ACTION") or os.environ.get("NOVA_SYSTEM_GUARD_QUARANTINE") or "off").strip().lower()
    if mode in {"1", "on", "true", "yes"}:
        return "high"
    if mode in {"all", "high", "critical", "off"}:
        return mode
    return "off"


def should_quarantine_item(item: dict[str, Any]) -> bool:
    mode = quarantine_mode()
    if mode == "off":
        return False
    if item.get("kind") not in {"driver", "library", "executable", "script"}:
        return False
    score = int(item.get("risk_score", 0))
    if mode == "critical":
        return score >= 85
    if mode == "high":
        return score >= 65
    return score >= 1


def apply_quarantine_actions(state_dir: pathlib.Path, event: dict[str, Any]) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    quarantine_dir = state_dir / "quarantine"
    for item in event.get("created", []):
        absolute_path = str(item.get("absolute_path") or "").strip()
        if not absolute_path or not should_quarantine_item(item):
            continue
        source = pathlib.Path(absolute_path)
        if not source.exists() or not source.is_file():
            continue
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        suffix = source.suffix or ".bin"
        target = quarantine_dir / f"{hashlib.sha1((absolute_path + str(time.time())).encode('utf-8')).hexdigest()[:12]}-{source.name}{suffix if source.suffix.lower() != suffix.lower() else ''}"
        try:
            shutil.move(str(source), str(target))
            action = {
                "type": "quarantine",
                "source_path": str(source),
                "target_path": str(target),
                "reason": f"new {item.get('kind')} with risk score {item.get('risk_score', 0)}",
                "success": True,
            }
            item["quarantine"] = action
            actions.append(action)
        except Exception as exc:
            action = {
                "type": "quarantine",
                "source_path": str(source),
                "target_path": str(target),
                "reason": str(exc).strip() or exc.__class__.__name__,
                "success": False,
            }
            item["quarantine"] = action
            actions.append(action)
    event["actions"] = actions
    return event


def render_item_list(items: list[dict[str, Any]]) -> str:
    if not items:
        return "<li>Keine Dateien</li>"
    rows = []
    for item in items:
        link = (
            f" <a href='{html.escape(str(item.get('detail_page', '')))}' target='_blank' rel='noopener'>Detailseite</a>"
            if item.get("detail_page")
            else ""
        )
        rows.append(
            f"<li><strong>{html.escape(str(item.get('path', '')))}</strong>{link}<br>"
            f"<span>{html.escape(str(item.get('absolute_path', '')))} | Risiko {item.get('risk_score', 0)} | {html.escape(str(item.get('kind', 'file')))}"
            f"{' | Signatur: ' + html.escape(str(item.get('signature_status', ''))) if item.get('signature_status') else ''}"
            f"{' | Publisher: ' + html.escape(str(item.get('publisher', ''))) if item.get('publisher') else ''}"
            f"{' | Command: ' + html.escape(str(item.get('command', ''))) if item.get('command') else ''}"
            "</span></li>"
        )
    return "".join(rows)


def render_html(snapshot: dict[str, Any], history_events: list[dict[str, Any]], analysis: dict[str, Any], current_event: dict[str, Any], runtime: dict[str, Any]) -> str:
    current_review = current_event.get("review", {})
    summary_cards = [
        ("Watch-Modus", str(runtime.get("watch_mode", "poll"))),
        ("Scopes", str(len(snapshot.get("scope_counts", {})))),
        ("Ueberwachte Dateien", str(snapshot.get("file_count", 0))),
        ("Kritische Dateien", str(len(analysis.get("critical_paths", [])))),
        ("Historie", str(len(history_events))),
    ]
    cards_html = "".join(
        f"<div class='card'><div class='label'>{html.escape(label)}</div><div class='value'>{html.escape(value)}</div></div>"
        for label, value in summary_cards
    )
    scope_rows = "".join(
        f"<tr><td>{html.escape(item['title'])}</td><td>{html.escape(item['priority'])}</td><td>{item['file_count']}</td><td>{'ja' if item['exists'] else 'nein'}</td><td>{html.escape(item['path'])}</td></tr>"
        for item in analysis.get("scope_rows", [])
    ) or "<tr><td colspan='5'>Keine Scopes konfiguriert.</td></tr>"
    kind_rows = "".join(
        f"<tr><td>{html.escape(item['kind'])}</td><td>{item['file_count']}</td></tr>"
        for item in analysis.get("kind_ranking", [])
    ) or "<tr><td colspan='2'>Keine Daten</td></tr>"
    critical_rows = "".join(
        f"<tr><td>{html.escape(str(item['path']))}</td><td>{html.escape(str(item['kind']))}</td><td>{item['risk_score']}</td><td>{html.escape(str(item['absolute_path']))}</td></tr>"
        for item in analysis.get("critical_paths", [])
    ) or "<tr><td colspan='4'>Keine Hochrisiko-Dateien in der aktuellen Sicht.</td></tr>"
    unsigned_rows = "".join(
        f"<tr><td>{html.escape(str(item['path']))}</td><td>{html.escape(str(item.get('signature_status') or 'unknown'))}</td><td>{html.escape(str(item.get('publisher') or ''))}</td><td>{item['risk_score']}</td></tr>"
        for item in analysis.get("unsigned_paths", [])
    ) or "<tr><td colspan='4'>Keine unsignierten oder nicht vertrauenswuerdigen Dateien.</td></tr>"
    warnings_html = "".join(f"<li>{html.escape(text)}</li>" for text in analysis.get("warnings", [])) or "<li>Keine Warnungen.</li>"
    action_rows = "".join(
        f"<li>{html.escape(str(item.get('type')))} | {html.escape(str(item.get('source_path')))} -> {html.escape(str(item.get('target_path')))} | {'ok' if item.get('success') else 'failed'} | {html.escape(str(item.get('reason') or ''))}</li>"
        for item in current_event.get("actions", [])
    ) or "<li>Keine aktiven Schutzaktionen.</li>"

    event_blocks: list[str] = []
    for event in reversed(history_events[-20:]):
        review = event.get("review", {})
        modified_blocks = []
        for item in event.get("modified", []):
            hunks_html = "".join(render_diff_hunk(hunk) for hunk in item.get("hunks", [])) or "<p>Keine Text-Hunks verfuegbar.</p>"
            detail_link = (
                f" <a href='{html.escape(str(item.get('detail_page', '')))}' target='_blank' rel='noopener'>Detailseite</a>"
                if item.get("detail_page")
                else ""
            )
            modified_blocks.append(
                "<details class='file-change' open>"
                f"<summary>{html.escape(str(item.get('path', '')))}{detail_link} <span>{item.get('risk_severity', 'low')} | +{item.get('added_lines', 0)} / -{item.get('removed_lines', 0)}</span></summary>"
                f"<div class='file-meta'>{html.escape(str(item.get('absolute_path', '')))}</div>"
                f"{hunks_html}</details>"
            )
        event_blocks.append(
            "<section class='event'>"
            f"<header><h3>{html.escape(str(event.get('summary', '')))}</h3><p>{fmt_ts(event.get('timestamp'))} | {html.escape(str(event.get('kind', 'scan')))}</p></header>"
            f"<div class='review severity-{html.escape(str(review.get('severity', 'low')))}'><strong>{html.escape(str(review.get('headline', 'Review')))}</strong><p>{html.escape(str(review.get('summary', '')))}</p></div>"
            f"<div class='panel'><h4>Aktionen</h4><ul>{''.join(f'<li>{html.escape(str(action.get('type')))} | {html.escape(str(action.get('source_path')))} -> {html.escape(str(action.get('target_path')))} | {'ok' if action.get('success') else 'failed'}</li>' for action in event.get('actions', [])) or '<li>Keine Aktionen.</li>'}</ul></div>"
            "<div class='event-grid'>"
            f"<div><h4>Neu</h4><ul>{render_item_list(event.get('created', []))}</ul></div>"
            f"<div><h4>Entfernt</h4><ul>{render_item_list(event.get('deleted', []))}</ul></div>"
            "</div>"
            f"<div class='modified-block'><h4>Geaendert</h4>{''.join(modified_blocks) or '<p>Keine geaenderten Dateien.</p>'}</div>"
            "</section>"
        )

    css = """
body { font-family: Segoe UI, Arial, sans-serif; background: linear-gradient(180deg, #140b0c, #1a1013 45%, #09090b); color: #f8fafc; margin: 0; }
a { color: #93c5fd; }
.container { max-width: 1500px; margin: 0 auto; padding: 32px 28px 80px; }
.hero { display: flex; justify-content: space-between; gap: 24px; align-items: end; margin-bottom: 24px; }
.hero h1 { margin: 0 0 8px; font-size: 40px; }
.hero p { margin: 0; color: #cbd5e1; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin: 24px 0 28px; }
.card, .panel, .event, .review-card { background: rgba(17, 24, 39, 0.72); border: 1px solid rgba(148, 163, 184, 0.14); border-radius: 18px; padding: 18px; box-shadow: 0 18px 48px rgba(0,0,0,.24); }
.label { font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: #94a3b8; margin-bottom: 8px; }
.value { font-size: 22px; font-weight: 700; }
.grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; margin-bottom: 22px; }
.review-card h2, .panel h2, .event h3 { margin-top: 0; }
.review { margin: 10px 0 16px; padding: 12px 14px; border-radius: 14px; }
.severity-low { border-color: rgba(16,185,129,.32); background: rgba(16,185,129,.12); }
.severity-medium { border-color: rgba(245,158,11,.36); background: rgba(245,158,11,.12); }
.severity-high { border-color: rgba(251,113,133,.38); background: rgba(251,113,133,.12); }
.severity-critical { border-color: rgba(239,68,68,.44); background: rgba(239,68,68,.14); }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 10px 12px; border-bottom: 1px solid rgba(148,163,184,.12); text-align: left; vertical-align: top; }
th { color: #fda4af; font-size: 13px; letter-spacing: .06em; text-transform: uppercase; }
ul { padding-left: 18px; }
.event { margin-bottom: 18px; }
.event header p, .file-meta { color: #94a3b8; }
.event-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.file-change { background: rgba(2, 6, 23, .48); border: 1px solid rgba(248,113,113,.18); border-radius: 14px; padding: 12px 14px; margin-bottom: 14px; }
.file-change summary { cursor: pointer; font-weight: 700; }
.file-change summary span { color: #fecaca; margin-left: 8px; font-weight: 500; }
.modified-block h4 { margin-bottom: 8px; }
.hunk { border-top: 1px solid rgba(148,163,184,.12); padding-top: 12px; margin-top: 12px; }
.hunk-meta { color: #fbbf24; margin-bottom: 10px; }
.hunk-columns { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.removed, .added { list-style: none; padding: 0; margin: 0; }
.removed li, .added li { display: grid; grid-template-columns: 64px 1fr; gap: 10px; padding: 6px 8px; border-radius: 10px; margin-bottom: 6px; }
.removed li { background: rgba(127,29,29,.42); }
.added li { background: rgba(20,83,45,.42); }
.ln { color: #f8fafc; opacity: .75; font-family: Consolas, monospace; }
code { white-space: pre-wrap; font-family: Consolas, monospace; color: #f8fafc; }
.footer { margin-top: 28px; color: #94a3b8; font-size: 13px; }
@media (max-width: 1100px) { .grid, .event-grid, .hunk-columns { grid-template-columns: 1fr; } .hero { flex-direction: column; align-items: start; } }
"""
    return (
        "<!DOCTYPE html><html lang='de'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<meta http-equiv='refresh' content='3'>"
        "<title>Nova System Guard</title>"
        f"<style>{css}</style></head><body><div class='container'>"
        "<div class='hero'><div><h1>Nova System Guard</h1>"
        "<p>Gezielte Host-Integrity-Ueberwachung fuer Windows-Persistenz, Temp-Ausfuehrung und Projektintegritaet.</p></div>"
        f"<div><p><strong>Letzte Aktualisierung:</strong> {fmt_ts(snapshot.get('generated_at'))}</p>"
        f"<p><strong>Review:</strong> {html.escape(str(current_review.get('severity', 'low')))} | Score {current_review.get('score', 0)}</p></div></div>"
        f"<section class='cards'>{cards_html}</section>"
        f"<section class='review-card severity-{html.escape(str(current_review.get('severity', 'low')))}'><h2>{html.escape(str(current_review.get('headline', 'Review')))}</h2>"
        f"<p>{html.escape(str(current_review.get('summary', '')))}</p><ul>{''.join(f'<li>{html.escape(text)}</li>' for text in current_review.get('findings', [])) or '<li>Keine Findings.</li>'}</ul>"
        f"<h3>Empfehlungen</h3><ul>{''.join(f'<li>{html.escape(text)}</li>' for text in current_review.get('recommendations', [])) or '<li>Keine Empfehlungen.</li>'}</ul></section>"
        "<section class='grid'>"
        f"<div class='panel'><h2>Aktueller Status</h2><p>{html.escape(str(current_event.get('summary', 'Keine Aenderung erkannt.')))}</p></div>"
        f"<div class='panel'><h2>Warnungen</h2><ul>{warnings_html}</ul></div>"
        f"<div class='panel'><h2>Watch-Status</h2><p>{html.escape(str(runtime.get('watch_mode', 'poll')))} | {html.escape(str(runtime.get('watch_reason', '')))}</p><h3>Schutzaktionen</h3><ul>{action_rows}</ul></div>"
        "</section>"
        "<section class='grid'>"
        f"<div class='panel'><h2>Scopes</h2><table><thead><tr><th>Scope</th><th>Prioritaet</th><th>Dateien</th><th>Existiert</th><th>Pfad</th></tr></thead><tbody>{scope_rows}</tbody></table></div>"
        f"<div class='panel'><h2>Dateiklassen</h2><table><thead><tr><th>Klasse</th><th>Dateien</th></tr></thead><tbody>{kind_rows}</tbody></table></div>"
        f"<div class='panel'><h2>Aktive Hochrisiko-Dateien</h2><table><thead><tr><th>Datei</th><th>Klasse</th><th>Risiko</th><th>Pfad</th></tr></thead><tbody>{critical_rows}</tbody></table></div>"
        "</section>"
        f"<section class='panel'><h2>Signatur- und Publisher-Pruefung</h2><table><thead><tr><th>Datei</th><th>Status</th><th>Publisher</th><th>Risiko</th></tr></thead><tbody>{unsigned_rows}</tbody></table></section>"
        f"<section class='panel'><h2>Ereignishistorie</h2>{''.join(event_blocks) or '<p>Noch keine Ereignisse.</p>'}</section>"
        f"<div class='footer'>Generiert von Nova System Guard v{VERSION} | Statusdatei: {STATE_DIR_NAME}/latest_status.json</div>"
        "</div></body></html>"
    )


def resolve_watch_mode() -> dict[str, Any]:
    requested = str(os.environ.get("NOVA_SYSTEM_GUARD_WATCH_MODE") or "auto").strip().lower()
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


def open_report_once(report_path: pathlib.Path, flag_path: pathlib.Path) -> None:
    if flag_path.exists() or not env_flag("NOVA_SYSTEM_GUARD_OPEN", True):
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


def create_watch_queue(scopes: list[dict[str, Any]]) -> tuple[Any, queue.Queue[str]] | tuple[None, queue.Queue[str]]:
    event_queue: queue.Queue[str] = queue.Queue()
    if not WATCHDOG_AVAILABLE:
        return None, event_queue

    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    existing_scopes = [scope for scope in scopes if pathlib.Path(scope["path"]).exists()]
    if not existing_scopes:
        return None, event_queue

    class GuardHandler(FileSystemEventHandler):
        def _record(self, path_text: str) -> None:
            path = pathlib.Path(path_text).resolve(strict=False)
            for scope in existing_scopes:
                scope_root = pathlib.Path(scope["path"]).resolve(strict=False)
                try:
                    rel = path.relative_to(scope_root)
                except Exception:
                    continue
                if should_skip_path(scope, rel):
                    return
                event_queue.put(str(path))
                return

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
    handler = GuardHandler()
    for scope in existing_scopes:
        observer.schedule(handler, str(scope["path"]), recursive=bool(scope.get("recurse", True)))
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


def monitor_once(root: pathlib.Path, state_dir: pathlib.Path, scopes: list[dict[str, Any]], *, runtime: dict[str, Any]) -> dict[str, Any]:
    snapshot_path = state_dir / "snapshot.json"
    history_path = state_dir / "history.json"
    analysis_path = state_dir / "system_guard_analysis.json"
    report_path = state_dir / "system_guard_report.html"
    status_path = state_dir / "latest_status.json"
    browser_flag = state_dir / ".browser_opened"

    previous = load_json(snapshot_path, {})
    history_payload = load_json(history_path, {"events": []})
    current = scan_targets(scopes)
    event, changed = diff_snapshots(previous, current)
    event = attach_detail_pages(state_dir, event, previous.get("files", {}), current.get("files", {}))
    if changed:
        event = apply_quarantine_actions(state_dir, event)
    events = list(history_payload.get("events", []))
    if changed:
        events.append(event)
        events = events[-MAX_HISTORY:]
    analysis = build_analysis(events, current)
    if changed and events:
        events[-1]["review"] = event.get("review", {})
    report_path.write_text(render_html(current, events, analysis, event, runtime), encoding="utf-8")
    save_json(snapshot_path, current)
    save_json(history_path, {"generated_at": current.get("generated_at"), "events": events})
    save_json(analysis_path, analysis)
    payload = {
        "generated_at": current.get("generated_at"),
        "changed": changed,
        "event": event,
        "review": event.get("review", {}),
        "runtime": runtime,
        "tracked_files": current.get("file_count", 0),
        "scope_count": len(scopes),
        "report_path": str(report_path),
        "analysis_path": str(analysis_path),
        "actions": event.get("actions", []),
        "status_line": event.get("summary", "Keine sicherheitsrelevante Aenderung erkannt."),
    }
    save_json(status_path, payload)
    open_report_once(report_path, browser_flag)
    return payload


def main() -> dict[str, Any]:
    helper_path = pathlib.Path(__file__).resolve()
    root = pathlib.Path(os.environ.get("NOVA_SYSTEM_GUARD_ROOT") or helper_path.parent.parent).resolve()
    state_dir = root / STATE_DIR_NAME
    state_dir.mkdir(parents=True, exist_ok=True)
    interval = float(os.environ.get("NOVA_SYSTEM_GUARD_INTERVAL", "2"))
    debounce_seconds = float(os.environ.get("NOVA_SYSTEM_GUARD_DEBOUNCE", "1.0"))
    oneshot = env_flag("NOVA_SYSTEM_GUARD_ONESHOT", False)
    scopes = resolve_scope_specs(root)
    watch_config = resolve_watch_mode()
    runtime = {
        "watch_mode": watch_config["mode"],
        "watch_requested": watch_config["requested"],
        "watch_reason": watch_config.get("reason", ""),
        "watchdog_available": WATCHDOG_AVAILABLE,
        "scope_titles": [scope["title"] for scope in scopes],
    }
    latest: dict[str, Any] | None = None

    if oneshot:
        return monitor_once(root, state_dir, scopes, runtime=runtime)

    if watch_config["mode"] == "watchdog":
        observer, event_queue = create_watch_queue(scopes)
        if observer is not None:
            try:
                latest = monitor_once(root, state_dir, scopes, runtime=runtime)
                while True:
                    batch = wait_for_watch_batch(event_queue, debounce_seconds=debounce_seconds)
                    runtime["last_trigger_paths"] = batch[:30]
                    latest = monitor_once(root, state_dir, scopes, runtime=runtime)
            except KeyboardInterrupt:
                return latest or {"changed": False, "status_line": "System Guard beendet.", "runtime": runtime}
            finally:
                observer.stop()
                observer.join(timeout=5)

    while True:
        latest = monitor_once(root, state_dir, scopes, runtime=runtime)
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            return latest or {"changed": False, "status_line": "System Guard beendet.", "runtime": runtime}


if __name__ == "__main__":
    main()
