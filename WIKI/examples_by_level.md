# examples_by_level

Diese Seite sortiert die vorhandenen Beispiele aus [`examples/`](../examples/) nicht nach Dateiname, sondern nach Lernstufe und Einsatzzweck.
Sie ist als Orientierung gedacht, wenn du nicht den gesamten Ordner auf einmal durcharbeiten willst.

Verwandte Seiten:

- [`examples_index.md`](./examples_index.md)
  Zentrales Portal fuer die gesamte Examples-Dokumentation.
- [`examples.md`](./examples.md)
  Vollstaendige dateiweise Referenz.
- [`examples_quickstart.md`](./examples_quickstart.md)
  Copy-Paste-Schnellstart.
- [`examples_matrix.md`](./examples_matrix.md)
  Vergleichstabelle nach Kategorie, AI, Mesh und Ergebnisart.

## Wie du diese Seite nutzt

- `Einsteiger`
  Wenn du zuerst einfache lokale Flows, Datasets und `py.exec` verstehen willst.
- `Fortgeschritten`
  Wenn du bereits einfache `.ns`-Dateien gelesen hast und jetzt Agenten, Events und zusammengesetzte Flows sehen willst.
- `Plattform`
  Wenn du Package-, Service-, Mesh-, Security- und Cluster-Bausteine verstehen willst.
- `Lifecycle`
  Wenn du komplette mehrstufige Entscheidungs- oder Verbesserungszyklen studieren willst.
- `Agenten`
  Wenn du vor allem die Standalone-Agentenbundles und modularen Rollenmodelle nutzen willst.

## Einsteiger

Diese Beispiele geben schnell sichtbare Ergebnisse und haben wenig operative Voraussetzungen.

### 1. [`examples/blob_runtime.ns`](../examples/blob_runtime.ns)

- Warum hier:
  Sehr klein, klar und direkt.
- Was du lernst:
  `blob.verify` und `blob.unpack`.
- Start:

  ```powershell
  ns.run .\examples\blob_runtime.ns
  ```

- Passende Begleitdatei:
  [`examples/blob_runtime_seed.nsblob.json`](../examples/blob_runtime_seed.nsblob.json)

### 2. [`examples/file_extension_scan.ns`](../examples/file_extension_scan.ns)

- Warum hier:
  Ein sehr einfaches lokales Flow-Beispiel.
- Was du lernst:
  `dataset` mit `format: "directory"`, `py.exec`, `state.set`, `system.log`.
- Start:

  ```powershell
  ns.run .\examples\file_extension_scan.ns
  ```

### 3. [`examples/file_extension_scan_advanced.ns`](../examples/file_extension_scan_advanced.ns)

- Warum hier:
  Das naechste sinnvolle Beispiel nach dem einfachen Dateiscan.
- Was du lernst:
  Rekursive Verzeichnisanalyse, Summary-Bildung, Agentenbewertung und HTML-Report.
- Start:

  ```powershell
  ai use lmstudio <modellname>
  ns.run .\examples\file_extension_scan_advanced.ns
  ```

### 4. [`examples/items.csv`](../examples/items.csv) und [`examples/items_large.csv`](../examples/items_large.csv)

- Warum hier:
  Perfekt fuer einfache CLI-Pipelines.
- Was du lernst:
  `data load`, `parallel py`, `ai prompt`, `memory embed`.
- Start:

  ```powershell
  data load examples/items.csv | parallel py row["price"]
  ```

## Fortgeschritten

Diese Beispiele verbinden mehrere Agenten, Memory, Events oder verdichtete Signallogik.

### 1. [`examples/decision_lifecycle_template.ns`](../examples/decision_lifecycle_template.ns)

- Warum hier:
  Das Standardmuster fuer mehrstufige Entscheidungslogik.
- Was du lernst:
  Mehrere Agentenrollen in einem strukturierten Flow.
- Start:

  ```powershell
  ai use lmstudio <modellname>
  ns.run .\examples\decision_lifecycle_template.ns
  ```

### 2. [`examples/market_radar.ns`](../examples/market_radar.ns)

- Warum hier:
  Gutes Beispiel fuer RSS-Dataset, Embeddings und Zusammenfassung.
- Was du lernst:
  Signalaufnahme, Vektorisierung und Radar-Logik.
- Start:

  ```powershell
  ai use lmstudio <modellname>
  ns.run .\examples\market_radar.ns
  ```

### 3. [`examples/federated_swarm_memory.ns`](../examples/federated_swarm_memory.ns)

- Warum hier:
  Kompakt, aber konzeptionell stark.
- Was du lernst:
  Federated-Swarm-Memory und agentengestuetzte Signalverdichtung.
- Start:

  ```powershell
  ai use lmstudio <modellname>
  ns.run .\examples\federated_swarm_memory.ns
  ```

