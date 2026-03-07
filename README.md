# Nova-shell

Nova-shell ist eine **Unified Compute & Data Orchestration Runtime** mit polyglotten Engines, Typed Pipelines, Streaming und NovaScript.

## Implementierte 5 Enterprise-Erweiterungen (v2)

### 1) NovaFabric-X — Unified Arrow-Native Memory Grid (MVP)
- `PipelineType.SHARED_MEMORY` für Handle-basierte Übergabe.
- `fabric put <text>` / `fabric get <handle>` für lokalen Shared-Memory-Transport.
- `fabric put-arrow <csv>` kombiniert Arrow-Load (`pyarrow`, optional) mit Fabric-Handle-Export.
- Ziel: weniger Serialisierung zwischen Stages; Grundlage für Zero-Copy-Workflows.

### 2) NovaMesh — Topology-Aware Scheduler (MVP)
- `mesh add <worker_url> <cap1,cap2,...>` registriert Worker und Capabilities.
- `mesh list` zeigt Worker inkl. aktueller Last.
- `mesh run <capability> <command>` wählt automatisch den am wenigsten belasteten Worker mit passender Capability.
- `remote <worker_url> <command>` bleibt als Low-Level-Primitive verfügbar.

### 3) NovaGuard-OS — Policy + Wasm-orientierte Isolation
- Policies: `open`, `minimal`, `offline`.
- `guard list`, `guard set <policy>`, `secure <policy> <command>`.
- Stage-weises Enforcement in der Pipeline-Ausführung.
- Zusätzlicher Wasm-Sicherheits-Guard in `secure wasm ...` für untrusted Compute-Pfade.

### 4) NovaFlow — Stateful Contextual Event Streaming
- SQLite-basiertes State-Backend (`FlowStateStore`) für zustandsbehaftete Auswertung.
- `flow state set <key> <value>` / `flow state get <key>`.
- `flow count-last <seconds> [pattern]` für Window-ähnliche Event-Zählung.
- `on file "<glob>" --timeout <sec> "<pipeline mit _>"` als reaktiver Trigger.

### 5) NovaStudio — Live Graph + LSP-style Introspection
- `studio completions <prefix>` liefert Command-Completion-Daten.
- `studio graph` liefert den letzten `PipelineGraph` als JSON.
- `studio events` exportiert den aktuellen Event-Buffer.
- Vision HTTP API erweitert um:
  - `GET /commands`
  - `GET /lsp/completions?prefix=<x>`
  - bestehend: `GET /events`, `GET /graph`

---

## Weitere Runtime-Features

- `py` / `python` mit persistentem Kontext (`py x=10`, danach `py x+5`).
- `cpp` (g++), `gpu` (pyopencl, optional), `wasm` (wasmtime, optional).
- `data load <csv> [--arrow]` und `data.load <csv> [--arrow]`.
- PipelineGraph/PipelineNode mit Fusion aufeinanderfolgender Python-Stages (`py_chain`).
- `watch` + `parallel` + Generator/Stream-Pipelines.
- Telemetrie pro Stage (`duration_ms`, `rows_processed`, `cpu_percent`, `rss_mb`, `cost_estimate`, `trace_id`).
- NovaScript via `ns.exec` und `ns.run`.

## Quickstart

```bash
python nova_shell.py
```

## Beispiele

```text
nova> fabric put hello
psm_abc123
nova> fabric get psm_abc123
hello

nova> mesh add http://127.0.0.1:9000 gpu,cpu
nova> mesh list
[{"url":"http://127.0.0.1:9000","caps":["cpu","gpu"],"load":0}]

nova> flow state set threshold 5
ok
nova> flow state get threshold
5

nova> observe run "data load file.csv | py len(_)"
{"trace_id":"...","stats":...}
```

## Tests

```bash
python -m unittest discover -s tests -v
```
