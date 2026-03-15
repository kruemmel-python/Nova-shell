from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from nova.mesh.protocol import ExecutorTask


@dataclass(slots=True)
class ActiveJob:
    request_id: str
    task_file: Path
    result_file: Path
    process: subprocess.Popen[str]
    stdout_chunks: list[str] = field(default_factory=list)
    stderr_chunks: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    status: str = "running"
    returncode: int | None = None

    def snapshot(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "request_id": self.request_id,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "returncode": self.returncode,
            "stdout_chunks": list(self.stdout_chunks),
            "stderr_chunks": list(self.stderr_chunks),
        }
        if self.result_file.exists():
            try:
                payload["result"] = json.loads(self.result_file.read_text(encoding="utf-8"))
            except Exception:
                payload["result"] = None
        else:
            payload["result"] = None
        return payload


class ExecutorDaemon:
    def __init__(self, backend: str, *, host: str, port: int, auth_token: str | None, base_path: Path, endpoint_file: Path) -> None:
        self.backend = backend
        self.host = host
        self.port = int(port)
        self.auth_token = auth_token
        self.base_path = base_path
        self.endpoint_file = endpoint_file
        self.work_dir = (base_path / ".nova" / "executor-jobs" / backend).resolve(strict=False)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, ActiveJob] = {}
        self._lock = threading.RLock()
        self._server: ThreadingHTTPServer | None = None

    def _authorized(self, headers: Any) -> bool:
        if not self.auth_token:
            return True
        return str(headers.get("Authorization") or "") == f"Bearer {self.auth_token}"

    def start(self) -> None:
        daemon = self

        class Handler(BaseHTTPRequestHandler):
            def _json_body(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length > 0 else b"{}"
                try:
                    payload = json.loads(body.decode("utf-8"))
                    return payload if isinstance(payload, dict) else {}
                except Exception:
                    return {}

            def _write_json(self, payload: Any, status: int = 200) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                if not daemon._authorized(self.headers):
                    self._write_json({"error": "unauthorized"}, status=401)
                    return
                parsed = urlparse(self.path)
                if parsed.path == "/health":
                    self._write_json({"status": "ok", "backend": daemon.backend, "active_jobs": len(daemon._jobs), "pid": os.getpid()})
                    return
                if parsed.path.startswith("/jobs/"):
                    request_id = parsed.path.split("/")[-1]
                    self._write_json(daemon.job_status(request_id))
                    return
                if parsed.path.startswith("/stream/"):
                    request_id = parsed.path.split("/")[-1]
                    self._write_json(daemon.stream(request_id))
                    return
                self._write_json({"error": "not found"}, status=404)

            def do_POST(self) -> None:  # noqa: N802
                if not daemon._authorized(self.headers):
                    self._write_json({"error": "unauthorized"}, status=401)
                    return
                payload = self._json_body()
                if self.path == "/execute":
                    self._write_json(daemon.execute(payload))
                    return
                if self.path == "/execute/async":
                    self._write_json(daemon.execute_async(payload))
                    return
                if self.path.startswith("/cancel/"):
                    request_id = self.path.split("/")[-1]
                    self._write_json(daemon.cancel(request_id))
                    return
                if self.path == "/shutdown":
                    self._write_json({"status": "stopping"})
                    threading.Thread(target=daemon.stop, daemon=True).start()
                    return
                self._write_json({"error": "not found"}, status=404)

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
                return

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self.port = int(self._server.server_address[1])
        endpoint_payload = {"endpoint": f"http://{self.host}:{self.port}", "host": self.host, "port": self.port}
        self.endpoint_file.write_text(json.dumps(endpoint_payload, ensure_ascii=False), encoding="utf-8")
        self._server.serve_forever()

    def stop(self) -> None:
        for request_id in list(self._jobs):
            self.cancel(request_id)
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        task = ExecutorTask.from_dict(payload)
        timeout_seconds = float(task.metadata.get("timeout_seconds") or 30.0)
        job = self._spawn_job(task)
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            snapshot = self.job_status(task.request_id)
            if snapshot["status"] != "running":
                result = snapshot.get("result")
                if isinstance(result, dict):
                    return result
                return {"request_id": task.request_id, "status": snapshot["status"], "error": "job failed without result"}
            time.sleep(0.05)
        self.cancel(task.request_id, reason="timeout")
        snapshot = self.job_status(task.request_id)
        result = snapshot.get("result")
        if isinstance(result, dict):
            return result
        return {"request_id": task.request_id, "status": "error", "error": "execution timed out", "metadata": {"backend": self.backend}}

    def execute_async(self, payload: dict[str, Any]) -> dict[str, Any]:
        task = ExecutorTask.from_dict(payload)
        job = self._spawn_job(task)
        return {"request_id": task.request_id, "status": job.status, "backend": self.backend}

    def stream(self, request_id: str) -> dict[str, Any]:
        return self.job_status(request_id)

    def cancel(self, request_id: str, *, reason: str = "canceled") -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(request_id)
            if job is None:
                return {"request_id": request_id, "canceled": False}
            if job.process.poll() is None:
                self._terminate_process(job.process)
            job.status = "canceled"
            job.returncode = job.process.poll()
            job.completed_at = time.time()
            if not job.result_file.exists():
                job.result_file.write_text(
                    json.dumps(
                        {
                            "request_id": request_id,
                            "status": "error",
                            "error": reason,
                            "metadata": {"backend": self.backend},
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
        return {"request_id": request_id, "canceled": True, "reason": reason}

    def job_status(self, request_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(request_id)
            if job is None:
                return {"request_id": request_id, "status": "unknown"}
            if job.status == "running" and job.process.poll() is not None:
                job.returncode = job.process.returncode
                job.completed_at = time.time()
                job.status = "ok" if job.process.returncode == 0 else ("error" if job.status != "canceled" else job.status)
            return job.snapshot()

    def _spawn_job(self, task: ExecutorTask) -> ActiveJob:
        with self._lock:
            existing = self._jobs.get(task.request_id)
            if existing is not None and existing.status == "running":
                return existing
            task_file = Path(tempfile.mkstemp(prefix=f"{self.backend}-task-", suffix=".json", dir=str(self.work_dir))[1])
            result_file = Path(tempfile.mkstemp(prefix=f"{self.backend}-result-", suffix=".json", dir=str(self.work_dir))[1])
            task.metadata = {**dict(task.metadata), "stream_mode": "tee"}
            task_file.write_text(json.dumps(task.to_dict(), ensure_ascii=False), encoding="utf-8")
            process = self._start_process(task_file, result_file)
            job = ActiveJob(request_id=task.request_id, task_file=task_file, result_file=result_file, process=process)
            self._jobs[task.request_id] = job
            threading.Thread(target=self._drain_stream, args=(job, process.stdout, job.stdout_chunks), daemon=True).start()
            threading.Thread(target=self._drain_stream, args=(job, process.stderr, job.stderr_chunks), daemon=True).start()
            return job

    def _start_process(self, task_file: Path, result_file: Path) -> subprocess.Popen[str]:
        kwargs: dict[str, Any] = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "stdin": subprocess.DEVNULL,
            "text": True,
            "cwd": str(self.base_path),
            "env": self._job_env(),
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "nova.runtime.executor_job",
                "--backend",
                self.backend,
                "--task-file",
                str(task_file),
                "--result-file",
                str(result_file),
            ],
            **kwargs,
        )

    def _job_env(self) -> dict[str, str]:
        env = dict(os.environ)
        project_root = str(Path(__file__).resolve().parents[2])
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = project_root if not existing else project_root + os.pathsep + existing
        return env

    def _drain_stream(self, job: ActiveJob, stream: Any, target: list[str]) -> None:
        if stream is None:
            return
        for line in iter(stream.readline, ""):
            with self._lock:
                target.append(line.rstrip("\n"))
        stream.close()

    def _terminate_process(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, text=True)
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            try:
                process.wait(timeout=2.0)
            except Exception:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)


def main() -> int:
    parser = argparse.ArgumentParser(description="Nova isolated executor daemon")
    parser.add_argument("--backend", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default="0")
    parser.add_argument("--auth-token", default=None)
    parser.add_argument("--endpoint-file", required=True)
    parser.add_argument("--base-path", required=True)
    args = parser.parse_args()

    daemon = ExecutorDaemon(
        str(args.backend),
        host=str(args.host),
        port=int(args.port),
        auth_token=str(args.auth_token) if args.auth_token else None,
        base_path=Path(args.base_path),
        endpoint_file=Path(args.endpoint_file),
    )
    daemon.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
