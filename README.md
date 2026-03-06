# Nova-shell

Nova-shell ist eine **Unified Compute & Data Orchestration Runtime** mit polyglotten Engines, Typed Pipelines, Streaming und NovaScript.

## Implementierte 5 Enterprise-Erweiterungen

### 1) NovaFabric — Distributed Zero-Copy Memory Bridge (MVP)
- Neuer Typ: `PipelineType.SHARED_MEMORY`
- Neuer Befehl: `fabric put <text>`, `fabric get <handle>`
- Nutzt `multiprocessing.shared_memory` für handle-basierten Datentransport.

### 2) NovaGuard — Policy-as-Code Sandbox
- Richtlinien: `open`, `minimal`, `offline`
- Befehle: `guard list`, `guard set <policy>`, `secure <policy> <command>`
- Enforcement erfolgt stage-weise in der Pipeline-Execution.

### 3) NovaStream — Reactive Event-Triggered Pipelines
- Bestehend: `watch ...` (snapshot/follow)
- Neu: `on file "<glob>" --timeout <sec> "<pipeline mit _>"`
- Event-getriebener Trigger startet Pipeline bei Datei-Eingang.

### 4) NovaPack — Hermetic Pipeline Bundling (OCI-ready foundation)
- Befehl: `pack <script.ns> --output <bundle.npx> [--requirements req.txt]`
- Erstellt ein Bundle mit Script + Manifest als transportierbares Artefakt.

### 5) NovaObserve — Distributed Tracing & Cost Profiling
- Event-Payload enthält:
  - `trace_id`, `stage`, `node`, `data_type`
  - `duration_ms`, `rows_processed`
  - `cpu_percent`, `rss_mb`, `cost_estimate`
- Befehle: `events last|stats|clear`, `observe run <pipeline>`

---

## Weitere Plattform-Features

- `py` / `python` mit persistentem Kontext
- `cpp` (g++), `gpu` (pyopencl), `wasm` (wasmtime)
- `remote <worker_url> <command>` (NovaMesh MVP)
- `data load <csv> [--arrow]` (Arrow optional via `pyarrow`)
- `vision start|status|stop` + HTTP-Endpunkte `/events`, `/graph`
- PipelineGraph/PipelineNode mit Python-Stage-Fusion (`py_chain`)
- NovaScript (`ns.exec`, `ns.run`)

## Quickstart

```bash
python nova_shell.py
```

## Beispiel

```text
nova> guard set minimal
nova> secure minimal sys ls
ERROR: policy 'minimal' blocks command 'sys'

nova> fabric put hello
psm_abc123
nova> fabric get psm_abc123
hello

nova> on file "input/*.csv" --timeout 5 "data load _ | py len(_)"
42

nova> observe run "data load file.csv | py len(_)"
{"trace_id":"...","stats":...}
```

## Tests

```bash
python -m unittest discover -s tests -v
```
