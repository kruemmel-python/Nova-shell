# Nova-shell

Nova-shell ist eine **Unified Compute & Data Orchestration Runtime** mit polyglotten Engines, Typed Pipelines, NovaScript und Observability.

## Neu umgesetzt (Enterprise-Track)

### 1) NovaCompute JIT (`jit_wasm`)
- NovaScript-ähnliche arithmetische Ausdrücke werden in WAT transpiliert und zur Laufzeit als Wasm ausgeführt.
- Kommando: `jit_wasm "1 + 2 * 3"`
- Fallback-Verhalten: klare Fehlermeldung, wenn `wasmtime` nicht installiert ist.

### 2) NovaSync (CRDT-basiertes dezentrales State-Management)
- G-Counter CRDT für globale Zähler.
- LWW-Map CRDT für Key/Value-Konfigurationen.
- Kommandos:
  - `sync inc <counter> [amount]`
  - `sync get <counter>`
  - `sync set <key> <value>`
  - `sync get-key <key>`
  - `sync export`
  - `sync merge <json_state>`

### 3) NovaLens (Temporal Lineage & Time-Travel Debugging)
- Snapshot-Erzeugung pro Stage-Ausführung (Trace-ID, Stage, Output-Preview, Data-Type, Zeitstempel).
- Kommandos:
  - `lens last`
  - `lens list [n]`
  - `lens show <snapshot_id>`

### 4) NovaFabric-Remote (Zero-Copy-Bridge über Mesh-Endpunkte, MVP)
- Lokaler Shared-Memory-Fabric bleibt erhalten: `fabric put/get`.
- Arrow-orientierter Handle-Export: `fabric put-arrow <csv>`.
- Remote-Transport-API (HTTP-basiertes MVP):
  - `fabric remote-put <url> <text>`
  - `fabric remote-get <url> <handle>`

### 5) Bereits vorhandene Plattform-Bausteine weiter integriert
- Mesh Scheduler: `mesh add/list/run`
- Guard/Policy: `guard`, `secure`
- Flow State: `flow state ...`, `flow count-last ...`
- Studio & Vision:
  - CLI: `studio completions|graph|events`
  - HTTP: `/events`, `/graph`, `/commands`, `/lsp/completions?prefix=...`

---

## Weitere Runtime-Features

- `py` / `python` mit persistentem Kontext.
- `cpp`, `gpu`, `wasm`, `remote` Engines.
- `data load <csv> [--arrow]` und `data.load <csv> [--arrow]`.
- PipelineGraph mit Python-Stage-Fusion (`py_chain`).
- `watch`-Streaming, `parallel`-Fanout, Generator-Pipelines.
- Telemetrie je Stage (`duration_ms`, `rows_processed`, `cpu_percent`, `rss_mb`, `cost_estimate`, `trace_id`).
- NovaScript: `ns.exec`, `ns.run`.

## Quickstart

```bash
python nova_shell.py
```

## Beispiele

```text
nova> jit_wasm "10 / 2 + 7"
12.0

nova> sync inc requests 5
5
nova> sync get requests
5

nova> py 2 + 2
4
nova> lens last
{"id":"...","stage":"py 2 + 2", ...}

nova> mesh add http://127.0.0.1:9000 gpu,cpu
nova> mesh list
[{"url":"http://127.0.0.1:9000","caps":["cpu","gpu"],"load":0}]
```

## Tests

```bash
python -m unittest discover -s tests -v
```