### 4. [`examples/mycelia_coevolution_lab.ns`](../examples/mycelia_coevolution_lab.ns)

- Warum hier:
  Experimenteller, aber klein genug fuer einen schnellen Einstieg.
- Was du lernst:
  Koevolutionaere Prompt- und Signalverdichtung.
- Start:

  ```powershell
  ai use lmstudio <modellname>
  ns.run .\examples\mycelia_coevolution_lab.ns
  ```

### 5. [`examples/distributed_pipeline.ns`](../examples/distributed_pipeline.ns)

- Warum hier:
  Zeigt einen echten Schritt von lokalem Flow hin zu verteiltem Orchestrieren.
- Was du lernst:
  Agent, Tool und Event in einer Incident-Pipeline.
- Start:

  ```powershell
  ai use lmstudio <modellname>
  ns.graph .\examples\distributed_pipeline.ns
  ns.run .\examples\distributed_pipeline.ns
  ```

## Plattform

Diese Beispiele richten sich an Nutzer, die Service-, Cluster- und Security-Konzepte verstehen wollen.

### 1. [`examples/control_plane_runtime.ns`](../examples/control_plane_runtime.ns)

- Fokus:
  Scheduler, Event-Trigger und einfacher Orchestrator-State.
- Start:

  ```powershell
  ns.graph .\examples\control_plane_runtime.ns
  ns.run .\examples\control_plane_runtime.ns
  ```

### 2. [`examples/service_package_platform.ns`](../examples/service_package_platform.ns)

- Fokus:
  `package`, `service`, Quotas und Deployment-Metadaten.
- Start:

  ```powershell
  ns.graph .\examples\service_package_platform.ns
  ns.run .\examples\service_package_platform.ns
  ```

### 3. [`examples/secure_multi_tenant.ns`](../examples/secure_multi_tenant.ns)

- Fokus:
  Rollen, Tenant-Isolation, TLS und sichere Ausfuehrung.
- Start:

  ```powershell
  ns.graph .\examples\secure_multi_tenant.ns
  ns.run .\examples\secure_multi_tenant.ns
  ```

### 4. [`examples/replicated_control_plane.ns`](../examples/replicated_control_plane.ns)

- Fokus:
  Replikation, Sync-Events und Cluster-Policies.
- Start:

  ```powershell
  ns.graph .\examples\replicated_control_plane.ns
  ns.run .\examples\replicated_control_plane.ns
  ```

### 5. [`examples/consensus_fabric_cluster.ns`](../examples/consensus_fabric_cluster.ns)

- Fokus:
  Konsens, Zertifikatsautoritaeten, Trust Policies, Services.
- Start:

  ```powershell
  ns.graph .\examples\consensus_fabric_cluster.ns
  ns.run .\examples\consensus_fabric_cluster.ns
  ```

### 6. [`examples/ai_os_cluster.ns`](../examples/ai_os_cluster.ns)

- Fokus:
  Ein KI-Betriebssystem als meshfaehiger Kontrollknoten.
- Start:

  ```powershell
  ns.graph .\examples\ai_os_cluster.ns
  ns.run .\examples\ai_os_cluster.ns
  ```

### 7. [`examples/advanced_agent_fabric.ns`](../examples/advanced_agent_fabric.ns)

- Fokus:
  Produktionsnahe Kombination aus Service-Fabric, Agenten-Governance, Package und Alerts.
- Start:

  ```powershell
  ns.graph .\examples\advanced_agent_fabric.ns
  ns.run .\examples\advanced_agent_fabric.ns
  ```

## Lifecycle

Diese Kategorie ist fuer komplette Arbeitszyklen gedacht, nicht nur fuer einzelne Flows.

### 1. [`examples/decision_lifecycle_template.ns`](../examples/decision_lifecycle_template.ns)

- Warum Lifecycle:
  Es ist die allgemeine Vorlage fuer mehrstufige Entscheidungen.
- Geeignet fuer:
  Eigene Lifecycle-Entwicklung und Rollenaufteilung.

### 2. [`examples/CEO_ns/CEO_Lifecycle.ns`](../examples/CEO_ns/CEO_Lifecycle.ns)

- Warum Lifecycle:
  Vollstaendiger Executive- und Decision-Cycle mit Signalen, Bewertung, Governance, Execution und Reporting.
- Start:

  ```powershell
  ai use lmstudio <modellname>
  ns.run .\examples\CEO_ns\CEO_Lifecycle.ns
  ```

