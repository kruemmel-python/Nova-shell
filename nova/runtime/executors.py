from __future__ import annotations

import contextlib
import http.server
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nova.mesh.protocol import ExecutorResult, ExecutorTask


@dataclass(slots=True)
class ExecutorRecord:
    backend: str
    endpoint: str
    host: str
    port: int
    status: str = "starting"
    auth_token: str | None = None
    tls_profile: str | None = None
    request_count: int = 0
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "endpoint": self.endpoint,
            "host": self.host,
            "port": self.port,
            "status": self.status,
            "auth_token": self.auth_token,
            "tls_profile": self.tls_profile,
            "request_count": self.request_count,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "last_error": self.last_error,
            "metadata": self.metadata,
        }


class _StreamTee(io.TextIOBase):
    def __init__(self, target: Any) -> None:
        self._target = target
        self._buffer = io.StringIO()

    def write(self, data: str) -> int:
        if data:
            self._target.write(data)
            self._target.flush()
            self._buffer.write(data)
        return len(data)

    def flush(self) -> None:
        self._target.flush()

    def rendered(self) -> str:
        return self._buffer.getvalue()


class _PythonAdapter:
    def execute(self, task: ExecutorTask) -> ExecutorResult:
        code = task.command or (task.arguments[0] if task.arguments else "")
        globals_ns: dict[str, Any] = {"json": json, "os": os, "time": time, "_": task.pipeline_data}
        stream_mode = str(task.metadata.get("stream_mode") or "")
        stdout: io.StringIO | _StreamTee = _StreamTee(sys.stdout) if stream_mode == "tee" else io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                try:
                    value = eval(code, globals_ns, globals_ns)
                    if value is not None:
                        print(value)
                except SyntaxError:
                    exec(code, globals_ns, globals_ns)
                    value = globals_ns.get("_")
            return ExecutorResult(
                request_id=task.request_id,
                output=stdout.rendered() if isinstance(stdout, _StreamTee) else stdout.getvalue(),
                data=value,
                data_type=type(value).__name__,
                metadata={"backend": "py"},
            )
        except Exception as exc:
            return ExecutorResult(request_id=task.request_id, status="error", error=str(exc), metadata={"backend": "py"})


