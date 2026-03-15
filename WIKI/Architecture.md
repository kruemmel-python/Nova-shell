# Architecture

## Zweck

Nova-shell ist als mehrschichtige Plattform aufgebaut.
Der wichtigste Architekturpunkt ist die Trennung zwischen:

- interaktiver Shell- und Befehlsruntime
- deklarativer Nova-Language-Toolchain
- AI-OS- und Control-Plane-Schicht

## Kernobjekte

```text
User
  ↓
CLI / Nova Language
  ↓
Parser / Module Loader / Toolchain
  ↓
Graph Compiler
  ↓
Runtime
  ├ Execution Engines
  ├ Agent Runtime
  ├ Event Bus
  ├ Memory and Atheria
  ├ Mesh and Executors
  ├ Service Fabric
  ├ Traffic Plane
  ├ Security and Policy
  └ Observability and Operations
```

Wichtige Architekturkomponenten:

- `NovaShell`
- `NovaParser`
- `NovaGraphCompiler`
- `NovaRuntime`
- `AgentRuntime`
- `MeshRegistry`
- `NovaControlPlaneAPIServer`
- `ServiceFabric`
- `ServiceTrafficPlane`

## Methoden und Schnittstellen

### Die zwei Laufzeitpfade

#### Shell-Runtime

Die Shell-Runtime in `nova_shell.py` stellt die interaktive Ausfuehrung bereit.
Sie enthaelt unter anderem:

- `PythonEngine`
- `CppEngine`
- `GPUEngine`
- `WasmEngine`
- `EventBus`
- `MeshScheduler`
- `NovaVectorMemory`
- `NovaAtheriaRuntime`
- `NovaAIProviderRuntime`
- `NovaShell`

#### Deklarative Nova-Runtime

Die neue Schicht unter `nova/` ist fuer `.ns`-Programme gebaut.
Ihr Kernpfad lautet:

```text
NovaParser
  ↓
NovaAST
  ↓
NovaGraphCompiler
  ↓
ExecutionGraph
  ↓
NovaRuntime
```

### Schichten im Detail

#### 1. Frontend-Schicht

Besteht aus:

- CLI-Kommandos
- `.ns`-Quelldateien
- Toolchain-Komponenten wie Loader, Formatter, Linter und LSP

#### 2. Modell- und Compiler-Schicht

Diese Schicht beschreibt Ressourcen und baut daraus einen gerichteten Ausfuehrungsgraphen.

Wichtige Klassen:

- `NovaParser`
- `NovaAST`
- `AgentDeclaration`
- `DatasetDeclaration`
- `FlowDeclaration`
- `EventDeclaration`
- `ExecutionGraph`
- `NovaGraphCompiler`

#### 3. Runtime-Schicht

Die Runtime laedt Programme, registriert Ressourcen, fuehrt Flows aus, emittiert Events und betreibt Plattformdienste.

Wichtige Klasse:

- `NovaRuntime`

#### 4. Agent- und Knowledge-Schicht

Diese Schicht fuehrt modellgestuetzte Aufgaben aus und verbindet sie mit Memory, Prompt-Registry, Evaluationsdaten und Atheria.

#### 5. Mesh- und Executor-Schicht

Diese Schicht erlaubt lokale und entfernte Ausfuehrung.

#### 6. Plattform- und Control-Plane-Schicht

Diese Schicht macht Nova-shell zu einer Betriebsplattform und nicht nur zu einem Agent-Framework.

## CLI

Architekturrelevante CLI-Einstiege:

- `ns.run`
- `ns.graph`
- `ns.control`
- `mesh`
- `agent`
- `service`

## API

Architekturrelevante HTTP-Schicht:

- `NovaControlPlaneAPIServer`
- Status-, Queue-, Service-, Traffic- und Metrics-Endpunkte

## Beispiele

Minimales Architekturbeispiel:

```text
market_radar.ns
  -> NovaParser
  -> NovaGraphCompiler
  -> NovaRuntime.run()
  -> AgentRuntime / BackendRouter / MeshRegistry
```

## Verwandte Seiten

- [SystemOverview](./SystemOverview.md)
- [ComponentModel](./ComponentModel.md)
- [NovaLanguage](./NovaLanguage.md)
- [NovaRuntime](./NovaRuntime.md)
- [ClassReference](./ClassReference.md)
- [PageTemplate](./PageTemplate.md)

## Architekturprinzipien

- deklarative Systembeschreibung statt rein imperativer Loops
- graphbasierte Ausfuehrung statt linearer Skriptketten
- agent-native Workflows
- eventgetriebene Automation
- modulare Backends fuer lokale und verteilte Ausfuehrung
- Plattformzustaende persistent unter `.nova/`
