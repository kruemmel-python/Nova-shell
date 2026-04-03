# examples_quickstart

Diese Seite ist die Copy-Paste-Version zu [`examples.md`](./examples.md).
Hier stehen die vorhandenen Beispiele aus [`examples/`](../examples/) so, dass du sie schnell starten, inspizieren und ausprobieren kannst.

## Vorbereitung

Alle Befehle sind fuer den Repository-Root `H:\Nova-shell-main` geschrieben.

### AI-Provider einmal aktivieren

Viele Agentenbeispiele nutzen `provider: shell` und `model: active`. Dafuer zuerst einen aktiven Provider setzen:

```powershell
ai use lmstudio <modellname>
ai config
```

### Struktur statt Ausfuehrung

Wenn du ein groesseres Beispiel erst lesen willst:

```powershell
ns.graph .\examples\<beispiel>.ns
```

## Sofort lokal nutzbare Beispiele

### [`examples/blob_runtime.ns`](../examples/blob_runtime.ns)

```powershell
ns.run .\examples\blob_runtime.ns
```

Prueft und entpackt das Seed-Artefakt [`examples/blob_runtime_seed.nsblob.json`](../examples/blob_runtime_seed.nsblob.json).

### [`examples/file_extension_scan.ns`](../examples/file_extension_scan.ns)

```powershell
ns.run .\examples\file_extension_scan.ns
```

Erzeugt einen JSON-Report mit Dateigruppen nach Endung fuer das aktuelle Verzeichnis.

### [`examples/file_extension_scan_advanced.ns`](../examples/file_extension_scan_advanced.ns)

```powershell
ai use lmstudio <modellname>
ns.run .\examples\file_extension_scan_advanced.ns
```

Fuehrt einen rekursiven Scan aus, erzeugt Summary, Agentenbewertung und HTML-Report.

### [`examples/decision_lifecycle_template.ns`](../examples/decision_lifecycle_template.ns)

```powershell
ai use lmstudio <modellname>
ns.run .\examples\decision_lifecycle_template.ns
```

Zeigt einen kompletten Decision-Lifecycle mit mehreren Agentenrollen.

### [`examples/market_radar.ns`](../examples/market_radar.ns)

```powershell
ai use lmstudio <modellname>
ns.run .\examples\market_radar.ns
```

Liest Markt- und RSS-Signale, bettet sie ein und erstellt eine Kurzbewertung.

### [`examples/federated_swarm_memory.ns`](../examples/federated_swarm_memory.ns)

```powershell
ai use lmstudio <modellname>
ns.run .\examples\federated_swarm_memory.ns
```

Verdichtet lokale Findings zu einem federierten Memory-Summary.

### [`examples/mycelia_coevolution_lab.ns`](../examples/mycelia_coevolution_lab.ns)

```powershell
ai use lmstudio <modellname>
ns.run .\examples\mycelia_coevolution_lab.ns
```

Erzeugt aus mehreren Prompts ein Population-Signal fuer Coevolution-Experimente.

## Plattform-, Mesh- und Clusterbeispiele

Diese Beispiele sind besonders gut fuer `ns.graph` und kontrollierte Runtime-Tests geeignet.

### [`examples/advanced_agent_fabric.ns`](../examples/advanced_agent_fabric.ns)

```powershell
ns.graph .\examples\advanced_agent_fabric.ns
ns.run .\examples\advanced_agent_fabric.ns
```

Zeigt Service-, Package-, Agent- und Alert-Modellierung in einer gemeinsamen Fabric.

### [`examples/ai_os_cluster.ns`](../examples/ai_os_cluster.ns)

```powershell
ns.graph .\examples\ai_os_cluster.ns
ns.run .\examples\ai_os_cluster.ns
```

Demonstriert einen Mesh- und Schedule-faehigen KI-Orchestrator.

### [`examples/consensus_fabric_cluster.ns`](../examples/consensus_fabric_cluster.ns)

```powershell
ns.graph .\examples\consensus_fabric_cluster.ns
ns.run .\examples\consensus_fabric_cluster.ns
```

Zeigt Konsens, Trust Policies, Package und Service in einer Cluster-Konfiguration.

### [`examples/control_plane_runtime.ns`](../examples/control_plane_runtime.ns)

```powershell
ns.graph .\examples\control_plane_runtime.ns
ns.run .\examples\control_plane_runtime.ns
```

Demonstriert Scheduler, Event-Trigger und einfachen Control-Plane-State.

### [`examples/distributed_pipeline.ns`](../examples/distributed_pipeline.ns)

```powershell
ai use lmstudio <modellname>
ns.graph .\examples\distributed_pipeline.ns
ns.run .\examples\distributed_pipeline.ns
```

Zeigt Incident-Triage ueber Mesh, Agent und Tool-Publishing.

### [`examples/replicated_control_plane.ns`](../examples/replicated_control_plane.ns)

```powershell
ns.graph .\examples\replicated_control_plane.ns
ns.run .\examples\replicated_control_plane.ns
```

