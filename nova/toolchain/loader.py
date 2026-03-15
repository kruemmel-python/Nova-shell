from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nova.parser.ast import ImportDeclaration, NovaAST, TopLevelDeclaration
from nova.parser.parser import NovaParser

from .registry import NovaPackageRegistry


@dataclass(slots=True)
class ResolvedNovaModule:
    module_id: str
    source_name: str
    path: str | None
    checksum: str
    ast: NovaAST
    imports: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class LoadedNovaProgram:
    ast: NovaAST
    modules: list[ResolvedNovaModule] = field(default_factory=list)
    lockfile: dict[str, Any] = field(default_factory=dict)


class NovaModuleLoader:
    """Resolve Nova imports into a merged AST and reproducible lockfile."""

    def __init__(self, parser: NovaParser | None = None, registry: NovaPackageRegistry | None = None) -> None:
        self.parser = parser or NovaParser()
        self.registry = registry

    def load(self, source: str, *, source_name: str = "<memory>", base_path: str | Path | None = None) -> LoadedNovaProgram:
        base = Path(base_path or Path.cwd()).resolve(strict=False)
        modules: dict[str, ResolvedNovaModule] = {}
        order: list[str] = []
        self._load_module(source, source_name=source_name, base_path=base, modules=modules, order=order)
        merged_declarations: list[TopLevelDeclaration] = []
        for module_id in order:
            module = modules[module_id]
            merged_declarations.extend(node for node in module.ast.declarations if not isinstance(node, ImportDeclaration))
        merged_source = "\n\n".join(module.ast.source for module in (modules[module_id] for module_id in order) if module.ast.source)
        lockfile = {
            "version": 1,
            "root": source_name,
            "base_path": str(base),
            "modules": [
                {
                    "module_id": module.module_id,
                    "source_name": module.source_name,
                    "path": module.path,
                    "checksum": module.checksum,
                    "imports": module.imports,
                }
                for module in (modules[module_id] for module_id in order)
            ],
        }
        return LoadedNovaProgram(
            ast=NovaAST(declarations=merged_declarations, source=merged_source or source),
            modules=[modules[module_id] for module_id in order],
            lockfile=lockfile,
        )

    def write_lockfile(self, lockfile: dict[str, Any], file_path: str | Path) -> dict[str, Any]:
        target = Path(file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(lockfile, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return {"file": str(target), "modules": len(lockfile.get("modules", []))}

    def _load_module(
        self,
        source: str,
        *,
        source_name: str,
        base_path: Path,
        modules: dict[str, ResolvedNovaModule],
        order: list[str],
    ) -> str:
        module_path = None
        if source_name != "<memory>":
            candidate = Path(source_name)
            if not candidate.is_absolute():
                candidate = (base_path / candidate).resolve(strict=False)
            if candidate.exists():
                module_path = candidate
                source_name = str(candidate)
        module_id = str(module_path or source_name)
        if module_id in modules:
            return module_id

        ast = self.parser.parse(source)
        imports: list[dict[str, Any]] = []
        placeholder = ResolvedNovaModule(
            module_id=module_id,
            source_name=source_name,
            path=str(module_path) if module_path is not None else None,
            checksum=self._checksum_bytes(source.encode("utf-8")) if module_path is None else self._checksum_path(module_path),
            ast=ast,
            imports=[],
        )
        modules[module_id] = placeholder

        for declaration in ast.imports():
            resolved = self._resolve_import(declaration.target, base_path=module_path.parent if module_path else base_path)
            imports.append(
                {
                    "target": declaration.target,
                    "alias": declaration.alias,
                    "kind": resolved.get("kind"),
                    "path": resolved.get("path"),
                    "package": resolved.get("package"),
                    "source_name": resolved.get("source_name"),
                }
            )
            if resolved["source"] is None:
                continue
            self._load_module(
                resolved["source"],
                source_name=resolved["source_name"],
                base_path=resolved["base_path"],
                modules=modules,
                order=order,
            )

        placeholder.imports = imports
        order.append(module_id)
        return module_id

    def _resolve_import(self, target: str, *, base_path: Path) -> dict[str, Any]:
        candidate = Path(target)
        looks_like_file = target.startswith(".") or target.startswith("/") or target.startswith("\\") or target.lower().endswith(".ns")
        if looks_like_file:
            if not candidate.is_absolute():
                candidate = (base_path / candidate).resolve(strict=False)
            if not candidate.exists():
                raise FileNotFoundError(f"import target not found: {candidate}")
            source = candidate.read_text(encoding="utf-8")
            return {
                "kind": "file",
                "path": str(candidate),
                "source": source,
                "source_name": str(candidate),
                "base_path": candidate.parent,
            }
        if self.registry is None:
            raise FileNotFoundError(f"registry import '{target}' cannot be resolved without a registry")
        package = self.registry.resolve(target)
        if package is None:
            raise FileNotFoundError(f"registry import '{target}' not found")
        entrypoint = Path(str(package["entrypoint"])).resolve(strict=False)
        if not entrypoint.exists():
            raise FileNotFoundError(f"registry entrypoint not found: {entrypoint}")
        return {
            "kind": "registry",
            "package": {"name": package["name"], "version": package["version"]},
            "path": str(entrypoint),
            "source": entrypoint.read_text(encoding="utf-8"),
            "source_name": str(entrypoint),
            "base_path": entrypoint.parent,
        }

    def _checksum_path(self, path: Path) -> str:
        return self._checksum_bytes(path.read_bytes()) if path.exists() else ""

    def _checksum_bytes(self, payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()
