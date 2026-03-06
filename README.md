# Nova-shell

Nova-shell ist ein **Compute-Runtime Shell-Prototyp mit Mini-DSL (NovaScript)**.

## Kernfeatures

- Python-Ausführung (`py`, `python`) mit **persistentem Python-Kontext**
- C++-Kompilierung/Ausführung (`cpp` via `g++`)
- GPU-Kernel-Ausführung (`gpu`) via OpenCL (`pyopencl` + `numpy`)
- Datenkommandos (`data load`, `data.load`) für CSV
- **Typed Pipeline** über `PipelineType` (`text`, `object`, `*_stream`)
- **Object Pipeline** (`CommandResult.data`) statt reinem String-Transport
- **Stream Pipeline** via `watch <file> --lines N` oder live `watch <file> --follow-seconds S`
- **Parallel Pipeline** über `parallel <command>`
- **Async Runtime** mit persistentem Event-Loop (`route()` ohne per-command loop spin-up)
- Event-Stream über `events` (`last`, `clear`, `stats`)
- NovaScript-Ausführung (`ns.exec`, `ns.run`) mit Parser + AST + Interpreter
- System-Command-Fallback (`sys` oder direkter Befehl)
- Built-ins (`cd`, `pwd`, `help`, `exit`)
- Plugin-System über `plugins/*.py`

## Starten

```bash
python nova_shell.py
```

## Beispiele

```text
nova> py x = 10
nova> py x + 5
15

nova> data load cities.csv | py len(_)
42

nova> watch logs.txt --follow-seconds 2 | py _.lower()
...

nova> printf 'a\nb\n' | parallel py _.upper()
A
B
```

## Typisierte Pipelines

`CommandResult` enthält:

- `output: str`
- `data: Any`
- `error: str | None`
- `data_type: PipelineType`

So kann eine Stage nicht nur Text, sondern auch strukturierte Objekte/Streams weitergeben.

Generator-Streams werden stage-weise lazy weitergereicht und am Pipeline-Ende materialisiert,
damit Zwischenstufen nicht unnötig alles sammeln müssen.

Events enthalten zusätzlich Laufzeitmetrik (`duration_ms`) und Verarbeitungsmenge (`rows_processed`).

## NovaScript DSL

Unterstützt:

- Assignment: `x = py 5*5`
- For-Loop: `for f in files:` (Body mit 4 Spaces)
- If-Block: `if len(files_lines) > 0:` (Body mit 4 Spaces)
- Variable-Injection: `$name`

## Architektur

- `CommandResult(output, data, error, data_type)` als Pipeline-Container
- `PythonEngine` mit persistentem `self.globals`
- `NovaShell.route_async()` als Async-Orchestrierung
- `watch` liefert Text-Streams (`PipelineType.TEXT_STREAM`) oder Lazy-Generatoren (`PipelineType.GENERATOR`)
- `parallel` Stage nutzt `ThreadPoolExecutor` für fan-out
- `novascript.py` liefert `NovaParser` + `NovaInterpreter`

## Tests

```bash
python -m unittest discover -s tests -v
```
