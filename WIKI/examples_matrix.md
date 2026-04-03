# examples_matrix

Diese Seite fasst die vorhandenen Beispiele aus [`examples/`](../examples/) als schnelle Vergleichsmatrix zusammen.
Sie beantwortet auf einen Blick:

- zu welcher Kategorie ein Beispiel gehoert
- ob ein aktiver AI-Provider sinnvoll oder noetig ist
- ob Mesh-, Cluster- oder Plattformfunktionen beteiligt sind
- ob direkt sichtbare Reports oder Artefakte entstehen
- ob das Beispiel ein guter Einstieg ist

Verwandte Seiten:

- [`examples_index.md`](./examples_index.md)
  Zentrales Portal fuer alle Example-Seiten.
- [`examples.md`](./examples.md)
  Vollstaendige dateiweise Referenz.
- [`examples_quickstart.md`](./examples_quickstart.md)
  Copy-Paste-Kommandos.
- [`examples_by_level.md`](./examples_by_level.md)
  Sortierung nach Lernstufe.

## Legende

- `AI`
  `ja` bedeutet: ein aktiver AI-Provider ist praktisch noetig oder stark empfohlen.
  `optional` bedeutet: das Beispiel kann strukturell auch ohne aktiven Provider gelesen werden, wird aber erst mit Modell wirklich interessant.
  `nein` bedeutet: kein aktiver AI-Provider ist fuer den Kernnutzen noetig.
- `Mesh`
  `ja` bedeutet: Mesh-, Cluster- oder verteilte Plattformkonzepte sind zentral.
  `optional` bedeutet: das Beispiel kann lokal gelesen oder teilweise genutzt werden, modelliert aber Mesh-/Plattform-Aspekte.
- `Report/Artefakte`
  Nennt das sichtbare Hauptergebnis.
- `Einstieg`
  `ja` bedeutet: guter Startpunkt fuer neue Nutzer.

## Hauptbeispiele

| Datei | Kategorie | AI | Mesh | Report/Artefakte | Einstieg | Kurzbild |
| --- | --- | --- | --- | --- | --- | --- |
| [`examples/blob_runtime.ns`](../examples/blob_runtime.ns) | Blob | nein | nein | Verifikation und Unpack-Resultat | ja | Kleinster Einstieg in Blob-Seeds |
| [`examples/file_extension_scan.ns`](../examples/file_extension_scan.ns) | Lokaler Flow | nein | nein | JSON-Report im Log | ja | Dateiscanner nach Endung |
| [`examples/file_extension_scan_advanced.ns`](../examples/file_extension_scan_advanced.ns) | Lokaler Report | ja | nein | JSON, Summary, HTML-Datei | ja | Rekursiver Scan mit Agentenbewertung |
| [`examples/decision_lifecycle_template.ns`](../examples/decision_lifecycle_template.ns) | Lifecycle | ja | nein | Aktionstext und State | ja | Generische Entscheidungsvorlage |
| [`examples/market_radar.ns`](../examples/market_radar.ns) | Radar/Signals | ja | nein | Briefing und Embeddings | ja | RSS- und Marktbeobachtung |
| [`examples/federated_swarm_memory.ns`](../examples/federated_swarm_memory.ns) | Memory | ja | optional | Invariant-Summary im State | ja | Federated-Swarm-Summary |
| [`examples/mycelia_coevolution_lab.ns`](../examples/mycelia_coevolution_lab.ns) | Experiment | ja | nein | Population-Signal im State | nein | Kleines Coevolution-Lab |
| [`examples/control_plane_runtime.ns`](../examples/control_plane_runtime.ns) | Plattform | nein | optional | State und Event | nein | Scheduler- und Control-Plane-Logik |
| [`examples/distributed_pipeline.ns`](../examples/distributed_pipeline.ns) | Mesh-Pipeline | ja | ja | Triage-Report | nein | Incident-Pipeline ueber Mesh |
| [`examples/advanced_agent_fabric.ns`](../examples/advanced_agent_fabric.ns) | Fabric/Services | optional | optional | Service- und Agentenstatus | nein | Produktionsnahe Gesamt-Fabric |
| [`examples/ai_os_cluster.ns`](../examples/ai_os_cluster.ns) | KI-Betriebssystem | ja | ja | Action-Plan und Events | nein | Mesh-Orchestrator mit Signalsystem |
| [`examples/consensus_fabric_cluster.ns`](../examples/consensus_fabric_cluster.ns) | Cluster | optional | ja | State und Service-Status | nein | Konsens, Trust und Service-Fabric |
| [`examples/replicated_control_plane.ns`](../examples/replicated_control_plane.ns) | Replication | nein | ja | Replizierter State und Event | nein | Multi-Node-Sync-Muster |
| [`examples/secure_multi_tenant.ns`](../examples/secure_multi_tenant.ns) | Security | nein | ja | Gesicherter Compute-State | nein | Rollen, TLS, Tenant-Isolation |
| [`examples/service_package_platform.ns`](../examples/service_package_platform.ns) | Deployment | nein | optional | Package-/Service-Status | nein | Package- und Service-Modell |
| [`examples/nova_project_monitor.ns`](../examples/nova_project_monitor.ns) | Monitoring | optional | nein | Projektmonitor-Report | nein | In echte Projekte kopierbarer Monitor |
| [`examples/nova_system_guard.ns`](../examples/nova_system_guard.ns) | Guard | optional | nein | Guard-Report | nein | Windows-Integritaetsmonitor |
| [`examples/composition_patterns_agents.ns`](../examples/composition_patterns_agents.ns) | Agentenbundle | ja | nein | Geladene Spezialagenten | nein | UI-/Composition-Regelkatalog |
| [`examples/react_best_practices_agents.ns`](../examples/react_best_practices_agents.ns) | Agentenbundle | ja | nein | Geladene Spezialagenten | nein | React-Best-Practice-Katalog |
| [`examples/react_native_skills_agents.ns`](../examples/react_native_skills_agents.ns) | Agentenbundle | ja | nein | Geladene Spezialagenten | nein | React-Native-/Expo-Katalog |

