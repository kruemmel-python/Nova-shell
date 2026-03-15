# Development Guide

## Zweck

Diese Seite richtet sich an Entwickler, die Nova-shell erweitern oder warten.

## Kernobjekte

Die wichtigsten Entwicklungszonen sind Module und Verzeichnisse.

## Methoden und Schnittstellen

### Projektzonen

| Bereich | Ort | Verantwortung |
| --- | --- | --- |
| Shell-Runtime | `nova_shell.py` | CLI, Engines, Befehlsrouter |
| Parser | `nova/parser/` | Nova-Language-Parsing und AST |
| Graph | `nova/graph/` | AST-zu-DAG-Kompilation |
| Runtime | `nova/runtime/` | deklarative Laufzeit und Plattformdienste |
| Agents | `nova/agents/` | Agent-Runtime, Prompting, Memory, Evals |
| Events | `nova/events/` | Event-Typen und Event-Bus |
| Mesh | `nova/mesh/` | Registry, Protokoll und verteilte Ausfuehrung |
| Toolchain | `nova/toolchain/` | Imports, Lockfiles, Formatter, Tests |

### Typische Erweiterungspunkte

#### Neue Sprachbausteine

- `nova/parser/parser.py`
- `nova/parser/ast.py`
- `nova/graph/compiler.py`
- `nova/graph/model.py`
- `nova/runtime/runtime.py`

#### Neue API-Endpunkte

- `nova/runtime/api.py`
- `nova/runtime/runtime.py`

#### Neue Agent-Features

- `nova/agents/runtime.py`
- `nova/agents/providers.py`
- `nova/agents/prompts.py`
- `nova/agents/memory.py`
- `nova/agents/evals.py`
- `nova/agents/sandbox.py`

#### Neue Toolchain-Funktionen

- `nova/toolchain/loader.py`
- `nova/toolchain/registry.py`
- `nova/toolchain/formatter.py`
- `nova/toolchain/linter.py`
- `nova/toolchain/lsp.py`
- `nova/toolchain/testing.py`

## CLI

Entwicklungsnahe Kommandos:

- `ns.graph`
- `ns.format`
- `ns.lint`
- `ns.test`
- `ns.control`
- `mesh start-worker`

## API

Fuer Integrations- und Plattformtests ist vor allem die Control-Plane-API relevant.
Details stehen in [APIReference](./APIReference.md).

## Beispiele

### Testen

```bash
python -m unittest tests.test_build_release
python -m unittest tests.test_nova_language
python -m unittest tests.test_nova_shell
```

### Dokumentationspflicht fuer neue Features

Wenn neue Kernfeatures dazukommen, aktualisiere mindestens:

- [NovaRuntime](./NovaRuntime.md)
- [APIReference](./APIReference.md)
- [ClassReference](./ClassReference.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)

## Verwandte Seiten

- [RepositoryStructure](./RepositoryStructure.md)
- [ClassReference](./ClassReference.md)
- [ParserAndASTReference](./ParserAndASTReference.md)
- [RuntimeMethodReference](./RuntimeMethodReference.md)
- [PageTemplate](./PageTemplate.md)
