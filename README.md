# Nova-shell

Nova-shell ist ein **Compute-Runtime Shell-Prototyp mit eigener Mini-DSL (NovaScript)**:

- Python-Ausführung (`py`, `python`)
- C++-Kompilierung und Ausführung (`cpp` via `g++`)
- GPU-Kernel-Ausführung (`gpu`) via OpenCL (`pyopencl` + `numpy`)
- Datenkommandos (`data load`, `data.load`) für CSV
- Event-Stream über `events` (`last`, `clear`)
- NovaScript-Ausführung (`ns.exec`, `ns.run`) mit Parser + AST + Interpreter
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

/home/user/project > ns.exec x = py 5*5; py $x
25

/home/user/project > events last
{"stage": "py 5 * 5", "error": "", "output": "25\n"}
```

## NovaScript DSL

Unterstützte Sprachbausteine:

- Assignment: `x = py 5*5`
- For-Loop:
  - `for f in files:`
  - eingerückter Body (4 Spaces)
- If-Block:
  - `if len(files_lines) > 0:`
  - eingerückter Body (4 Spaces)
- Variable-Injection in Commands via `$name`

### Script-Datei ausführen

```bash
# sample.ns
files = sys printf 'a\nb\n'
for f in files:
    py $f
if len(files_lines) == 2:
    py 42
```

```text
nova> ns.run sample.ns
42
```

## Architektur

- `novascript.py`
  - `NovaParser`: baut AST-Knoten (`Assignment`, `Command`, `ForLoop`, `IfBlock`)
  - `NovaInterpreter`: führt AST gegen `NovaShell.route()` aus
- `nova_shell.py`
  - `PythonEngine`: `eval`/`exec`, Pipeline-Input in `_`
  - `CppEngine`: temp `program.cpp` + `g++ -std=c++20`
  - `GPUEngine`: OpenCL-Kernel-Ausführung über `pyopencl`
  - `DataEngine`: CSV-Loading mit JSON-Ausgabe
  - `SystemEngine`: Host-Shell-Commands
  - `EventBus`: Stage-Events für jede ausgeführte Pipeline-Stufe

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
