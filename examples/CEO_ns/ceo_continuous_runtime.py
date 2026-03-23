from __future__ import annotations

import json
import os
import time
from pathlib import Path

from nova.runtime.runtime import NovaRuntime


ROOT = Path(__file__).resolve().parent
PROGRAM_PATH = ROOT / "CEO_Lifecycle.ns"
RUNTIME_DIR = ROOT / ".nova_ceo"


def run_cycle(cycle_index: int) -> dict[str, object]:
    runtime = NovaRuntime()
    try:
        source = PROGRAM_PATH.read_text(encoding="utf-8")
        runtime.load(source, source_name=str(PROGRAM_PATH), base_path=ROOT)
        result = runtime.emit("ceo.tick", {"source": "timer", "cycle": cycle_index})
        payload = result.to_dict()
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        status_path = RUNTIME_DIR / "continuous_status.json"
        status_payload = {
            "cycle": cycle_index,
            "timestamp": time.time(),
            "source_name": payload.get("source_name"),
            "flow_count": len(payload.get("flows") or []),
            "event_count": len(payload.get("events") or []),
            "outputs": dict((payload.get("context") or {}).get("outputs") or {}),
        }
        status_path.write_text(json.dumps(status_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return status_payload
    finally:
        runtime.close()


def main() -> int:
    oneshot = str(os.environ.get("NOVA_CEO_ONESHOT") or "0").lower() in {"1", "true", "yes", "on"}
    interval = max(5.0, float(os.environ.get("NOVA_CEO_INTERVAL") or 60.0))
    cycle = 0
    while True:
        cycle += 1
        payload = run_cycle(cycle)
        print(json.dumps(payload, ensure_ascii=False))
        if oneshot:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
