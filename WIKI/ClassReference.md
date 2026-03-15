# Class Reference

## Zweck

Diese Seite ist die zentrale Klassenreferenz der Nova-shell-Wiki.
Sie ersetzt keine API-Doku, sondern erklaert die wichtigsten Typen nach Verantwortungsbereich, damit Entwickler schnell die richtigen Einstiegspunkte finden.

## Kernobjekte

### Parser und Sprachmodell

| Klasse | Modul | Zweck | Typische Nutzung |
| --- | --- | --- | --- |
| `NovaParser` | `nova.parser.parser` | Liest `.ns`-Quelltext und erzeugt eine `NovaAST`. | Parser fuer Dateien, Strings und Syntax-Erweiterungen |
| `NovaAST` | `nova.parser.ast` | Oberster AST-Knoten eines Nova-Programms. | Uebergabe an Compiler und Toolchain |
| `ImportDeclaration` | `nova.parser.ast` | Repraesentiert `import`-Anweisungen. | Modulaufloesung und Lockfile-Erstellung |
| `AgentDeclaration` | `nova.parser.ast` | Beschreibt einen Agenten-Block. | Agent-Definitionen in `.ns` |
| `DatasetDeclaration` | `nova.parser.ast` | Beschreibt ein Dataset. | Data- und Sensor-Pipelines |
| `ToolDeclaration` | `nova.parser.ast` | Deklarative Tool-Definition. | Tool-Routing in Runtime und Agenten |
| `ServiceDeclaration` | `nova.parser.ast` | Deklarative Service-Beschreibung. | Service Fabric und Traffic Plane |
| `PackageDeclaration` | `nova.parser.ast` | Paketmetadaten fuer Module und Distribution. | Toolchain, Registry, Dependencies |
| `FlowDeclaration` | `nova.parser.ast` | Enthaelt einen Ausfuehrungsfluss. | DAG-Compiler und Scheduler |
| `FlowStep` | `nova.parser.ast` | Ein einzelner Schritt in einem Flow. | Kanten- und Node-Erzeugung |

### Beispiel

```python
from nova.parser.parser import NovaParser

source = """
agent researcher {
  model: llama3
}

flow radar {
  researcher summarize tech_rss
}
"""

parser = NovaParser()
ast = parser.parse(source, source_name="radar.ns")
print(ast.flows[0].name)
```

### Graph und Kompilierung

| Klasse | Modul | Zweck | Typische Nutzung |
| --- | --- | --- | --- |
| `NovaGraphCompiler` | `nova.graph.compiler` | Uebersetzt `NovaAST` in einen `ExecutionGraph`. | Vor jeder deklarativen Ausfuehrung |
| `ExecutionGraph` | `nova.graph.model` | Enthaelt Knoten, Kanten und Metadaten eines Programms. | Scheduler, Visualisierung, Analyse |
| `ExecutionEdge` | `nova.graph.model` | Verbindet Knoten im Graph. | Daten- und Kontrollfluss |
| `AgentNode` | `nova.graph.model` | Graph-Repraesentation eines Agenten. | Agent-Orchestrierung |
| `DatasetNode` | `nova.graph.model` | Graph-Repraesentation eines Datasets. | Eingabe- und Persistenzknoten |
| `ToolNode` | `nova.graph.model` | Graph-Repraesentation eines Tools. | Externe Aktionen und Executor-Routing |
| `ServiceNode` | `nova.graph.model` | Repraesentiert einen Service in der Service Fabric. | Deployment und Routing |
| `PackageNode` | `nova.graph.model` | Repraesentiert ein Paket im Graph. | Registry und Abhaengigkeiten |
| `FlowNode` | `nova.graph.model` | Steuert Flow-spezifische Ausfuehrung. | Entry-Points und Flow-Steuerung |
| `EventNode` | `nova.graph.model` | Reagiert auf Bus- oder Runtime-Ereignisse. | Event-gesteuerte Automatisierung |

### Beispiel

```python
from nova.parser.parser import NovaParser
from nova.graph.compiler import NovaGraphCompiler

parser = NovaParser()
ast = parser.parse_file("examples/market_radar.ns")
graph = NovaGraphCompiler().compile(ast)

for node in graph.nodes:
    print(node.kind, node.name)
```

### Runtime und Control Plane