## Beispiel-Suiten

| Ordner/Datei | Kategorie | AI | Mesh | Report/Artefakte | Einstieg | Kurzbild |
| --- | --- | --- | --- | --- | --- | --- |
| [`examples/CEO_ns/CEO_Core.ns`](../examples/CEO_ns/CEO_Core.ns) | Router-Agent | ja | nein | Routing-Empfehlung | nein | Einstieg in die CEO-Suite |
| [`examples/CEO_ns/StrategyAgent.ns`](../examples/CEO_ns/StrategyAgent.ns) | Rollenagent | ja | nein | Vorschlag mit Score | ja | Strategischer Einzelagent |
| [`examples/CEO_ns/RiskAgent.ns`](../examples/CEO_ns/RiskAgent.ns) | Rollenagent | ja | nein | Risikoformat mit Empfehlung | ja | Risikobewertung fuer Entscheidungen |
| [`examples/CEO_ns/CapitalAgent.ns`](../examples/CEO_ns/CapitalAgent.ns) | Rollenagent | ja | nein | Freigabe-/Kapitalantwort | nein | Kapital- und Liquiditaetspruefung |
| [`examples/CEO_ns/OperationsAgent.ns`](../examples/CEO_ns/OperationsAgent.ns) | Rollenagent | ja | nein | Operational-Fit und Bottleneck | ja | Operative Umsetzbarkeit |
| [`examples/CEO_ns/ConsensusLayer.ns`](../examples/CEO_ns/ConsensusLayer.ns) | Rollenagent | ja | nein | Endentscheidung | nein | Vereint mehrere Perspektiven |
| [`examples/CEO_ns/NarrativeAgent.ns`](../examples/CEO_ns/NarrativeAgent.ns) | Rollenagent | ja | nein | Board-Narrativ | nein | Management-Narrativ |
| [`examples/CEO_ns/ExecutionDispatcher.ns`](../examples/CEO_ns/ExecutionDispatcher.ns) | Rollenagent | ja | nein | Operativer Dispatch | nein | Uebersetzt Entscheidung in Aktion |
| [`examples/CEO_ns/CEO_Lifecycle.ns`](../examples/CEO_ns/CEO_Lifecycle.ns) | Lifecycle-Suite | ja | nein | `.nova_ceo`, Report, State, Verlauf | ja | Voller Executive-Cycle |
| [`examples/CEO_ns/ceo_continuous_runtime.py`](../examples/CEO_ns/ceo_continuous_runtime.py) | Kontinuierlicher Runner | nein | nein | `continuous_status.json` | nein | Periodischer CEO-Lauf |
| [`examples/code_improvement_ns/Code_Improve_Lifecycle.ns`](../examples/code_improvement_ns/Code_Improve_Lifecycle.ns) | Code-Lifecycle | ja | nein | Verbessertes Zielartefakt und Report | ja | Selbstverbesserung fuer Code |
| [`examples/code_improvement_ns/code_improve_runtime_helper.py`](../examples/code_improvement_ns/code_improve_runtime_helper.py) | Helper | nein | nein | Hilfslogik | nein | Parsing, Auswahl, Persistenz |
| [`examples/code_improvement_ns/README.md`](../examples/code_improvement_ns/README.md) | Doku | nein | nein | Kurzanleitung | nein | Einstieg in die Suite |

