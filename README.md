# Nova-shell

Nova-shell ist jetzt ein **Compute-Runtime Shell-Prototyp**:

- Python-Ausführung (`py`, `python`)
- C++-Kompilierung und Ausführung (`cpp` via `g++`)
- GPU-Kernel-Ausführung (`gpu`) via OpenCL (`pyopencl` + `numpy`)
- Datenkommandos (`data load`, `data.load`) für CSV
- Event-Stream über `events` (`last`, `clear`)
- System-Command-Fallback (`sys` oder direkter Befehl)
- Pipeline-Unterstützung (`cmd | py ...`) inkl. robuster Trennung bei zitierten Pipes
- Built-ins (`cd`, `pwd`, `help`, `exit`)
- Plugin-System über `plugins/*.py`
- Command-History (wenn `readline` verfügbar ist)

## Starten

```bash
python nova_shell.py
```

## Beispiele

```text
/home/user/project > py 5 * 5
25

/home/user/project > data load cities.csv | py _.count("name")
42

/home/user/project > gpu kernel.cl
0.0 1.0 2.0 ...

/home/user/project > events last
{"stage": "py 5 * 5", "error": "", "output": "25\n"}
```

## Architektur

- `PythonEngine`: `eval`/`exec`, Pipeline-Input in `_`
- `CppEngine`: temp `program.cpp` + `g++ -std=c++20`
- `GPUEngine`: OpenCL-Kernel-Ausführung über `pyopencl`
- `DataEngine`: CSV-Loading mit JSON-Ausgabe
- `SystemEngine`: Host-Shell-Commands
- `EventBus`: Stage-Events für jede ausgeführte Pipeline-Stufe
- `NovaShell`: Routing, Built-ins, Pipelines, REPL, Plugin-Loader

## GPU Hinweis

`gpu` benötigt:

- `pyopencl`
- `numpy`
- einen verfügbaren OpenCL-Treiber / Device

Wenn etwas fehlt, liefert der Command eine klare Fehlermeldung.

## Plugins

Lege Python-Dateien in `plugins/` an. Jede Datei kann eine `register(shell)` Funktion anbieten:

```python
from nova_shell import CommandResult


def register(shell):
    def train(args: str, _input: str) -> CommandResult:
        return CommandResult(output=f"training model with {args}\n")

    shell.register_command("ai.train", train)
```

## Tests

```bash
python -m unittest discover -s tests -v
```