| Klasse | Modul | Zweck | Typische Nutzung |
| --- | --- | --- | --- |
| `NovaRuntime` | `nova.runtime.runtime` | Zentrale deklarative Runtime. | Laden, Kompilieren, Ausfuehren, API, Scheduling |
| `RuntimeContext` | `nova.runtime.context` | Buendelt Services der Runtime. | Dependency Injection |
| `CompiledNovaProgram` | `nova.runtime.runtime` | Haelt AST, Graph und Zusatzmetadaten. | Zwischenschritt zwischen Parser und Laufzeit |
| `NovaRuntimeResult` | `nova.runtime.runtime` | Ergebnisobjekt einer Ausfuehrung. | Status, Outputs, Fehler |
| `BackendRouter` | `nova.runtime.backends` | Mappt Tool- oder Executor-Aufrufe auf Backends. | `py/cpp/gpu/wasm/ai/system` |
| `DurableControlPlane` | `nova.runtime.control_plane` | Queue, Scheduler, Replay und durable Task-Steuerung. | Hintergrundarbeit und Wiederanlauf |
| `ControlPlaneConsensus` | `nova.runtime.consensus` | Konsens- und Replikationsschicht. | Multi-Node Ownership und Commit |
| `NovaControlPlaneAPIServer` | `nova.runtime.api` | HTTP-API fuer Verwaltung und Observability. | Control Plane, Automatisierung, Integrationen |
| `RuntimeOperations` | `nova.runtime.operations` | Backup, Restore, Failpoints, Lasttests. | Betriebsreife und Recovery |
| `RuntimeObservability` | `nova.runtime.observability` | Traces, Audit, Event-Historie. | Debugging und Diagnose |

### Beispiel

```python
from nova.runtime.runtime import NovaRuntime

runtime = NovaRuntime()
program = runtime.load("examples/control_plane_runtime.ns")
result = runtime.run(program)

print(result.status)
```

### Agents, Memory und AI-Laufzeit

| Klasse | Modul | Zweck | Typische Nutzung |
| --- | --- | --- | --- |
| `AgentRuntime` | `nova.agents.runtime` | Fuehrt Agentenaufgaben mit Modellen, Tools und Memory aus. | Agent-Tasks im Graph |
| `AgentSpecification` | `nova.agents.runtime` | Konfiguration eines Agenten. | Registrierung und Steuerung |
| `AgentTask` | `nova.agents.runtime` | Ein einzelner Agentenauftrag. | Laufzeit-Dispatch |
| `AgentExecutionResult` | `nova.agents.runtime` | Ergebnis eines Agentenlaufs. | Protokollierung und Folgefluesse |
| `PromptRegistry` | `nova.agents.prompts` | Versioniert Prompt-Staende. | Governance und Rollout |
| `DistributedMemoryStore` | `nova.agents.memory` | Verteilter Agenten-Speicher. | Kontextsuche und Wiederverwendung |
| `AgentEvalStore` | `nova.agents.evals` | Speichert Eval-Laeufe und Resultate. | Modellvergleich und Regressionserkennung |
| `ToolSandbox` | `nova.agents.sandbox` | Begrenzte Tool-Ausfuehrung fuer Agenten. | Sichere Tool-Nutzung |

### Beispiel

```python
from nova.agents.runtime import AgentRuntime, AgentSpecification, AgentTask

runtime = AgentRuntime()
runtime.register(AgentSpecification(name="researcher", model="gpt-4o-mini"))
result = runtime.execute(AgentTask(agent="researcher", objective="Summarize the feed"))
print(result.output)
```

### Mesh, Worker und Executor

| Klasse | Modul | Zweck | Typische Nutzung |
| --- | --- | --- | --- |
| `MeshRegistry` | `nova.mesh.registry` | Verwaltet Worker-Knoten und Routing. | Remote-Ausfuehrung |
| `WorkerNode` | `nova.mesh.registry` | Beschreibt einen Worker mit Capabilities. | Registrierung und Scheduling |
| `ExecutorTask` | `nova.mesh.protocol` | Standardisierte Remote-Aufgabe. | Executor-Protokoll |
| `ExecutorResult` | `nova.mesh.protocol` | Standardisierte Antwort eines Workers. | Ergebnisuebergabe |
| `NativeExecutorManager` | `nova.runtime.executors` | Startet und verwaltet Backend-Executors. | Native `py/cpp/gpu/wasm/ai`-Pfad |
| `ExecutorDaemon` | `nova.runtime.executor_daemon` | Daemon fuer isolierte Ausfuehrung. | Subprozess-Isolation |