## Daten-, Request- und Helper-Dateien

| Datei | Typ | Direkt nutzbar | Wofuer gedacht |
| --- | --- | --- | --- |
| [`examples/blob_runtime_seed.nsblob.json`](../examples/blob_runtime_seed.nsblob.json) | Seed-Artefakt | ja, ueber `blob.*` | Blob- und Seed-Demo |
| [`examples/items.csv`](../examples/items.csv) | CSV | ja | Kleine Datenpipeline-Demo |
| [`examples/items_large.csv`](../examples/items_large.csv) | CSV | ja | Groessere Datenpipeline-Demo |
| [`examples/nova_project_monitor_helper.py`](../examples/nova_project_monitor_helper.py) | Helper | indirekt | Python-Logik fuer Projektmonitor |
| [`examples/nova_system_guard_helper.py`](../examples/nova_system_guard_helper.py) | Helper | indirekt | Python-Logik fuer System Guard |
| [`examples/CEO_ns/internal_telemetry.json`](../examples/CEO_ns/internal_telemetry.json) | Dataset | indirekt | Interne Betriebssignale fuer CEO-Lifecycle |
| [`examples/CEO_ns/external_market_signals.json`](../examples/CEO_ns/external_market_signals.json) | Dataset | indirekt | Marktsignale fuer CEO-Lifecycle |
| [`examples/CEO_ns/event_signals.json`](../examples/CEO_ns/event_signals.json) | Dataset | indirekt | Event-Signale fuer CEO-Lifecycle |
| [`examples/CEO_ns/policy_overrides.json`](../examples/CEO_ns/policy_overrides.json) | Dataset | indirekt | Governance-Overrides |
| [`examples/CEO_ns/ceo_runtime_helper.py`](../examples/CEO_ns/ceo_runtime_helper.py) | Helper | indirekt | Signal-, State- und Reportlogik |
| [`examples/code_improvement_ns/code_improvement_request.json`](../examples/code_improvement_ns/code_improvement_request.json) | Request | ja, indirekt | Standardlauf fuer Einzeldatei |
| [`examples/code_improvement_ns/code_improvement_project_request.json`](../examples/code_improvement_ns/code_improvement_project_request.json) | Request | ja, indirekt | Projektmodus fuer mehrere Dateien |
| [`examples/code_improvement_ns/sample_target.py`](../examples/code_improvement_ns/sample_target.py) | Beispielcode | indirekt | Ziel fuer Einzeldatei-Verbesserung |
| [`examples/code_improvement_ns/demo_project/clean_numbers.py`](../examples/code_improvement_ns/demo_project/clean_numbers.py) | Beispielcode | indirekt | Demo-Projektdatei fuer Projektmodus |
| [`examples/code_improvement_ns/demo_project/reporting.py`](../examples/code_improvement_ns/demo_project/reporting.py) | Beispielcode | indirekt | Zweite Demo-Projektdatei |

## Beste Startpunkte nach Ziel

| Ziel | Bester Start |
| --- | --- |
| Ich will sofort etwas sehen | [`examples/file_extension_scan.ns`](../examples/file_extension_scan.ns) |
| Ich will einen HTML-Report sehen | [`examples/file_extension_scan_advanced.ns`](../examples/file_extension_scan_advanced.ns) |
| Ich will Blob-Seeds verstehen | [`examples/blob_runtime.ns`](../examples/blob_runtime.ns) |
| Ich will Agenten-Lifecycles lernen | [`examples/decision_lifecycle_template.ns`](../examples/decision_lifecycle_template.ns) |
| Ich will eine komplette Management-Suite sehen | [`examples/CEO_ns/CEO_Lifecycle.ns`](../examples/CEO_ns/CEO_Lifecycle.ns) |
| Ich will Nova-shell fuer Codeverbesserung nutzen | [`examples/code_improvement_ns/Code_Improve_Lifecycle.ns`](../examples/code_improvement_ns/Code_Improve_Lifecycle.ns) |
| Ich will Cluster- und Plattformkonzepte lesen | [`examples/control_plane_runtime.ns`](../examples/control_plane_runtime.ns) |
| Ich will einen grossen Agentenkatalog laden | [`examples/react_best_practices_agents.ns`](../examples/react_best_practices_agents.ns) |

## Hinweis zur Interpretation

Diese Matrix bewertet nicht, welches Beispiel das "beste" ist, sondern welches fuer einen bestimmten Lern- oder Einsatzfall am passendsten ist.
Die Einordnung `Einstieg: ja` ist absichtlich streng: Sie markiert nur Beispiele, die ohne viel Vorwissen schnell einen verstaendlichen Nutzen zeigen.
