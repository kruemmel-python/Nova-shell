from __future__ import annotations

import argparse

import nova_shell


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local Nova-shell mesh worker.")
    parser.add_argument("--host", default="127.0.0.1", help="host for the worker HTTP server")
    parser.add_argument("--port", type=int, default=8769, help="port for the worker HTTP server")
    parser.add_argument("--caps", default="cpu,py,ai", help="comma-separated worker capabilities")
    parser.add_argument("--token", default="", help="optional bearer token required by the worker")
    parser.add_argument("--cert", default="", help="TLS certificate path for the worker")
    parser.add_argument("--key", default="", help="TLS private key path for the worker")
    parser.add_argument("--ca", default="", help="optional CA bundle path for the worker")
    return parser


def translate_args(namespace: argparse.Namespace) -> list[str]:
    argv = [
        "--serve-worker",
        "--worker-host",
        namespace.host,
        "--worker-port",
        str(namespace.port),
        "--worker-caps",
        namespace.caps,
    ]
    if namespace.token:
        argv.extend(["--worker-token", namespace.token])
    if namespace.cert:
        argv.extend(["--worker-cert", namespace.cert])
    if namespace.key:
        argv.extend(["--worker-key", namespace.key])
    if namespace.ca:
        argv.extend(["--worker-ca", namespace.ca])
    return argv


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    namespace = parser.parse_args(argv)
    return int(nova_shell.main(translate_args(namespace)))


if __name__ == "__main__":
    raise SystemExit(main())