- Danach:
  Berichte liegen unter `examples\CEO_ns\.nova_ceo\`.

### 3. [`examples/code_improvement_ns/Code_Improve_Lifecycle.ns`](../examples/code_improvement_ns/Code_Improve_Lifecycle.ns)

- Warum Lifecycle:
  Vollstaendiger Verbesserungszyklus fuer Quellcode oder kleine Projekte.
- Start:

  ```powershell
  ai use lmstudio <modellname>
  ns.run .\examples\code_improvement_ns\Code_Improve_Lifecycle.ns
  ```

- Danach:
  Verbessertes Zielartefakt unter `generated/`, Bericht unter `.nova_code_improve/`.

### 4. [`examples/CEO_ns/ceo_continuous_runtime.py`](../examples/CEO_ns/ceo_continuous_runtime.py)

- Warum Lifecycle:
  Kontinuierlicher Lauf des CEO-Lifecycles ausserhalb eines Einzelaufrufs.
- Start:

  ```powershell
  python .\examples\CEO_ns\ceo_continuous_runtime.py
  ```

## Agenten

Hier geht es um Einzelrollen, modulare Agentensysteme und Standalone-Bundles.

### Modulare CEO-Agenten

- [`examples/CEO_ns/CEO_Core.ns`](../examples/CEO_ns/CEO_Core.ns)
  Router fuer die CEO-Suite.
- [`examples/CEO_ns/StrategyAgent.ns`](../examples/CEO_ns/StrategyAgent.ns)
  Strategische Vorschlaege.
- [`examples/CEO_ns/RiskAgent.ns`](../examples/CEO_ns/RiskAgent.ns)
  Risikobewertung.
- [`examples/CEO_ns/CapitalAgent.ns`](../examples/CEO_ns/CapitalAgent.ns)
  Kapital- und Liquiditaetspruefung.
- [`examples/CEO_ns/OperationsAgent.ns`](../examples/CEO_ns/OperationsAgent.ns)
  Operative Umsetzbarkeit.
- [`examples/CEO_ns/ConsensusLayer.ns`](../examples/CEO_ns/ConsensusLayer.ns)
  Endgueltige Managemententscheidung.
- [`examples/CEO_ns/NarrativeAgent.ns`](../examples/CEO_ns/NarrativeAgent.ns)
  Board-Narrativ.
- [`examples/CEO_ns/ExecutionDispatcher.ns`](../examples/CEO_ns/ExecutionDispatcher.ns)
  Operativer Dispatch.

Typische Nutzung:

```powershell
ai use lmstudio <modellname>
ns.run .\examples\CEO_ns\RiskAgent.ns
agent run RiskAgent "Ein Partner will aussteigen, waehrend die Kapazitaet stark steigt."
```

### Standalone-Agentenbundles

#### [`examples/composition_patterns_agents.ns`](../examples/composition_patterns_agents.ns)

- Fokus:
  UI- und Composition-Regeln als spezialisierte Agenten.

```powershell
ai use lmstudio <modellname>
ns.run .\examples\composition_patterns_agents.ns
agent list
```

#### [`examples/react_best_practices_agents.ns`](../examples/react_best_practices_agents.ns)

- Fokus:
  React-Architektur, Patterns und Best Practices.

```powershell
ai use lmstudio <modellname>
ns.run .\examples\react_best_practices_agents.ns
agent list
```

#### [`examples/react_native_skills_agents.ns`](../examples/react_native_skills_agents.ns)

- Fokus:
  React-Native- und Expo-Regeln als lokaler Agentenkatalog.

```powershell
ai use lmstudio <modellname>
ns.run .\examples\react_native_skills_agents.ns
agent list
```

## Empfohlene Reihenfolge je Ziel

### Ich will Nova-shell schnell praktisch verstehen

1. `blob_runtime.ns`
2. `file_extension_scan.ns`
3. `file_extension_scan_advanced.ns`
4. `decision_lifecycle_template.ns`

### Ich will Agenten praktisch einsetzen

1. `CEO_ns/StrategyAgent.ns`
2. `CEO_ns/RiskAgent.ns`
3. `composition_patterns_agents.ns`
4. `react_best_practices_agents.ns`

### Ich will Lifecycles bauen

1. `decision_lifecycle_template.ns`
2. `CEO_ns/CEO_Lifecycle.ns`
3. `code_improvement_ns/Code_Improve_Lifecycle.ns`

### Ich will Plattform- und Clusterkonzepte verstehen

1. `control_plane_runtime.ns`
2. `service_package_platform.ns`
3. `secure_multi_tenant.ns`
4. `replicated_control_plane.ns`
5. `consensus_fabric_cluster.ns`
6. `ai_os_cluster.ns`
7. `advanced_agent_fabric.ns`

## Verwandte Seiten

- [`examples.md`](./examples.md)
- [`examples_quickstart.md`](./examples_quickstart.md)
- [`ExamplesAndRecipes.md`](./ExamplesAndRecipes.md)
- [`CEOAgentExamples.md`](./CEOAgentExamples.md)