### Beispiel

```python
from nova.mesh.registry import MeshRegistry, WorkerNode

mesh = MeshRegistry()
mesh.register(
    WorkerNode(
        node_id="worker-1",
        endpoint="http://127.0.0.1:9040",
        capabilities={"py", "gpu", "ai"},
    )
)
```

### Toolchain und Entwicklerschnittstellen

| Klasse | Modul | Zweck | Typische Nutzung |
| --- | --- | --- | --- |
| `NovaModuleLoader` | `nova.toolchain.loader` | Loest Module und Imports auf. | Multi-Datei-Programme |
| `ResolvedNovaModule` | `nova.toolchain.loader` | Repraesentiert ein geladenes Modul. | Toolchain-Analyse |
| `LoadedNovaProgram` | `nova.toolchain.loader` | Vollstaendig geladenes Programm inkl. Abhaengigkeiten. | Kompilierung und Tests |
| `NovaPackageRegistry` | `nova.toolchain.registry` | Paketpublikation und -aufloesung. | Wiederverwendbare Module |
| `NovaFormatter` | `nova.toolchain.formatter` | Formatiert `.ns`-Quelltext. | Style-Konsistenz |
| `NovaLinter` | `nova.toolchain.linter` | Statische Diagnosen fuer `.ns`. | Qualitaetspruefung |
| `NovaLanguageServerFacade` | `nova.toolchain.lsp` | Editor-nahe Informationen wie Hover und Symbole. | IDE-Integration |
| `NovaTestRunner` | `nova.toolchain.testing` | Fuehrt deklarative Programmtets aus. | Projektweite `.ns`-Tests |
| `NovaTestSuiteResult` | `nova.toolchain.testing` | Zusammenfassung eines Testlaufs. | CI und Regressionen |

### Beispiel

```python
from nova.toolchain.loader import NovaModuleLoader
from nova.toolchain.testing import NovaTestRunner

loader = NovaModuleLoader()
program = loader.load("examples/distributed_pipeline.ns")

runner = NovaTestRunner()
result = runner.run(program)
print(result.passed)
```

### Legacy- und Shell-Klassen

Die Datei `nova_shell.py` enthaelt weiterhin die interaktive Shell, Engines und Integrationsschichten.
Die wichtigsten Einstiegspunkte sind:

| Klasse | Modul | Zweck |
| --- | --- | --- |
| `NovaShell` | `nova_shell` | Interaktive Shell und Kommandorouter |
| `NovaShellCommandExecutor` | `nova_shell` | Fuehrt Shell-Kommandos aus |
| `PythonEngine` | `nova_shell` | Python-Ausfuehrung fuer die klassische Runtime |
| `CppEngine` | `nova_shell` | C++-Build- und Laufpfad |
| `GPUEngine` | `nova_shell` | GPU-bezogene Operationen |
| `WasmEngine` | `nova_shell` | WASM- und Sandbox-Ausfuehrung |
| `RemoteEngine` | `nova_shell` | Remote-Compute und Mesh-Bruecke |
| `NovaAtheriaRuntime` | `nova_shell` | Atheria-Integration im Shell-Pfad |
| `NovaAIProviderRuntime` | `nova_shell` | Provider-Bruecke fuer AI-Aufrufe |

## Methoden und Schnittstellen

Diese Seite dokumentiert vor allem Typen.
Methodendetails stehen in den spezialisierten Referenzseiten:

- [ParserAndASTReference](./ParserAndASTReference.md)
- [RuntimeMethodReference](./RuntimeMethodReference.md)
- [APIReference](./APIReference.md)

## CLI

Shell-Klassen werden ueber die interaktive CLI sichtbar.
Runtime- und Toolchain-Klassen werden ueber `ns.*`, Tests und API-Pfade genutzt.

## API

Die API-relevanten Klassen sind vor allem:

- `NovaControlPlaneAPIServer`
- `DurableControlPlane`
- `ControlPlaneConsensus`

## Beispiele

Die Codebeispiele in den einzelnen Abschnitten zeigen typische Konstruktion und Nutzung.

## Verwandte Seiten

- Parser und Sprache: [ParserAndASTReference](./ParserAndASTReference.md)
- Runtime-Methoden: [RuntimeMethodReference](./RuntimeMethodReference.md)
- Nutzungsbeispiele: [ExamplesAndRecipes](./ExamplesAndRecipes.md)
- [PageTemplate](./PageTemplate.md)
