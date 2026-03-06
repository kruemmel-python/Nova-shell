# Nova-shell

Nova-shell ist ein **Compute-Runtime-Prototyp**: eine Shell mit Pipeline-Engine, Typed Streams, Execution-Graph und NovaScript-DSL.

## Überblick

Nova-shell kombiniert:

- klassische Shell-Kommandos (`sys` / Fallback)
- Python-Execution mit persistentem Kontext (`py`, `python`)
- C++-Compile/Run (`cpp`)
- GPU-Kernel-Execution (`gpu`, optional über OpenCL)
- Data-Pipelines (`data load`, `data.load`)
- Stream/Follower-Pipelines (`watch`)
- Parallel-Fanout (`parallel ...`)
- Pipeline-Telemetrie (`events last|stats|clear`)
- Mini-DSL (`ns.exec`, `ns.run`)

## Quickstart

```bash
python nova_shell.py
```

## Wichtige Commands

- `py <code>` / `python <code>` – Python ausführen (mit persistentem `_` + Globals)
- `cpp <code>` – C++ kompilieren und ausführen (`g++` erforderlich)
- `gpu <kernel.cl>` – OpenCL-Kernel ausführen (`pyopencl` + `numpy` erforderlich)
- `data load <file.csv>` – CSV laden
- `watch <file> --lines N` – letzte N Zeilen als Stream
- `watch <file> --follow-seconds S` – tail-artiger Follow-Stream
- `parallel <stage>` – Stage parallel auf Stream-Items ausführen
- `events last|stats|clear` – Telemetrie anzeigen/aggregieren/leeren
- `ns.exec <script>` / `ns.run <file.ns>` – NovaScript ausführen
- `cd`, `pwd`, `help`, `exit`

## Pipeline-Beispiele

```text
nova> py x = 10
nova> py x + 5
15

nova> data load cities.csv | py len(_)
42

nova> watch logs.txt --follow-seconds 2 | py _.upper()
...

nova> printf 'a\nb\n' | parallel py _.upper()
A
B
```

## Typed Pipeline Model

`CommandResult` transportiert:

- `output: str`
- `data: Any`
- `error: str | None`
- `data_type: PipelineType`

Pipeline-Typen umfassen u. a. `TEXT`, `OBJECT`, `TEXT_STREAM`, `GENERATOR`.
Generator-Pipelines bleiben zwischen Stages lazy und werden am Ende materialisiert.

## Execution Graph + Optimizer

Nova-shell baut intern einen `PipelineGraph` aus `PipelineNode`s.
Aufeinanderfolgende Python-Stages werden als `py_chain` geplant (Stage-Fusion auf Plan-Ebene), bevor die Ausführung läuft.

## Telemetrie

Events enthalten u. a.:

- `stage`
- `node`
- `data_type`
- `duration_ms`
- `rows_processed`

Mit `events stats` bekommst du aggregierte Kennzahlen wie durchschnittliche Stage-Dauer.

## NovaScript DSL (kurz)

Unterstützt aktuell:

- Assignment: `x = py 5*5`
- For-Loop (4 Spaces eingerückt)
- If-Block (4 Spaces eingerückt)
- Variablen-Injection via `$name`

## Tests

```bash
python -m unittest discover -s tests -v
```
