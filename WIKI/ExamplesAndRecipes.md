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
- `blob.*`
- `synth.*`
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

### 11. Standalone Agenten aus `agent-skills-main` erzeugen

```powershell
ns.skills build agent-skills-main .\examples
ns.run .\examples\react_best_practices_agents.ns
agent list
agent run react_best_practices_router "Ich habe serielle Fetches, zu grosse Bundles und viele Re-Renders."
agent run react_best_practices_async_parallel "const user = await fetchUser(); const posts = await fetchPosts();"
```

Erwartung:

- pro Skill-Buendel entsteht eine eigenstaendige `.ns`-Datei in `examples/`
- `agent list` zeigt danach die generierten Agenten direkt in der Shell
- `agent run` arbeitet gegen die geladene `.ns`-Datei, nicht mehr gegen den Rohordner

### 12. Backup und Restore

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

### 15. Blob-Seed lokal erzeugen und ausfuehren

```powershell
blob pack --text "21 * 2" --type py
blob verify .\calc.nsblob.json
blob exec .\calc.nsblob.json
```

### 16. Blob-Seed in deklarativer Runtime nutzen

```powershell
ns.graph examples\blob_runtime.ns
ns.run examples\blob_runtime.ns
```

### 17. Blob-Seed ueber Mesh verschieben

```powershell
mesh start-worker --caps cpu,py
blob mesh-run cpu .\calc.nsblob.json
```

### 18. Predictive Engine Shift testen

```powershell
py 1 + 1
py 2 + 1
py 3 + 1
synth forecast
synth shift suggest "for item in rows: total += item"
```

Wenn genug Telemetrie vorhanden ist, liefert Nova-shell neben einer Engine-Empfehlung auch einen `delegated_command`.

### 19. Federated Invariant im Mesh publizieren

```powershell
mesh federated publish --statement "Inter-core resonance raised" --namespace swarm --project lab --broadcast
mesh federated history 5
```

Fuer same-host zero-copy:

```powershell
zero put federated-invariant-payload
mesh federated publish --statement "Shared invariant" --handle <HANDLE> --size <SIZE> --type text --same-host
```

### 20. Aion-Chronik direkt ins Mesh uebertragen

```powershell
mesh federated chronik-latest --namespace atheria --project swarm --broadcast
```

### 21. Mycelia-Atheria Co-Evolution laufen lassen

```powershell
mycelia coevolve run research-pop --cycles 3 --input "edge inference pressure rises"
mycelia coevolve status research-pop
```

### 22. Beispielprogramme fuer Federated Memory und Co-Evolution vorbereiten

```powershell
ns.graph examples\federated_swarm_memory.ns
ns.run examples\federated_swarm_memory.ns

ns.graph examples\mycelia_coevolution_lab.ns
ns.run examples\mycelia_coevolution_lab.ns
```

## Verwandte Seiten

- [NSBlobGenerator](./NSBlobGenerator.md)
- [NovaSynthPredictiveEngineShifting](./NovaSynthPredictiveEngineShifting.md)
- [ZeroCopyFederatedLearningMesh](./ZeroCopyFederatedLearningMesh.md)
- [MyceliaAtheriaCoEvolution](./MyceliaAtheriaCoEvolution.md)
- [TutorialPredictiveFederatedCoevolution](./TutorialPredictiveFederatedCoevolution.md)

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

### 16. Einen Projektordner live ueberwachen

Lege `nova_project_monitor.ns` in den Projektordner und starte den Monitor direkt dort:

```powershell
cd F:\DeCoG-TRI
ns.run nova_project_monitor.ns
```

Sicherer Erstlauf:

```powershell
$env:NOVA_PROJECT_MONITOR_ONESHOT = "1"
$env:NOVA_PROJECT_MONITOR_OPEN = "0"
ns.run nova_project_monitor.ns
```

Mit Build/Test-Checks und AI-Review:

```powershell
$env:NOVA_PROJECT_MONITOR_AUTOMATION = "auto"
$env:NOVA_PROJECT_MONITOR_AI_MODE = "auto"
ns.run nova_project_monitor.ns
```

Erwartung:

- `.nova_project_monitor/project_monitor_report.html` wird aktualisiert
- geaenderte Dateien erhalten Detailseiten
- Review-Agent und Build-/Test-Ergebnisse erscheinen im Report

### 17. Windows-Persistenz und Temp-Ausfuehrung gezielt ueberwachen

Lege `nova_system_guard.ns` in ein Arbeitsverzeichnis und starte den Guard:

```powershell
ns.run nova_system_guard.ns
```

Nur die Guard-Logik gegen eigene Testpfade laufen lassen:

```powershell
$env:NOVA_SYSTEM_GUARD_INCLUDE_DEFAULTS = "0"
$env:NOVA_SYSTEM_GUARD_INCLUDE_PROJECT = "off"
$env:NOVA_SYSTEM_GUARD_PATHS = "C:/lab/startup;C:/lab/temp"
$env:NOVA_SYSTEM_GUARD_ONESHOT = "1"
$env:NOVA_SYSTEM_GUARD_OPEN = "0"
ns.run nova_system_guard.ns
```

Mit Live-Dateisystem-Events:

```powershell
$env:NOVA_SYSTEM_GUARD_WATCH_MODE = "auto"
ns.run nova_system_guard.ns
```

Mit Quarantaene fuer neue Hochrisiko-Dateien:

```powershell
$env:NOVA_SYSTEM_GUARD_ACTION = "high"
ns.run nova_system_guard.ns
```

Erwartung:

- `.nova_system_guard/system_guard_report.html` wird aktualisiert
- kritische Windows-Pfade wie Startup, Temp, Downloads und Treiberbereiche werden fokussiert bewertet
- Textbasierte Aenderungen wie `.bat` oder `.ps1` erscheinen mit Zeilen-Diff und Detailseite
- Scheduled Tasks, Registry Run Keys sowie Signatur-/Publisher-Status erscheinen im Report

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
- [WatchMonitor](./WatchMonitor.md)
- [SystemGuardMonitor](./SystemGuardMonitor.md)
- [WatchMonitorQuickStart](./WatchMonitorQuickStart.md)