class _CppAdapter:
    def execute(self, task: ExecutorTask) -> ExecutorResult:
        compiler = next((candidate for candidate in ("clang++", "g++", "c++") if shutil.which(candidate)), None)
        if compiler is None:
            return ExecutorResult(request_id=task.request_id, status="error", error="no C++ compiler available", metadata={"backend": "cpp"})
        source = task.command or (task.arguments[0] if task.arguments else "")
        timeout_seconds = float(task.metadata.get("timeout_seconds") or 30.0)
        stream_mode = str(task.metadata.get("stream_mode") or "")
        stdin_text = ""
        if task.pipeline_data is not None:
            stdin_text = task.pipeline_data if isinstance(task.pipeline_data, str) else json.dumps(task.pipeline_data, ensure_ascii=False)
        with tempfile.TemporaryDirectory(prefix="nova-cpp-") as tmp:
            base = Path(tmp)
            source_path = base / "main.cpp"
            binary_path = base / ("main.exe" if shutil.which("where") else "main")
            source_path.write_text(source, encoding="utf-8")
            compile_proc = subprocess.run(
                [compiler, "-std=c++20", "-O2", str(source_path), "-o", str(binary_path)],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            if compile_proc.returncode != 0:
                if stream_mode == "tee":
                    if compile_proc.stdout:
                        sys.stdout.write(compile_proc.stdout)
                    if compile_proc.stderr:
                        sys.stderr.write(compile_proc.stderr)
                return ExecutorResult(
                    request_id=task.request_id,
                    status="error",
                    error=compile_proc.stderr.strip() or compile_proc.stdout.strip() or "compile failed",
                    metadata={"backend": "cpp", "compiler": compiler},
                )
            run_proc = subprocess.run(
                [str(binary_path)],
                capture_output=True,
                text=True,
                input=stdin_text,
                timeout=timeout_seconds,
            )
            if stream_mode == "tee":
                if run_proc.stdout:
                    sys.stdout.write(run_proc.stdout)
                if run_proc.stderr:
                    sys.stderr.write(run_proc.stderr)
            error = run_proc.stderr.strip() or None
            status = "ok" if run_proc.returncode == 0 else "error"
            return ExecutorResult(
                request_id=task.request_id,
                status=status,
                output=run_proc.stdout,
                data=run_proc.stdout,
                error=error,
                metadata={"backend": "cpp", "compiler": compiler, "returncode": run_proc.returncode},
            )


class _GpuAdapter:
    def execute(self, task: ExecutorTask) -> ExecutorResult:
        code = task.command or (task.arguments[0] if task.arguments else "")
        modules: list[tuple[str, Any]] = []
        for module_name, alias in (("cupy", "xp"), ("torch", "torch"), ("numpy", "xp")):
            try:
                module = __import__(module_name)
                modules.append((alias, module))
                if module_name == "cupy":
                    break
            except Exception:
                continue
        if not modules:
            return ExecutorResult(request_id=task.request_id, status="error", error="no GPU-capable runtime available", metadata={"backend": "gpu"})
        globals_ns: dict[str, Any] = {"json": json, "_": task.pipeline_data}
        for alias, module in modules:
            globals_ns[alias] = module
        stream_mode = str(task.metadata.get("stream_mode") or "")
        stdout: io.StringIO | _StreamTee = _StreamTee(sys.stdout) if stream_mode == "tee" else io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                try:
                    value = eval(code, globals_ns, globals_ns)
                    if value is not None:
                        print(value)
                except SyntaxError:
                    exec(code, globals_ns, globals_ns)
                    value = globals_ns.get("_")
            backend_name = "cupy" if "xp" in globals_ns and getattr(globals_ns["xp"], "__name__", "") == "cupy" else "python"
            return ExecutorResult(
                request_id=task.request_id,
                output=stdout.rendered() if isinstance(stdout, _StreamTee) else stdout.getvalue(),
                data=value,
                data_type=type(value).__name__,
                metadata={"backend": "gpu", "runtime": backend_name},
            )
        except Exception as exc:
            return ExecutorResult(request_id=task.request_id, status="error", error=str(exc), metadata={"backend": "gpu"})


class _WasmAdapter:
    def execute(self, task: ExecutorTask) -> ExecutorResult:
        runtime = shutil.which("wasmtime") or shutil.which("wasmer")
        module_path = task.command or (task.arguments[0] if task.arguments else "")
        timeout_seconds = float(task.metadata.get("timeout_seconds") or 30.0)
        stream_mode = str(task.metadata.get("stream_mode") or "")
        if runtime is None:
            return ExecutorResult(request_id=task.request_id, status="error", error="no wasm runtime available", metadata={"backend": "wasm"})
        if not module_path:
            return ExecutorResult(request_id=task.request_id, status="error", error="wasm.run requires a module path", metadata={"backend": "wasm"})
        target = Path(module_path)
        if not target.exists():
            return ExecutorResult(request_id=task.request_id, status="error", error=f"wasm module not found: {target}", metadata={"backend": "wasm"})
        proc = subprocess.run([runtime, str(target)], capture_output=True, text=True, timeout=timeout_seconds)
        if stream_mode == "tee":
            if proc.stdout:
                sys.stdout.write(proc.stdout)
            if proc.stderr:
                sys.stderr.write(proc.stderr)
        return ExecutorResult(
            request_id=task.request_id,
            status="ok" if proc.returncode == 0 else "error",
            output=proc.stdout,
            data=proc.stdout,
            error=proc.stderr or None,
            metadata={"backend": "wasm", "runtime": Path(runtime).name, "returncode": proc.returncode},
        )


class _AiAdapter:
    def __init__(self, command_executor: Any | None = None) -> None:
        self.command_executor = command_executor

    def execute(self, task: ExecutorTask) -> ExecutorResult:
        prompt = task.command or (task.arguments[0] if task.arguments else "")
        operation = task.operation or "ai.prompt"
        if self.command_executor is not None and operation in {"ai.prompt", "atheria.chat", "atheria.search", "memory.embed", "memory.search"}:
            command_map = {
                "ai.prompt": f'ai prompt {json.dumps(prompt, ensure_ascii=False)}',
                "atheria.chat": f'atheria chat {json.dumps(prompt, ensure_ascii=False)}',
                "atheria.search": f'atheria search {json.dumps(prompt, ensure_ascii=False)}',
                "memory.embed": f'memory embed {json.dumps(prompt, ensure_ascii=False)}',
                "memory.search": f'memory search {json.dumps(prompt, ensure_ascii=False)}',
            }
            response = self.command_executor.execute(command_map[operation], pipeline_data=task.pipeline_data, cwd=Path.cwd())
            return ExecutorResult(
                request_id=task.request_id,
                status="error" if response.error else "ok",
                output=response.output,
                data=response.data if response.data is not None else response.output,
                error=response.error,
                data_type=type(response.data).__name__ if response.data is not None else "text",
                metadata={"backend": "ai", **dict(response.metadata)},
            )
        data = {
            "operation": operation,
            "prompt": prompt,
            "input": task.pipeline_data,
            "mode": "synthetic",
        }
        return ExecutorResult(request_id=task.request_id, output=json.dumps(data, ensure_ascii=False), data=data, data_type="json", metadata={"backend": "ai"})


def execute_backend_task(backend: str, task: ExecutorTask, *, command_executor: Any | None = None) -> ExecutorResult:
    adapter = {
        "py": _PythonAdapter(),
        "cpp": _CppAdapter(),
        "gpu": _GpuAdapter(),
        "wasm": _WasmAdapter(),
        "ai": _AiAdapter(command_executor),
    }[backend]
    return adapter.execute(task)


class NativeExecutorServer:
    def __init__(self, backend: str, adapter: Any, *, host: str, port: int, auth_token: str | None = None) -> None:
        self.backend = backend
        self.adapter = adapter
        self.host = host
        self.port = int(port)
        self.auth_token = auth_token
        self._server: http.server.ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> str:
        if self._server is not None:
            return f"http://{self.host}:{self.port}"
        adapter = self.adapter
        auth_token = self.auth_token
        backend = self.backend

        class Handler(http.server.BaseHTTPRequestHandler):
            def _authorized(self) -> bool:
                if not auth_token:
                    return True
                return str(self.headers.get("Authorization") or "") == f"Bearer {auth_token}"

            def _write_json(self, payload: Any, status: int = 200) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                if not self._authorized():
                    self._write_json({"error": "unauthorized"}, status=401)
                    return
                if self.path == "/health":
                    self._write_json({"status": "ok", "backend": backend})
                    return
                self._write_json({"error": "not found"}, status=404)

            def do_POST(self) -> None:  # noqa: N802
                if not self._authorized():
                    self._write_json({"error": "unauthorized"}, status=401)
                    return
                if self.path != "/execute":
                    self._write_json({"error": "not found"}, status=404)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
                result = adapter.execute(ExecutorTask.from_dict(payload))
                self._write_json(result.to_dict())

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
                return

        self._server = http.server.ThreadingHTTPServer((self.host, self.port), Handler)
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(target=self._server.serve_forever, name=f"NovaExecutor:{self.backend}", daemon=True)
        self._thread.start()
        return f"http://{self.host}:{self.port}"

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._thread = None
        self._server = None


class NativeExecutorManager:
    def __init__(self, base_path: Path, *, command_executor: Any | None = None) -> None:
        state_dir = (base_path / ".nova").resolve(strict=False)
        state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = state_dir / "runtime-executors.db"
        self.daemon_dir = state_dir / "executor-daemons"
        self.daemon_dir.mkdir(parents=True, exist_ok=True)
        self.command_executor = command_executor
        self.base_path = base_path
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._lock = threading.RLock()
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS executors (
                    backend TEXT PRIMARY KEY,
                    endpoint TEXT NOT NULL,
                    host TEXT NOT NULL,
                    port INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    auth_token TEXT,
                    tls_profile TEXT,
                    request_count INTEGER NOT NULL,
                    started_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_error TEXT,
                    metadata_json TEXT NOT NULL
                )
                """
            )

    def close(self) -> None:
        for backend in list(self._processes):
            self.stop_backend(backend)
        with self._lock:
            self._conn.close()

    def ensure_backend(self, backend: str) -> dict[str, Any]:
        record = self.get_backend(backend)
        if record is not None and self._healthy(record):
            return record
        return self._start_backend(backend, previous_record=record)

    def get_backend(self, backend: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT backend, endpoint, host, port, status, auth_token, tls_profile, request_count, started_at, updated_at, last_error, metadata_json
                FROM executors
                WHERE backend=?
                """,
                (backend,),
            ).fetchone()
        if row is None:
            return None
        return ExecutorRecord(
            backend=row[0],
            endpoint=row[1],
            host=row[2],
            port=int(row[3]),
            status=row[4],
            auth_token=row[5],
            tls_profile=row[6],
            request_count=int(row[7]),
            started_at=float(row[8]),
            updated_at=float(row[9]),
            last_error=row[10],
            metadata=json.loads(row[11]),
        ).to_dict()

    def list_backends(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT backend, endpoint, host, port, status, auth_token, tls_profile, request_count, started_at, updated_at, last_error, metadata_json
                FROM executors
                ORDER BY backend
                """
            ).fetchall()
        records = [
            ExecutorRecord(
                backend=row[0],
                endpoint=row[1],
                host=row[2],
                port=int(row[3]),
                status=row[4],
                auth_token=row[5],
                tls_profile=row[6],
                request_count=int(row[7]),
                started_at=float(row[8]),
                updated_at=float(row[9]),
                last_error=row[10],
                metadata=json.loads(row[11]),
            ).to_dict()
            for row in rows
        ]
        for record in records:
            if not self._healthy(record):
                record["status"] = "unhealthy"
        return records

    def execute(self, backend: str, task: ExecutorTask) -> Any:
        from .context import CommandExecution

        record = self.ensure_backend(backend)
        payload = self._request(
            record,
            "/execute",
            task.to_dict(),
            timeout=float(task.metadata.get("timeout_seconds") or 30.0) + 5.0,
        )
        self._mark_request(backend, payload.get("error"))
        return CommandExecution(
            output=str(payload.get("output", "")),
            data=payload.get("data"),
            error=payload.get("error"),
            metadata={"executor_backend": backend, "executor_protocol": payload.get("protocol"), **dict(payload.get("metadata") or {})},
        )

    def execute_async(self, backend: str, task: ExecutorTask) -> dict[str, Any]:
        record = self.ensure_backend(backend)
        return self._request(record, "/execute/async", task.to_dict(), timeout=10.0)

    def cancel(self, backend: str, request_id: str) -> dict[str, Any]:
        record = self.ensure_backend(backend)
        return self._request(record, f"/cancel/{request_id}", {}, timeout=10.0)

    def stream(self, backend: str, request_id: str) -> dict[str, Any]:
        record = self.ensure_backend(backend)
        return self._request(record, f"/stream/{request_id}", None, method="GET", timeout=10.0)

    def stop_backend(self, backend: str) -> dict[str, Any]:
        process = self._processes.pop(backend, None)
        record = self.get_backend(backend)
        if record is not None:
            try:
                self._request(record, "/shutdown", {}, timeout=5.0)
            except Exception:
                pass
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3.0)
            except Exception:
                process.kill()
        self._update_record_status(backend, "stopped", None)
        return self.get_backend(backend) or {"backend": backend, "status": "stopped"}

    def restart_backend(self, backend: str) -> dict[str, Any]:
        self.stop_backend(backend)
        return self._start_backend(backend, previous_record=self.get_backend(backend))

    def recover(self) -> dict[str, Any]:
        restarted: list[str] = []
        for record in self.list_backends():
            if record.get("status") == "unhealthy":
                self._start_backend(str(record["backend"]), previous_record=record)
                restarted.append(str(record["backend"]))
        return {"restarted": restarted, "count": len(restarted)}

    def snapshot(self) -> dict[str, Any]:
        return {"db_path": str(self.db_path), "executors": self.list_backends()}

    def _endpoint_file(self, backend: str) -> Path:
        return self.daemon_dir / f"{backend}.endpoint.json"

    def _log_file(self, backend: str, stream_name: str) -> Path:
        return self.daemon_dir / f"{backend}.{stream_name}.log"

    def _start_backend(self, backend: str, *, previous_record: dict[str, Any] | None = None) -> dict[str, Any]:
        endpoint_file = self._endpoint_file(backend)
        if endpoint_file.exists():
            endpoint_file.unlink()
        auth_token = str(previous_record.get("auth_token")) if previous_record and previous_record.get("auth_token") else uuid.uuid4().hex[:16]
        stderr_handle = self._log_file(backend, "stderr").open("a", encoding="utf-8")
        stdout_handle = self._log_file(backend, "stdout").open("a", encoding="utf-8")
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "nova.runtime.executor_daemon",
                "--backend",
                backend,
                "--host",
                "127.0.0.1",
                "--port",
                "0",
                "--auth-token",
                auth_token,
                "--endpoint-file",
                str(endpoint_file),
                "--base-path",
                str(self.base_path),
            ],
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
            cwd=str(self.base_path),
            env=self._daemon_env(),
        )
        stdout_handle.close()
        stderr_handle.close()
        self._processes[backend] = process
        deadline = time.time() + 10.0
        while time.time() < deadline:
            if endpoint_file.exists():
                payload = json.loads(endpoint_file.read_text(encoding="utf-8"))
                record = ExecutorRecord(
                    backend=backend,
                    endpoint=str(payload["endpoint"]),
                    host=str(payload["host"]),
                    port=int(payload["port"]),
                    status="ok",
                    auth_token=auth_token,
                    request_count=int(previous_record.get("request_count", 0)) if previous_record else 0,
                    last_error=None,
                    metadata={"isolated": True, "pid": process.pid, "mode": "subprocess"},
                ).to_dict()
                with self._lock, self._conn:
                    self._conn.execute(
                        """
                        INSERT INTO executors(backend, endpoint, host, port, status, auth_token, tls_profile, request_count, started_at, updated_at, last_error, metadata_json)
                        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(backend) DO UPDATE SET
                            endpoint=excluded.endpoint,
                            host=excluded.host,
                            port=excluded.port,
                            status=excluded.status,
                            auth_token=excluded.auth_token,
                            request_count=excluded.request_count,
                            updated_at=excluded.updated_at,
                            last_error=excluded.last_error,
                            metadata_json=excluded.metadata_json
                        """,
                        (
                            backend,
                            record["endpoint"],
                            record["host"],
                            record["port"],
                            record["status"],
                            auth_token,
                            None,
                            record["request_count"],
                            record["started_at"],
                            record["updated_at"],
                            None,
                            json.dumps(record["metadata"], ensure_ascii=False),
                        ),
                    )
                return self.get_backend(backend) or record
            if process.poll() is not None:
                break
            time.sleep(0.1)
        stderr_handle.close()
        stdout_handle.close()
        self._update_record_status(backend, "error", "executor daemon failed to start")
        raise RuntimeError(f"executor daemon failed to start for backend '{backend}'")

    def _healthy(self, record: dict[str, Any]) -> bool:
        try:
            payload = self._request(record, "/health", None, method="GET", timeout=3.0)
            return str(payload.get("status") or "") == "ok"
        except Exception:
            return False

    def _request(self, record: dict[str, Any], path: str, payload: dict[str, Any] | None, *, method: str = "POST", timeout: float = 10.0) -> dict[str, Any]:
        headers = {}
        auth_token = record.get("auth_token")
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(str(record["endpoint"]).rstrip("/") + path, data=data, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _mark_request(self, backend: str, error: str | None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE executors SET request_count=request_count+1, updated_at=?, last_error=?, status=? WHERE backend=?",
                (time.time(), error, "error" if error else "ok", backend),
            )

    def _update_record_status(self, backend: str, status: str, error: str | None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE executors SET status=?, updated_at=?, last_error=? WHERE backend=?",
                (status, time.time(), error, backend),
            )

    def _daemon_env(self) -> dict[str, str]:
        env = dict(os.environ)
        project_root = str(Path(__file__).resolve().parents[2])
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = project_root if not existing else project_root + os.pathsep + existing
        return env
