# Nova-shell

Nova-shell ist ein **PowerShell-ähnlicher Hybrid-Prototyp** mit:

- Python-Ausführung (`py`, `python`)
- C++-Kompilierung und Ausführung (`cpp` via `g++`)
- System-Command-Fallback (`sys` oder direkter Befehl)
- Pipeline-Unterstützung (`cmd | py ...`) inkl. robuster Trennung bei zitierten Pipes
- Built-in Commands (`cd`, `pwd`, `help`, `exit`)
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

/home/user/project > echo hallo | py _.strip().upper()
HALLO

/home/user/project > py "a|b"
a|b

/home/user/project > cd ..
/home/user > pwd
/home/user
```

## Architektur

- `PythonEngine`: führt Snippets direkt aus (`eval`/`exec`), Pipeline-Input liegt in `_`.
- `CppEngine`: schreibt temporäre `program.cpp`, kompiliert mit `g++ -std=c++20`, führt Binary aus.
- `SystemEngine`: führt Host-Shell-Commands aus.
- `NovaShell`: Routing per Pattern Matching, Pipelines, Built-ins, REPL und Plugin-Lader.

## Plugins

Lege Python-Dateien in `plugins/` an. Jede Datei kann eine `register(shell)` Funktion anbieten:

```python
from nova_shell import CommandResult


def register(shell):
    def hello(args: str, _input: str) -> CommandResult:
        return CommandResult(output=f"Hello {args or 'Plugin'}\n")

    shell.register_command("hello", hello)
```

Dann in der Shell:

```text
nova> hello Welt
Hello Welt
```

## Tests

```bash
python -m unittest discover -s tests -v
```
