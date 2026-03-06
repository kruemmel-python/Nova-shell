# Nova-shell

Nova-shell ist ein **Compute-Runtime Shell-Prototyp mit Mini-DSL (NovaScript)**.

## Kernfeatures

- Python-Ausführung (`py`, `python`) mit **persistentem Python-Kontext**
- C++-Kompilierung/Ausführung (`cpp` via `g++`)
- GPU-Kernel-Ausführung (`gpu`) via OpenCL (`pyopencl` + `numpy`)
- Datenkommandos (`data load`, `data.load`) für CSV
- **Object Pipeline** (`CommandResult.data`) statt reinem String-Transport
- **Parallel Pipeline** über `parallel <command>`
- Event-Stream über `events` (`last`, `clear`)
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

nova> printf 'a\nb\n' | parallel py _.upper()
A
B
```

## NovaScript DSL

Unterstützt:

- Assignment: `x = py 5*5`
- For-Loop: `for f in files:` (Body mit 4 Spaces)
- If-Block: `if len(files_lines) > 0:` (Body mit 4 Spaces)
- Variable-Injection: `$name`

Script-Datei:

```text
files = sys printf 'a\nb\n'
for f in files:
    py $f
if len(files_lines) == 2:
    py 42
```

Ausführen:

```text
nova> ns.run sample.ns
42
```

## Architektur

- `CommandResult(output, data, error)` als Pipeline-Container
- `PythonEngine` mit persistentem `self.globals`
- `NovaShell.route()` propagiert `output` + `data` zwischen Stages
- `parallel` Stage nutzt `ThreadPoolExecutor` für fan-out über Zeilen/List-Items
- `novascript.py` liefert `NovaParser` + `NovaInterpreter`

## Tests

```bash
python -m unittest discover -s tests -v
```