Zeigt Replikationsendpunkte, Trust Policies und Event-Synchronisation.

### [`examples/secure_multi_tenant.ns`](../examples/secure_multi_tenant.ns)

```powershell
ns.graph .\examples\secure_multi_tenant.ns
ns.run .\examples\secure_multi_tenant.ns
```

Demonstriert Rollen, TLS-Anforderungen und Tenant-Isolation.

### [`examples/service_package_platform.ns`](../examples/service_package_platform.ns)

```powershell
ns.graph .\examples\service_package_platform.ns
ns.run .\examples\service_package_platform.ns
```

Zeigt Package-, Service- und Deployment-Bausteine.

## Standalone-Agentenbundles

### [`examples/composition_patterns_agents.ns`](../examples/composition_patterns_agents.ns)

```powershell
ai use lmstudio <modellname>
ns.run .\examples\composition_patterns_agents.ns
agent list
```

Danach einen Spezialagenten auswaehlen:

```powershell
agent run composition_patterns_router "Ich habe zu viele Boolean-Props in einer React-Komponente."
```

### [`examples/react_best_practices_agents.ns`](../examples/react_best_practices_agents.ns)

```powershell
ai use lmstudio <modellname>
ns.run .\examples\react_best_practices_agents.ns
agent list
```

Dann gezielt nutzen:

```powershell
agent run react_best_practices_router "Pruefe diesen React-Code auf Architektur- und Performance-Probleme."
```

### [`examples/react_native_skills_agents.ns`](../examples/react_native_skills_agents.ns)

```powershell
ai use lmstudio <modellname>
ns.run .\examples\react_native_skills_agents.ns
agent list
```

Dann gezielt nutzen:

```powershell
agent run react_native_skills_router "Pruefe eine Expo-App auf typische React-Native-Probleme."
```

## Monitoring- und Guard-Beispiele

Diese beiden Dateien sind fuer echte Projektordner gedacht und werden typischerweise dorthin kopiert.

### [`examples/nova_project_monitor.ns`](../examples/nova_project_monitor.ns)

Im Zielprojekt:

```powershell
Copy-Item H:\Nova-shell-main\examples\nova_project_monitor.ns . -Force
ns.run .\nova_project_monitor.ns
```

Optional mit One-Shot:

```powershell
$env:NOVA_PROJECT_MONITOR_ONESHOT='1'
ns.run .\nova_project_monitor.ns
```

### [`examples/nova_system_guard.ns`](../examples/nova_system_guard.ns)

Im Zielprojekt oder Arbeitsordner:

```powershell
Copy-Item H:\Nova-shell-main\examples\nova_system_guard.ns . -Force
ns.run .\nova_system_guard.ns
```

Optional mit One-Shot:

```powershell
$env:NOVA_SYSTEM_GUARD_ONESHOT='1'
ns.run .\nova_system_guard.ns
```

## CEO-Beispielsystem

### Router laden

```powershell
ai use lmstudio <modellname>
ns.run .\examples\CEO_ns\CEO_Core.ns
agent run CEO_Core "Ich moechte eine CEO-Entscheidung bei steigender Nachfrage simulieren."
```

### Einzelne Rollen testen

#### [`examples/CEO_ns/StrategyAgent.ns`](../examples/CEO_ns/StrategyAgent.ns)

```powershell
ai use lmstudio <modellname>
ns.run .\examples\CEO_ns\StrategyAgent.ns
agent run StrategyAgent "Enterprise-Nachfrage steigt stark, GPU-Kapazitaet wird knapp."
```

#### [`examples/CEO_ns/RiskAgent.ns`](../examples/CEO_ns/RiskAgent.ns)

```powershell
ai use lmstudio <modellname>
ns.run .\examples\CEO_ns\RiskAgent.ns
agent run RiskAgent "Ein Partner fordert Kapital, waehrend die Kapazitaet knapp wird."
```

#### [`examples/CEO_ns/CapitalAgent.ns`](../examples/CEO_ns/CapitalAgent.ns)

```powershell
ai use lmstudio <modellname>
ns.run .\examples\CEO_ns\CapitalAgent.ns
agent run CapitalAgent "Wir brauchen 250000 Euro fuer eine Kapazitaetserweiterung."
```

#### [`examples/CEO_ns/OperationsAgent.ns`](../examples/CEO_ns/OperationsAgent.ns)

```powershell
ai use lmstudio <modellname>
ns.run .\examples\CEO_ns\OperationsAgent.ns
agent run OperationsAgent "GPU-Auslastung steigt ueber 87 Prozent, Partnerdruck nimmt zu."
```

#### [`examples/CEO_ns/ConsensusLayer.ns`](../examples/CEO_ns/ConsensusLayer.ns)

```powershell
ai use lmstudio <modellname>
ns.run .\examples\CEO_ns\ConsensusLayer.ns
agent run ConsensusLayer "Strategie: expandieren. Risiko: mittel. Kapital: verfuegbar."
```

