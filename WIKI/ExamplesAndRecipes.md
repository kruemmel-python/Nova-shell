# Examples and Recipes

## Zweck

Diese Seite sammelt kurze, konkrete Beispiele.
Sie soll zeigen, wie Nova-shell in der Praxis benutzt wird, ohne dass man sich zuerst durch alle Architekturtexte arbeiten muss.

## Kernobjekte

Die Beispiele nutzen vor allem diese Einstiegspunkte:

- `NovaRuntime`
- `NovaParser`
- `NovaGraphCompiler`
- `AgentRuntime`
- `MeshRegistry`
- `NovaModuleLoader`

## Methoden und Schnittstellen

Die Rezepte drehen sich vor allem um:

- `run`
- `compile`
- `enqueue_flow`
- `start_control_api`
- `deploy_service`
- `format_source`
- `lint_source`
- `run_program_tests`

## CLI

Hauefige Beispielkommandos:

- `ns.run`
- `ns.graph`
- `ns.control`
- `mesh.*`
- `ns.format`
- `ns.lint`
- `ns.test`

## API

Mehrere Beispiele fuehren zur HTTP-Control-Plane.
Die zugehoerigen Endpunkte sind in [APIReference](./APIReference.md) beschrieben.

## Beispiele

### 1. Erstes `.ns`-Programm ausfuehren

Datei `radar.ns`:

```nova
dataset tech_rss {
  source: rss
}

agent researcher {
  model: gpt-4o-mini
}

flow radar {
  rss.fetch tech_rss
  researcher summarize tech_rss
}
```

CLI:

```powershell
ns.run radar.ns
```

Python:

```python
from nova.runtime.runtime import NovaRuntime

runtime = NovaRuntime()
program = runtime.load("radar.ns")
result = runtime.run(program)
print(result.status)
```

### 2. Ein Programm nur kompilieren und den Graph inspizieren

```python
from nova.parser.parser import NovaParser
from nova.graph.compiler import NovaGraphCompiler

parser = NovaParser()
ast = parser.parse_file("examples/market_radar.ns")
graph = NovaGraphCompiler().compile(ast)

print("Nodes:", len(graph.nodes))
print("Edges:", len(graph.edges))
```

Typischer Zweck:

- neue Flows verstehen
- Toolchain oder Linter erweitern
- Scheduling und Knotenaufbau debuggen

### 3. Agent registrieren und ausfuehren

```python
from nova.agents.runtime import AgentRuntime, AgentSpecification, AgentTask

agents = AgentRuntime()
agents.register(
    AgentSpecification(
        name="researcher",
        model="gpt-4o-mini",
        tools=["web.search", "atheria.embed"],
    )
)

result = agents.execute(
    AgentTask(
        agent="researcher",
        objective="Summarize the latest technical feed",
    )
)
print(result.output)
```

### 4. Einen Flow in die durable Queue legen

```python
from nova.runtime.runtime import NovaRuntime

runtime = NovaRuntime()
program = runtime.load("examples/control_plane_runtime.ns")
runtime.enqueue_flow("cluster_radar", program=program, priority="high")
runtime.scheduler_tick()
runtime.run_pending_tasks()
```

### 5. Control-Plane-API starten

```python
from nova.runtime.runtime import NovaRuntime

runtime = NovaRuntime()
status = runtime.start_control_api(host="127.0.0.1", port=9850)
print(status)
```

Danach koennen HTTP-Clients gegen die API arbeiten:

```powershell
curl http://127.0.0.1:9850/status
```

### 6. Service deployen und skalieren

```python
from nova.runtime.runtime import NovaRuntime

runtime = NovaRuntime()
runtime.install_package("analytics", source="./packages/analytics", version="1.0.0")
runtime.deploy_service("analytics-api", package="analytics", replicas=2)
runtime.scale_service("analytics-api", 4)
```

### 7. Mesh-Worker registrieren

```python
from nova.mesh.registry import MeshRegistry, WorkerNode

mesh = MeshRegistry()
mesh.register(
    WorkerNode(
        node_id="worker-gpu-1",
        endpoint="http://127.0.0.1:9040",
        capabilities={"gpu", "py", "ai"},
    )
)
```

CLI-Beispiel:

```powershell
mesh.add http://127.0.0.1:9040 --capabilities gpu,py,ai
mesh.list
```

### 8. Module und Imports nutzen

Datei `main.ns`:

```nova
import "agents/research.ns"
import "flows/radar.ns"
```

Toolchain:

```python
from nova.toolchain.loader import NovaModuleLoader

loader = NovaModuleLoader()
program = loader.load("main.ns")
loader.write_lockfile("nova.lock")
```

### 9. Formatieren, linten und testen

```python
from nova.runtime.runtime import NovaRuntime

runtime = NovaRuntime()
formatted = runtime.format_source("examples/market_radar.ns")
diagnostics = runtime.lint_source("examples/market_radar.ns")
tests = runtime.run_program_tests("examples/market_radar.ns")

print(formatted)
print(diagnostics)
print(tests)
```

CLI:

```powershell
ns.format examples\market_radar.ns
ns.lint examples\market_radar.ns
ns.test examples\market_radar.ns
```

### 10. Backup und Restore

```python
from nova.runtime.runtime import NovaRuntime

runtime = NovaRuntime()
runtime.create_backup(".nova/backups/backup-001")
runtime.restore_backup(".nova/backups/backup-001")
```

### 11. Atheria und Memory nutzen

```python
from nova.runtime.runtime import NovaRuntime

runtime = NovaRuntime()
runtime.emit("new_information", {"topic": "gpu_runtime"})
matches = runtime.search_agent_memory("researcher", "gpu runtime")
print(matches)
```

### 12. Minimaler Multi-Agent-Flow

```nova
agent collector {
  model: gpt-4o-mini
}

agent reviewer {
  model: gpt-4o-mini
}

dataset findings {
  source: memory
}

flow review_loop {
  collector summarize findings
  reviewer critique findings
}
```

### 13. Service mit Traffic-Shift vorbereiten

```python
from nova.runtime.runtime import NovaRuntime

runtime = NovaRuntime()
runtime.deploy_service("frontend-blue", image="frontend:blue", replicas=2)
runtime.deploy_service("frontend-green", image="frontend:green", replicas=2)
runtime.start_traffic_proxy(host="127.0.0.1", port=9900)
```

### 14. Typische Entwicklungsrezepte

#### Neue Sprachsyntax testen

1. `.ns`-Beispiel erstellen
2. mit `NovaParser.parse` parsen
3. AST in `ParserAndASTReference` gegenpruefen
4. Graph mit `NovaGraphCompiler.compile` inspizieren
5. Runtime-Test mit `NovaTestRunner` schreiben

#### Neue Runtime-Funktion dokumentieren

1. Methode in `NovaRuntime` oder Subsystem identifizieren
2. Referenzseite aktualisieren
3. mindestens ein kurzes Beispiel in diese Seite aufnehmen

## Verwandte Seiten

- [ClassReference](./ClassReference.md)
- [RuntimeMethodReference](./RuntimeMethodReference.md)
- [NovaCLI](./NovaCLI.md)
- [Tutorials](./Tutorials.md)
- [PageTemplate](./PageTemplate.md)
