from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


_MODULE_CACHE: dict[str, ModuleType] = {}


def _atheria_root() -> Path:
    return Path(__file__).resolve().parents[2] / "Atheria"


def load_atheria_script(script_name: str, module_key: str) -> ModuleType:
    cached = _MODULE_CACHE.get(module_key)
    if cached is not None:
        return cached

    target = _atheria_root() / script_name
    if not target.exists():
        raise FileNotFoundError(target)

    spec = importlib.util.spec_from_file_location(module_key, target)
    if spec is None or spec.loader is None:
        raise ImportError(f"unable to load Atheria script: {target}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_key] = module
    spec.loader.exec_module(module)
    _MODULE_CACHE[module_key] = module
    return module


def load_market_future_projection() -> ModuleType:
    return load_atheria_script("atheria_market_future_projection.py", "nova_atheria_market_future_projection")


def load_information_einstein_like() -> ModuleType:
    return load_atheria_script("atheria_information_einstein_like.py", "nova_atheria_information_einstein_like")


def load_aion_chronik() -> ModuleType:
    return load_atheria_script("aion_chronik.py", "nova_atheria_aion_chronik")