#### [`examples/CEO_ns/NarrativeAgent.ns`](../examples/CEO_ns/NarrativeAgent.ns)

```powershell
ai use lmstudio <modellname>
ns.run .\examples\CEO_ns\NarrativeAgent.ns
agent run NarrativeAgent "Entscheidung: approve. Aktion: scale_enterprise_capacity."
```

#### [`examples/CEO_ns/ExecutionDispatcher.ns`](../examples/CEO_ns/ExecutionDispatcher.ns)

```powershell
ai use lmstudio <modellname>
ns.run .\examples\CEO_ns\ExecutionDispatcher.ns
agent run ExecutionDispatcher "Entscheidung: approve. Kapital: reserviert. Owner: platform-ops."
```

### Voller Lifecycle

#### [`examples/CEO_ns/CEO_Lifecycle.ns`](../examples/CEO_ns/CEO_Lifecycle.ns)

```powershell
ai use lmstudio <modellname>
ns.run .\examples\CEO_ns\CEO_Lifecycle.ns
```

Danach liegen Artefakte unter `examples\CEO_ns\.nova_ceo\`.

### Kontinuierlicher Runner

#### [`examples/CEO_ns/ceo_continuous_runtime.py`](../examples/CEO_ns/ceo_continuous_runtime.py)

```powershell
python .\examples\CEO_ns\ceo_continuous_runtime.py
```

Einmaliger Zyklus:

```powershell
$env:NOVA_CEO_ONESHOT='1'
python .\examples\CEO_ns\ceo_continuous_runtime.py
```

## Code-Improvement-Beispielsystem

### Standardlauf

#### [`examples/code_improvement_ns/Code_Improve_Lifecycle.ns`](../examples/code_improvement_ns/Code_Improve_Lifecycle.ns)

```powershell
ai use lmstudio <modellname>
ns.run .\examples\code_improvement_ns\Code_Improve_Lifecycle.ns
```

Das nutzt standardmaessig [`examples/code_improvement_ns/code_improvement_request.json`](../examples/code_improvement_ns/code_improvement_request.json) und verarbeitet [`examples/code_improvement_ns/sample_target.py`](../examples/code_improvement_ns/sample_target.py).

### Projektmodus

Projekt-Request aktivieren:

```powershell
Copy-Item .\examples\code_improvement_ns\code_improvement_project_request.json .\examples\code_improvement_ns\code_improvement_request.json -Force
ai use lmstudio <modellname>
ns.run .\examples\code_improvement_ns\Code_Improve_Lifecycle.ns
```

Danach arbeitet der Lifecycle gegen das Demo-Projekt:

- [`examples/code_improvement_ns/demo_project/clean_numbers.py`](../examples/code_improvement_ns/demo_project/clean_numbers.py)
- [`examples/code_improvement_ns/demo_project/reporting.py`](../examples/code_improvement_ns/demo_project/reporting.py)

### Report lesen

Nach dem Lauf:

```powershell
type .\examples\code_improvement_ns\.nova_code_improve\sample_target.report.json
```

## Daten- und Pipeline-Beispiele

### [`examples/items.csv`](../examples/items.csv)

```powershell
data load examples/items.csv
```

Nur Preise:

```powershell
data load examples/items.csv | parallel py row["price"]
```

Mit AI-Zusammenfassung:

```powershell
ai use lmstudio <modellname>
data load examples/items.csv | parallel py row["price"] | ai prompt "Ist das teuer?"
```

Mit Memory:

```powershell
ai use lmstudio <modellname>
data load examples/items.csv | parallel py row["price"] | ai prompt "Ist das teuer?" | memory embed --id price_check
```

### [`examples/items_large.csv`](../examples/items_large.csv)

```powershell
data load examples/items_large.csv
```

### [`examples/blob_runtime_seed.nsblob.json`](../examples/blob_runtime_seed.nsblob.json)

Direkt pruefen:

```powershell
blob verify .\examples\blob_runtime_seed.nsblob.json
```

Direkt entpacken:

```powershell
blob unpack .\examples\blob_runtime_seed.nsblob.json
```

## Wenn du nur drei Dinge ausprobieren willst

```powershell
ns.run .\examples\blob_runtime.ns
```

```powershell
ai use lmstudio <modellname>
ns.run .\examples\CEO_ns\CEO_Lifecycle.ns
```

```powershell
ai use lmstudio <modellname>
ns.run .\examples\code_improvement_ns\Code_Improve_Lifecycle.ns
```

## Verwandte Seiten

- [`examples_index.md`](./examples_index.md)
- [`examples.md`](./examples.md)
- [`examples_by_level.md`](./examples_by_level.md)
- [`examples_matrix.md`](./examples_matrix.md)
- [`ExamplesAndRecipes.md`](./ExamplesAndRecipes.md)
- [`CEOAgentExamples.md`](./CEOAgentExamples.md)
