# Examples and Recipes

## Zweck

Diese Seite sammelt kurze, konkrete Beispiele.
Sie soll zeigen, wie Nova-shell in der Praxis benutzt wird, ohne dass man sich zuerst durch alle Architekturtexte arbeiten muss.

## Einstiegspunkte

Die Rezepte nutzen vor allem diese Objekte und Systeme:

- `NovaRuntime`
- `NovaParser`
- `NovaGraphCompiler`
- `AgentRuntime`
- `MeshRegistry`
- `NovaModuleLoader`

## Typische Methoden und Schnittstellen

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
- `wiki.*`

## API

Mehrere Beispiele fuehren zur HTTP-Control-Plane.
Die zugehoerigen Endpunkte sind in [APIReference](./APIReference.md) beschrieben.

## Rezepte

### 1. Erstes `.ns`-Programm ausfuehren

Datei `radar.ns`:

```ns
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

### 3. Laufzeit direkt aus Python verwenden

```python
from nova.runtime.runtime import NovaRuntime

runtime = NovaRuntime()
result = runtime.run("examples/market_radar.ns")
print(result.status)
```

### 4. Agent registrieren und ausfuehren

```python
from nova.agents.runtime import AgentRuntime, AgentSpecification, AgentTask

agents = AgentRuntime()
agents.register(
    AgentSpecification(
        name="researcher",
        model="gpt-4o-mini",
        tools=["system.log"],
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

### 5. Einen Flow in die durable Queue legen

```python
from nova.runtime.runtime import NovaRuntime

runtime = NovaRuntime()
program = runtime.load("examples/control_plane_runtime.ns")
runtime.enqueue_flow("cluster_radar", program=program, priority="high")
runtime.scheduler_tick()
runtime.run_pending_tasks()
```

### 6. Control-Plane-API starten

```python
from nova.runtime.runtime import NovaRuntime

runtime = NovaRuntime()
status = runtime.start_control_api(host="127.0.0.1", port=9850)
print(status)
```

Danach:

```powershell
curl http://127.0.0.1:9850/status
```

### 7. Service deployen und skalieren

```python
from nova.runtime.runtime import NovaRuntime

runtime = NovaRuntime()
runtime.install_package("analytics", source="./packages/analytics", version="1.0.0")
runtime.deploy_service("analytics-api", package="analytics", replicas=2)
runtime.scale_service("analytics-api", 4)
```

### 8. Mesh-Worker registrieren

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

### 9. Module und Imports nutzen

Datei `main.ns`:

```ns
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

### 10. Formatieren, linten und testen

```powershell
ns.format examples\market_radar.ns
ns.lint examples\market_radar.ns
ns.test examples\market_radar.ns
```

### 11. Backup und Restore

```python
from nova.runtime.runtime import NovaRuntime

runtime = NovaRuntime()
runtime.create_backup(".nova/backups/backup-001")
runtime.restore_backup(".nova/backups/backup-001")
```

### 12. Atheria und Memory nutzen

```python
from nova.runtime.runtime import NovaRuntime

runtime = NovaRuntime()
runtime.emit("new_information", {"topic": "gpu_runtime"})
matches = runtime.search_agent_memory("researcher", "gpu runtime")
print(matches)
```

### 13. Minimaler Multi-Agent-Flow

```ns
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

### 14. Service mit Traffic-Shift vorbereiten

```python
from nova.runtime.runtime import NovaRuntime

runtime = NovaRuntime()
runtime.deploy_service("frontend-blue", image="frontend:blue", replicas=2)
runtime.deploy_service("frontend-green", image="frontend:green", replicas=2)
runtime.start_traffic_proxy(host="127.0.0.1", port=9900)
```

### 15. Die Wiki als HTML-Site bauen und oeffnen

```powershell
wiki build
wiki serve --open
```

Mit expliziten Pfaden:

```powershell
wiki build --source WIKI --output .nova\wiki-site
wiki open Home --source WIKI --output .nova\wiki-site --port 8767
```

## Wann diese Seite benutzt werden sollte

Diese Seite ist ideal, wenn du:

- ein neues Subsystem schnell ausprobieren willst
- eine Beispielbasis fuer Tests oder Doku brauchst
- einen realistischen Startpunkt vor der tieferen Referenz suchst

## Verwandte Seiten

- [NovaCLI](./NovaCLI.md)
- [ProgrammingWithNovaShell](./ProgrammingWithNovaShell.md)
- [ClassReference](./ClassReference.md)
- [RuntimeMethodReference](./RuntimeMethodReference.md)
- [Tutorials](./Tutorials.md)
