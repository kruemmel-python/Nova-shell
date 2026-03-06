# Nova-shell

Nova-shell ist ein **PowerShell-ähnlicher Hybrid-Prototyp** mit:

- Python-Ausführung (`py`)
- C++-Kompilierung und Ausführung (`cpp` via `g++`)
- System-Command-Fallback (`sys` oder direkter Befehl)
- Pipeline-Unterstützung (`cmd | py ...`)
- Plugin-System über `plugins/*.py`

## Starten

```bash
python nova_shell.py
```

## Beispiele

```text
nova> py print("Hello Python")
nova> py len("abc")
nova> echo hallo | py _.strip().upper()
nova> cpp #include <iostream>\nint main(){std::cout<<"Hello C++";}
nova> sys echo direkt
nova> exit
```

## Architektur

- `PythonEngine`: führt Snippets direkt aus (`eval`/`exec`), Pipeline-Input liegt in `_`.
- `CppEngine`: schreibt temporäre `program.cpp`, kompiliert mit `g++ -std=c++20`, führt Binary aus.
- `SystemEngine`: führt Host-Shell-Commands aus.
- `NovaShell`: Routing per Pattern Matching, Pipelines, REPL und Plugin-Lader.

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
python -m unittest -v
```
