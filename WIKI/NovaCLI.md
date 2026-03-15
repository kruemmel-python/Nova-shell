# Nova CLI

## Zweck

Die CLI ist die praktische Eintrittsschicht in Nova-shell.
Sie deckt sowohl die bestehende Shell-Runtime als auch den deklarativen Nova-Runtimepfad ab.

## Kernobjekte

- `NovaShell`
- `NovaShellCommandExecutor`
- `CommandResult`
- `MeshWorkerServer`
- `VisionServer`

## Methoden und Schnittstellen

Die CLI ist kommandozentriert.
Die wichtigsten Schnittstellen sind Kommandogruppen, Subkommandos und Shell-Integrationen.

## CLI

### Grundform

Interaktive Nutzung:

```bash
nova-shell
```

Einzelkommando:

```bash
nova-shell --no-plugins -c "py 1 + 1"
```

### Kommandogruppen

#### Compute

| Kommando | Zweck | Beispiel |
| --- | --- | --- |
| `py` | Python-Ausdruecke und Code | `py 1 + 1` |
| `cpp` | native C++-Ausfuehrung | `cpp.sandbox int main(){ return 0; }` |
| `gpu` | GPU/OpenCL-Pfade | `gpu graph show` |
| `wasm` | WebAssembly-Ausfuehrung | `wasm run program.wasm` |
| `sys` | Shell-/Systemaufrufe | `sys dir` |

#### AI und Knowledge

| Kommando | Zweck |
| --- | --- |
| `ai` | Provider, Modelle und Prompts |
| `atheria` | lokales Wissens- und Trainingssystem |
| `agent` | Agenten, Instanzen und Graphen |
| `memory` | Vector Memory und Namespaces |
| `tool` | Tool-Registrierung und Tool-Aufrufe |

#### Deklarative Runtime

| Kommando | Zweck |
| --- | --- |
| `ns.exec` | Inline-Ausfuehrung von Nova-Quelltext |
| `ns.run` | `.ns`-Datei ausfuehren |
| `ns.graph` | kompilierten Graph zeigen |
| `ns.status` | Runtime- und Plattformstatus |
| `ns.control` | Queue, API, Replay, Metrics |
| `ns.snapshot` | Snapshot schreiben |
| `ns.resume` | Snapshot wieder laden |

#### Plattform

| Kommando | Zweck |
| --- | --- |
| `mesh` | Worker und verteilte Ausfuehrung |
| `wiki` | Markdown-Wiki nach HTML bauen, lokal serven und im Browser oeffnen |
| `remote` | Remote-Ausfuehrung |
| `vision` | Web- und UI-Flaechen |
| `guard` | Sicherheits- und Sandbox-Pfade |

## API

Die CLI spricht nicht nur lokal, sondern kann Plattformfunktionen ueber die Control-Plane-API begleiten.
Fuer HTTP-Endpunkte siehe [APIReference](./APIReference.md).

## Beispiele

### Beispielmuster

```text
ai providers
atheria init
memory search "distributed execution"
mesh start-worker --caps py,gpu
ns.run examples/market_radar.ns
ns.control daemon start
wiki serve --open
```

## Verwandte Seiten

- [ExamplesAndRecipes](./ExamplesAndRecipes.md)
- [APIReference](./APIReference.md)
- [ClassReference](./ClassReference.md)
- [PageTemplate](./PageTemplate.md)
