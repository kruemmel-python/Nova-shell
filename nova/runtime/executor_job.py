from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from nova.mesh.protocol import ExecutorResult, ExecutorTask

from .executors import execute_backend_task


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one isolated Nova executor job")
    parser.add_argument("--backend", required=True)
    parser.add_argument("--task-file", required=True)
    parser.add_argument("--result-file", required=True)
    args = parser.parse_args()

    task_path = Path(args.task_file)
    result_path = Path(args.result_file)
    payload = json.loads(task_path.read_text(encoding="utf-8"))
    task = ExecutorTask.from_dict(payload)
    metadata = dict(task.metadata)
    metadata.setdefault("stream_mode", "tee")
    task.metadata = metadata

    try:
        result = execute_backend_task(str(args.backend), task)
    except Exception as exc:
        result = ExecutorResult(request_id=task.request_id, status="error", error=str(exc), metadata={"backend": str(args.backend)})
    result_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False), encoding="utf-8")
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
