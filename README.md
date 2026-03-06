# Nova-shell

Nova-shell ist ein **Compute-Runtime-Prototyp** mit Pipeline-Engine, NovaScript-DSL und polyglotten Engines.

## Neu: 5 strategische Erweiterungen

1. **NovaMesh (Remote Workers)**
   - Kommando: `remote <worker_url> <command>`
   - Ermöglicht delegierte Stage-Ausführung über HTTP/JSON.

2. **NovaFlow (Arrow / Zero-Copy-Vorbereitung)**
   - Kommando: `data load <file.csv> --arrow`
   - Nutzt (optional) `pyarrow` und übergibt ein Arrow-Table-Objekt im Pipeline-Transport.

3. **NovaShield (Wasm Isolation Layer)**
   - Kommando: `wasm <module.wasm>`
   - Führt Wasm-Module über `wasmtime` aus (wenn installiert).

4. **NovaIntel (AI Pipeline Synthesis)**
   - Kommando: `ai "<prompt>"`
   - Erzeugt Pipeline-Vorschläge aus natürlicher Sprache als Einstiegspunkt.

5. **NovaVision (Live Pipeline Inspection)**
   - Kommandos: `vision start [port]`, `vision status`, `vision stop`
   - Exponiert Runtime-Daten über HTTP (`/events`, `/graph`).

## Kernfeatures

- Python-Ausführung (`py`, `python`) mit persistentem Kontext
- C++-Kompilierung/Ausführung (`cpp` via `g++`)
- GPU-Kernel (`gpu`) via OpenCL (`pyopencl` + `numpy`)
- Typed Pipelines über `CommandResult` + `PipelineType`
- Streaming (`watch ...`) und Parallel-Fanout (`parallel ...`)
- PipelineGraph/Node-Planung mit `py_chain`-Fusion
- NovaScript (`ns.exec`, `ns.run`)
- Telemetrie über `events last|stats|clear`

## Quickstart

```bash
python nova_shell.py
```

## Beispiele

```text
nova> data load cities.csv --arrow
nova> ai "average column A from csv"
nova> vision start 8877
nova> remote http://127.0.0.1:9000/execute py 1+1
nova> wasm module.wasm
```

## Tests

```bash
python -m unittest discover -s tests -v
```
