# examples

Diese Seite ist die vollstaendige Referenz fuer die Beispiele im Ordner [`examples/`](../examples/).
Sie erklaert, was jedes Beispiel zeigt, wie du es startest, welche Voraussetzungen gelten und welche Dateien nur als Daten, Requests oder Helper dienen.

Nicht als Quellbeispiele zaehlen versteckte Laufzeitordner wie `.nova*`, generierte Reports oder `__pycache__`. Diese werden hier bewusst nicht dokumentiert.

## Grundregeln fuer alle Beispiele

1. Starte die Beispiele am besten aus dem Repository-Root `H:\Nova-shell-main`.
2. Nutze zuerst `ns.graph <datei>`, wenn du die Struktur sehen willst, und `ns.run <datei>`, wenn du das Beispiel laden oder direkt ausfuehren willst.
3. Beispiele mit `provider: shell` und `model: active` brauchen einen aktiven AI-Provider, zum Beispiel:

   ```powershell
   ai use lmstudio <modellname>
   ```

4. Beispiele mit relativen `path:`-Angaben erwarten, dass du sie aus dem Repo-Root oder aus ihrem eigenen Beispielordner startest.
5. Einige Plattform- und Clusterbeispiele sind in erster Linie Architektur- und Runtime-Beispiele. Sie sind zum Verstehen, fuer `ns.graph` und fuer kontrollierte lokale Tests gedacht. Nicht jedes davon ist ohne passende Runtime-, Mesh- oder Service-Umgebung als vollstaendige End-to-End-Demo gedacht.

## Schnellueberblick

| Bereich | Dateien | Typischer Nutzen |
| --- | --- | --- |
| Lokale Analyse und Reports | `file_extension_scan*.ns`, `blob_runtime.ns` | Sofort lokal starten und Ergebnis sehen |
| Agenten und Entscheidungslogik | `decision_lifecycle_template.ns`, `market_radar.ns`, `federated_swarm_memory.ns`, `mycelia_coevolution_lab.ns` | Memory, Agenten und Ereignisse verstehen |
| Plattform und Cluster | `advanced_agent_fabric.ns`, `ai_os_cluster.ns`, `consensus_fabric_cluster.ns`, `control_plane_runtime.ns`, `distributed_pipeline.ns`, `replicated_control_plane.ns`, `secure_multi_tenant.ns`, `service_package_platform.ns` | Architektur, Service-Plane, Replication, Security |
| Monitoring und Guard | `nova_project_monitor.ns`, `nova_system_guard.ns` | In echte Projekte kopieren und dort verwenden |
| Standalone Skill Bundles | `composition_patterns_agents.ns`, `react_best_practices_agents.ns`, `react_native_skills_agents.ns` | Agenten laden und per `agent run` nutzen |
| Komplette Example-Suiten | `CEO_ns/`, `code_improvement_ns/` | Mehrstufige Lifecycles und modulare Agentensysteme |

## Wie du die Beispiele sinnvoll nutzt

### Nur Struktur ansehen

```powershell
ns.graph .\examples\file_extension_scan_advanced.ns
```

Das ist der beste Einstieg fuer groessere Beispiele mit vielen Flows, Events oder Agenten.

### Flow ausfuehren

```powershell
ns.run .\examples\blob_runtime.ns
```

Das ist sinnvoll fuer Beispiele, die direkt eine Pipeline, einen Report oder ein Lifecycle-Resultat erzeugen.

### Agentenbundle laden und dann gezielt aufrufen

```powershell
ai use lmstudio <modellname>
ns.run .\examples\CEO_ns\StrategyAgent.ns
agent run StrategyAgent "Enterprise-Nachfrage steigt stark."
```

Das ist das passende Muster fuer einzelne Agentenbeispiele.

## Top-Level-Beispiele in `examples/`

### [`advanced_agent_fabric.ns`](../examples/advanced_agent_fabric.ns)

Dieses Beispiel zeigt eine fortgeschrittene Produktionsbeschreibung mit `system`, `package`, `service`, `agent`, `dataset` und `flow`.

- Zweck:
  Eine kombinierte Fabric-Deklaration fuer Service-Betrieb, Agenten-Governance und Observability.
- Was du daran lernst:
  Wie Services, Packages, Autoscaling, Memory-Shards und Alerts gemeinsam modelliert werden.
- Empfohlene Nutzung:
  Zuerst mit `ns.graph`, danach optional mit `ns.run`, wenn du den Review-Flow im Kontext lokaler Runtime-Funktionen untersuchen willst.
- Geeignet fuer:
  Architekturstudium, Plattformdesign und erweiterte `.ns`-Systemmodelle.

### [`ai_os_cluster.ns`](../examples/ai_os_cluster.ns)

Dieses Beispiel modelliert ein KI-Betriebssystem als Mesh-orientierten Kontrollknoten.

- Zweck:
  Zeigt `system` mit Cluster-, Lease-, Secret- und Schedule-Eigenschaften sowie einen strategischen Agenten mit Atheria-Integration.
- Flow:
  Ein Signal-Feed wird geladen, eingebettet, gezaehlt, als State persistiert und anschliessend in einen Aktionsplan verdichtet.
- Empfohlene Nutzung:
  `ns.graph` fuer die Architektur, `ns.run` fuer den Datenfluss.
- Besonders interessant, wenn du:
  Scheduler, Mesh-Betrieb und Agent-orchestrierte Betriebslogik kombinieren willst.

### [`blob_runtime.ns`](../examples/blob_runtime.ns)

Das kleinste und direkteste Beispiel fuer NSBlob-Artefakte.

- Zweck:
  Demonstriert `blob.verify` und `blob.unpack`.
- Abhaengige Datei:
  [`blob_runtime_seed.nsblob.json`](../examples/blob_runtime_seed.nsblob.json)
- Typischer Start:

  ```powershell
  ns.run .\examples\blob_runtime.ns
  ```

- Ergebnis:
  Du siehst, wie ein Blob erst geprueft und dann entpackt wird.
- Geeignet fuer:
  Einsteiger in Seed-, Bundle- und Blob-Workflows.

### [`blob_runtime_seed.nsblob.json`](../examples/blob_runtime_seed.nsblob.json)

Das ist kein `.ns`-Programm, sondern das zugehoerige Beispiel-Artefakt fuer `blob_runtime.ns`.

- Zweck:
  Beispiel fuer ein NSBlob-Seed-Payload.
- Nutzung:
  Nicht direkt mit `ns.run` starten, sondern ueber `blob_runtime.ns` oder andere Blob-Befehle verwenden.

### [`composition_patterns_agents.ns`](../examples/composition_patterns_agents.ns)

Ein grosses Standalone-Agentenbundle fuer UI- und Composition-Patterns.

- Zweck:
  Es laedt viele spezialisierte Agenten fuer React-/UI-Kompositionsregeln in eine einzelne Datei.
- Was du daran lernst:
  Wie grosse Agentenkataloge als `.ns`-Bundle ausgeliefert werden koennen.
- Typischer Ablauf:

  ```powershell
  ai use lmstudio <modellname>
  ns.run .\examples\composition_patterns_agents.ns
  agent list
  ```

- Danach:
  Du rufst gezielt einen Agenten aus dem geladenen Katalog mit `agent run <name> "<input>"` auf.
- Geeignet fuer:
  Standalone Skill Agents, Regelkataloge und lokale Expertensysteme.

### [`consensus_fabric_cluster.ns`](../examples/consensus_fabric_cluster.ns)

Dieses Beispiel zeigt einen clusterfaehigen Plattformkern mit Konsens, Zertifikatsautoritaeten, Trust Policies, Package und Service.

- Zweck:
  Demonstriert, wie ein konsensfaehiges Cluster samt Service-Rollout beschrieben wird.
- Flow:
  Ein Prompt-Dataset wird gezaehlt, in State geschrieben und der Gateway-Service abgefragt.
- Empfohlene Nutzung:
  Vor allem `ns.graph`, anschliessend gezielte Runtime-Tests.
- Geeignet fuer:
  Cluster- und Control-Plane-Konzepte.

### [`control_plane_runtime.ns`](../examples/control_plane_runtime.ns)

Ein kompaktes Beispiel fuer Schedules, Events und Control-Plane-State.

- Zweck:
  Zeigt, wie ein Orchestrator periodische Jobs und Event-getriggerte Flows beschreibt.
- Flow:
  Metriken werden summiert, im State abgelegt und als Event emittiert.
- Typischer Nutzen:
  Einstieg in Scheduler- und Queue-nahe `.ns`-Programme.
- Typischer Start:

  ```powershell
  ns.graph .\examples\control_plane_runtime.ns
  ns.run .\examples\control_plane_runtime.ns
  ```

### [`decision_lifecycle_template.ns`](../examples/decision_lifecycle_template.ns)

Das ist die generische Vorlage fuer einen mehrstufigen Entscheidungs-Lifecycle.

- Zweck:
  Zeigt ein vollstaendiges Muster aus mehreren Agentenrollen: Signal-Transformation, Constraint-Analyse, Merge, Entscheidung und Aktion.
- Wichtige Bausteine:
  `SignalTransformer`, `ConstraintTransformer`, `MergerAgent`, `DecisionAgent`, `ActionAgent`.
- Flow:
  Rohsignale werden transformiert, zusammengefuehrt, entschieden und in eine Aktion uebersetzt.
- Geeignet fuer:
  Eigene Lifecycles, die du spaeter fuer Betrieb, Management oder Moderation anpassen willst.
- Besonders wertvoll:
  Als Blaupause fuer eigene `.ns`-Programme mit mehreren Agenten.

### [`distributed_pipeline.ns`](../examples/distributed_pipeline.ns)

Ein Mesh-orientiertes Beispiel fuer Incident-Triage ueber eine Pipeline.

- Zweck:
  Kombiniert `system`, `tool`, `agent`, `dataset`, `flow` und `event` fuer eine verteilte Incident-Reaktion.
- Flow:
  Ein Incident-Feed wird gelesen, ein Planner erzeugt einen Triage-Report und ein Tool publiziert ihn.
- Was du daran lernst:
  Wie man Agenten und Tools in einer verteilten Pipeline verknuepft.
- Geeignet fuer:
  Edge-, Mesh- und Operations-Szenarien.

### [`federated_swarm_memory.ns`](../examples/federated_swarm_memory.ns)

Ein kleines, klares Beispiel fuer Swarm-Memory und Zusammenfassung lokaler Findings.

- Zweck:
  Zeigt einen federierten Memory-Use-Case mit Agent, State und lokaler Signalverdichtung.
- Flow:
  `local_findings` werden zusammengefasst und als Invariant-Summary im State abgelegt.
- Geeignet fuer:
  Memory-Konzepte, Federated-Learning-Denke und leichte Agentendemos.

### [`file_extension_scan.ns`](../examples/file_extension_scan.ns)

Ein direkt lokal nutzbares Beispiel fuer Dateisystemanalyse.

- Zweck:
  Zaehlt Dateien in einem Verzeichnis und gruppiert sie nach Endung.
- Flow:
  Ein `directory`-Dataset wird eingelesen, per `py.exec` in JSON umgebaut und ins Log geschrieben.
- Typischer Start:

  ```powershell
  ns.run .\examples\file_extension_scan.ns
  ```

- Ergebnis:
  Ein JSON-Report mit Dateigruppen und Anzahl.
- Geeignet fuer:
  Einsteiger, Verzeichnisdatasets und `py.exec` in Flows.

### [`file_extension_scan_advanced.ns`](../examples/file_extension_scan_advanced.ns)

Die ausfuehrlichere Variante des Dateiscan-Beispiels.

- Zweck:
  Fuehrt einen rekursiven Scan durch, erzeugt JSON, Summary, Agentenbewertung und HTML-Report.
- Besonderheiten:
  Schreibt `file_extension_scan_report.html` und oeffnet die Datei optional automatisch.
- Agent:
  `inspector` bewertet Struktur, groesste Dateien, Dateien ohne Endung und Aufraeumpotenzial.
- Typischer Start:

  ```powershell
  ai use lmstudio <modellname>
  ns.run .\examples\file_extension_scan_advanced.ns
  ```

- Geeignet fuer:
  Lokale Reports, Dateianalyse und HTML-Ausgabe aus einem Flow.

### [`items.csv`](../examples/items.csv)

Kleine CSV fuer CLI-, Daten- und AI-Pipeline-Beispiele.

- Zweck:
  Demonstrationsdaten fuer `data load`, `parallel py`, `ai prompt`, `memory embed` und andere Pipeline-Kommandos.
- Typische Nutzung:

  ```powershell
  data load examples/items.csv | parallel py row["price"]
  ```

- Geeignet fuer:
  Einfache Datenpipelines und Doku-Beispiele.

### [`items_large.csv`](../examples/items_large.csv)

Groessere CSV-Variante fuer dieselben Datenpipeline-Muster.

- Zweck:
  Dient als etwas realistischere Eingabe fuer Aggregationen, Filter und Einbettungen.
- Geeignet fuer:
  `data load`, `parallel`, Memory- und AI-Workflows mit mehr Zeilenvolumen.

### [`market_radar.ns`](../examples/market_radar.ns)

Ein kompaktes Radar-Beispiel mit RSS-Dataset, Embeddings und Zusammenfassung.

- Zweck:
  Zeigt, wie externe Signale gesammelt, eingebettet und von einem Forschungsagenten verdichtet werden.
- Bestandteile:
  `research_memory`, Agent `researcher`, RSS-Dataset `tech_rss`, Event `new_information`.
- Vorausgesetzt:
  Das Beispiel nutzt [`sample_news.json`](../sample_news.json) aus dem Repo.
- Geeignet fuer:
  Monitoring, News-Radar und erste Atheria-/Embedding-Workflows.

### [`mycelia_coevolution_lab.ns`](../examples/mycelia_coevolution_lab.ns)

Ein minimales Experiment fuer ko-evolutionaere Signalverdichtung.

- Zweck:
  Verdichtet mehrere Prompts zu einem Population-Signal.
- Flow:
  Ein `evaluator`-Agent fasst Eingaben zusammen, State speichert das Ergebnis, `system.log` gibt es aus.
- Geeignet fuer:
  Leichte Experimente rund um Mycelia-/Coevolution-Denke.

### [`nova_project_monitor.ns`](../examples/nova_project_monitor.ns)

Ein ausfuehrbares Monitor-Skript fuer ein beliebiges Projektverzeichnis.

- Zweck:
  Beobachtet ein Projekt, erzeugt Reports und kann optional Automations- und AI-Pfade mitnutzen.
- Wichtiger Unterschied:
  Dieses Beispiel ist zum Kopieren in ein echtes Projekt gedacht, nicht nur zum Studieren im `examples`-Ordner.
- Kommentarblock im Kopf:
  Dokumentiert alle relevanten Umgebungsvariablen wie Intervall, Debounce, Watch-Mode, AI-Modus und Automation.
- Helper:
  [`nova_project_monitor_helper.py`](../examples/nova_project_monitor_helper.py) wird beim Lauf in `.nova_project_monitor/` geschrieben und dann ausgefuehrt.
- Typischer Einsatz:
  In das Wurzelverzeichnis eines Projekts kopieren und dort `ns.run nova_project_monitor.ns` starten.

### [`nova_project_monitor_helper.py`](../examples/nova_project_monitor_helper.py)

Helper-Datei fuer den Projektmonitor.

- Zweck:
  Enthaelt die Python-Logik, die vom `.ns`-Skript zur Laufzeit eingebettet und ausgefuehrt wird.
- Nutzung:
  Nicht als eigenstaendiges Hauptbeispiel, sondern als Begleitdatei von `nova_project_monitor.ns`.

### [`nova_system_guard.ns`](../examples/nova_system_guard.ns)

Ein Windows-zentriertes Persistenz- und Integritaetsmonitoring.

- Zweck:
  Ueberwacht definierte Pfade und erzeugt Reports fuer System- und Projektintegritaet.
- Einsatzmuster:
  Wie beim Projektmonitor wird die Datei in einen realen Arbeitskontext kopiert und dort ausgefuehrt.
- Kopfkommentar:
  Beschreibt Intervalle, Debounce, Include-Defaults, Projektpfade und Watch-Verhalten.
- Helper:
  [`nova_system_guard_helper.py`](../examples/nova_system_guard_helper.py)
- Geeignet fuer:
  Windows-Watch-, Guard- und Persistenzszenarien.

### [`nova_system_guard_helper.py`](../examples/nova_system_guard_helper.py)

Begleitdatei fuer `nova_system_guard.ns`.

- Zweck:
  Stellt die Python-Hauptlogik fuer den Guard-Lauf bereit.
- Nutzung:
  Nicht direkt mit `ns.run`, sondern indirekt ueber das Hauptskript.

### [`react_best_practices_agents.ns`](../examples/react_best_practices_agents.ns)

Ein grosses Expertensystem fuer React-Best-Practices.

- Zweck:
  Laedt einen umfangreichen Agentenkatalog fuer React-, Architektur-, Performance- und API-Regeln.
- Typische Nutzung:

  ```powershell
  ai use lmstudio <modellname>
  ns.run .\examples\react_best_practices_agents.ns
  agent list
  ```

- Danach:
  Einen passenden Spezialagenten auswaehlen und gezielt mit `agent run` ansprechen.
- Geeignet fuer:
  Code-Review, Code-Transformation und regelbasierten Agenteneinsatz.

### [`react_native_skills_agents.ns`](../examples/react_native_skills_agents.ns)

Das React-Native-Gegenstueck zum React-Best-Practices-Bundle.

- Zweck:
  Laedt viele spezialisierte Agenten fuer Expo, React Native, Performance, Navigation, Styling und mobile Architektur.
- Typischer Nutzen:
  Du kannst ein React-Native-Projekt oder einen einzelnen Codeausschnitt gegen konkrete mobile Regeln pruefen lassen.
- Typische Nutzung:
  Laden, `agent list`, danach passendes Spezialagenten-Target aufrufen.

### [`replicated_control_plane.ns`](../examples/replicated_control_plane.ns)

Ein Beispiel fuer Replikation und sichere Cluster-Synchronisation.

- Zweck:
  Zeigt Replikationsendpunkte, Auth-Token, Trust Policies und einen einfachen Sync-Flow.
- Flow:
  Ein Payload wird geloggt, in replizierten State geschrieben und als Event emittiert.
- Geeignet fuer:
  Replikationsmodelle, Multi-Node-Tests und sichere Event-Verteilung.

### [`secure_multi_tenant.ns`](../examples/secure_multi_tenant.ns)

Ein kompaktes Sicherheitsbeispiel fuer Auth, Rollen, TLS und Tenant-Isolation.

- Zweck:
  Zeigt, wie sichere Compute-Flows mit Rollen- und TLS-Anforderungen modelliert werden.
- Besonderheiten:
  `auth_required`, `tenant_isolation`, `mesh_tls_required`, `required_roles`.
- Flow:
  Metriken werden summiert, als State gespeichert und als Event publiziert.
- Geeignet fuer:
  Sicherheits- und Governance-Muster in `.ns`.

### [`service_package_platform.ns`](../examples/service_package_platform.ns)

Ein Beispiel fuer Package- und Service-Betrieb auf einer Plattformebene.

- Zweck:
  Zeigt `package`, `service`, Quotas, API-Plane und Statuspruefung.
- Flow:
  Paket- und Service-Status werden abgerufen und in State abgelegt.
- Geeignet fuer:
  Service-Rollout, Package-Lifecycle und Plattformmodelle.

## Beispiel-Suite `examples/CEO_ns`

Der Ordner [`examples/CEO_ns/`](../examples/CEO_ns/) ist ein komplettes Executive-/CEO-Beispielsystem. Die tiefere Erklaerung steht zusaetzlich in [`CEOAgentExamples.md`](./CEOAgentExamples.md). Hier findest du die operative Einordnung aller Dateien.

### Agenten und Rollen

- [`CEO_Core.ns`](../examples/CEO_ns/CEO_Core.ns)
  Router-Agent fuer die gesamte CEO-Suite. Er sagt dir, welche Rolle oder Laufzeitdatei als naechstes passt.
- [`StrategyAgent.ns`](../examples/CEO_ns/StrategyAgent.ns)
  Erzeugt einen Vorschlag, Score und Kapitalbedarf aus Markt- und Betriebssignalen.
- [`RiskAgent.ns`](../examples/CEO_ns/RiskAgent.ns)
  Bewertet Risiken, Warnsignale und eine direkte Empfehlung fuer den Vorstand.
- [`CapitalAgent.ns`](../examples/CEO_ns/CapitalAgent.ns)
  Prueft Kapitalbedarf, Liquiditaetswirkung und Freigabefaehigkeit.
- [`OperationsAgent.ns`](../examples/CEO_ns/OperationsAgent.ns)
  Bewertet operative Umsetzbarkeit, Bottlenecks und Kapazitaetsmassnahmen.
- [`ConsensusLayer.ns`](../examples/CEO_ns/ConsensusLayer.ns)
  Vereint Strategie-, Risiko- und Kapitalperspektive in eine finale Entscheidung.
- [`NarrativeAgent.ns`](../examples/CEO_ns/NarrativeAgent.ns)
  Formt Entscheidungen in ein boardtaugliches Narrativ um.
- [`ExecutionDispatcher.ns`](../examples/CEO_ns/ExecutionDispatcher.ns)
  Uebersetzt Entscheidungen in operative Dispatch-Schritte und Verantwortlichkeiten.

### Lifecycle und Runtime

- [`CEO_Lifecycle.ns`](../examples/CEO_ns/CEO_Lifecycle.ns)
  Das Herzstueck der Suite. Laedt Telemetrie, Markt- und Event-Signale, harmonisiert sie, bewertet sie ueber mehrere Rollen und schreibt Artefakte unter `.nova_ceo/`.
- [`ceo_runtime_helper.py`](../examples/CEO_ns/ceo_runtime_helper.py)
  Python-Helfer fuer Signalnormalisierung, Zustandslogik, Scoring, Ausfuehrung, Persistenz und Berichtserstellung.
- [`ceo_continuous_runtime.py`](../examples/CEO_ns/ceo_continuous_runtime.py)
  Ein Python-Runner fuer kontinuierliche `ceo.tick`-Zyklen. Gut fuer periodischen Betrieb ausserhalb eines einzelnen `ns.run`-Aufrufs.

### Datensaetze

- [`internal_telemetry.json`](../examples/CEO_ns/internal_telemetry.json)
  Interne Betriebs- und Kapazitaetssignale.
- [`external_market_signals.json`](../examples/CEO_ns/external_market_signals.json)
  Externe Markt- und Nachfragesignale.
- [`event_signals.json`](../examples/CEO_ns/event_signals.json)
  Ereignisbasierte Trigger und Zusatzsignale.
- [`policy_overrides.json`](../examples/CEO_ns/policy_overrides.json)
  Governance- und Policy-Anpassungen fuer den Lauf.

### Typische Nutzung der CEO-Suite

#### Einzelne Rolle laden

```powershell
ai use lmstudio <modellname>
ns.run .\examples\CEO_ns\RiskAgent.ns
agent run RiskAgent "Ein Partner fordert Kapital, waehrend die Kapazitaet knapp wird."
```

#### Vollen Lifecycle starten

```powershell
ai use lmstudio <modellname>
ns.run .\examples\CEO_ns\CEO_Lifecycle.ns
```

Danach entstehen Berichte unter `examples\CEO_ns\.nova_ceo\`.

## Beispiel-Suite `examples/code_improvement_ns`

Der Ordner [`examples/code_improvement_ns/`](../examples/code_improvement_ns/) zeigt, wie Nova-shell Quellcode prueft, verbessert, Kandidaten bewertet und die beste neue Variante in eine neue Datei oder ein neues Projektverzeichnis schreibt.

### Kern-Dateien

- [`Code_Improve_Lifecycle.ns`](../examples/code_improvement_ns/Code_Improve_Lifecycle.ns)
  Mehrstufiger Lifecycle mit `CodeReviewAgent`, `RefactorAgent`, `ReliabilityAgent`, `SimplifyAgent` und `SelectorAgent`.
- [`code_improve_runtime_helper.py`](../examples/code_improvement_ns/code_improve_runtime_helper.py)
  Python-Helper fuer Request-Laden, Prompt-Bau, Kandidatenparsing, Reparatur, Auswahl und Persistenz.
- [`README.md`](../examples/code_improvement_ns/README.md)
  Kurzbeschreibung fuer den Einsatz der Suite.

### Request- und Beispieldateien

- [`code_improvement_request.json`](../examples/code_improvement_ns/code_improvement_request.json)
  Standard-Request fuer den Einzeldateimodus.
- [`code_improvement_project_request.json`](../examples/code_improvement_ns/code_improvement_project_request.json)
  Request fuer den Projektmodus.
- [`sample_target.py`](../examples/code_improvement_ns/sample_target.py)
  Kleine Zieldatei fuer den Einzeldatei-Durchlauf.

### Demo-Projekt fuer Projektmodus

- [`demo_project/clean_numbers.py`](../examples/code_improvement_ns/demo_project/clean_numbers.py)
  Beispielmodul, das sich gut fuer Refactoring und Robustheitsverbesserungen eignet.
- [`demo_project/reporting.py`](../examples/code_improvement_ns/demo_project/reporting.py)
  Zweites Beispielmodul fuer einen Multi-Datei-Lauf.

### Typische Nutzung

#### Einzeldatei verbessern

```powershell
ai use lmstudio <modellname>
ns.run .\examples\code_improvement_ns\Code_Improve_Lifecycle.ns
```

Der Lifecycle liest den Request, verbessert den Code und schreibt die beste Variante in das konfigurierte `output_path`.

#### Projektmodus aktivieren

Setze die Inhalte von `code_improvement_project_request.json` als aktiven Request oder passe den Standard-Request auf `source_dir` an.

### Ergebnisdateien

Die Suite erzeugt typischerweise:

- eine verbesserte Ausgabedatei oder ein neues Projektverzeichnis unter `generated/`
- einen Bericht unter `.nova_code_improve/`

## Welche Beispiele sofort lokal sichtbar etwas tun

Wenn du moeglichst schnell ein greifbares Ergebnis sehen willst, beginne mit diesen Dateien:

1. [`file_extension_scan.ns`](../examples/file_extension_scan.ns)
2. [`file_extension_scan_advanced.ns`](../examples/file_extension_scan_advanced.ns)
3. [`blob_runtime.ns`](../examples/blob_runtime.ns)
4. [`decision_lifecycle_template.ns`](../examples/decision_lifecycle_template.ns)
5. [`CEO_ns/CEO_Lifecycle.ns`](../examples/CEO_ns/CEO_Lifecycle.ns)
6. [`code_improvement_ns/Code_Improve_Lifecycle.ns`](../examples/code_improvement_ns/Code_Improve_Lifecycle.ns)

## Welche Beispiele zuerst mit `ns.graph` sinnvoll sind

Diese Dateien sind besonders lehrreich, wenn du zuerst ihre Struktur statt den Lauf betrachtest:

- [`advanced_agent_fabric.ns`](../examples/advanced_agent_fabric.ns)
- [`ai_os_cluster.ns`](../examples/ai_os_cluster.ns)
- [`consensus_fabric_cluster.ns`](../examples/consensus_fabric_cluster.ns)
- [`control_plane_runtime.ns`](../examples/control_plane_runtime.ns)
- [`distributed_pipeline.ns`](../examples/distributed_pipeline.ns)
- [`replicated_control_plane.ns`](../examples/replicated_control_plane.ns)
- [`secure_multi_tenant.ns`](../examples/secure_multi_tenant.ns)
- [`service_package_platform.ns`](../examples/service_package_platform.ns)

## Empfohlene Lernreihenfolge

Wenn du den Ordner systematisch verstehen willst, ist diese Reihenfolge sinnvoll:

1. `file_extension_scan.ns`
   Einstieg in `dataset`, `flow`, `py.exec` und `system.log`.
2. `file_extension_scan_advanced.ns`
   Aufbau eines laengeren Flows mit Agent, State und HTML-Output.
3. `blob_runtime.ns`
   Einstieg in Blob-Artefakte.
4. `decision_lifecycle_template.ns`
   Grundform eines Agenten-Lifecycles.
5. `market_radar.ns` und `federated_swarm_memory.ns`
   Memory, Embeddings und Signalverdichtung.
6. `control_plane_runtime.ns` und `distributed_pipeline.ns`
   Events, Scheduler, Mesh- und Tool-Orchestrierung.
7. `CEO_ns/`
   Vollstaendige Rollen- und Lifecycle-Suite.
8. `code_improvement_ns/`
   Selbstverbesserung und codebezogene Agentenarbeit.
9. `composition_patterns_agents.ns`, `react_best_practices_agents.ns`, `react_native_skills_agents.ns`
   Grosse Standalone-Agentenkataloge.

## Verwandte Wiki-Seiten

- [`examples_index.md`](./examples_index.md)
  Zentrales Portal fuer alle Example-Dokumentationsseiten.
- [`examples_quickstart.md`](./examples_quickstart.md)
  Copy-Paste-Schnellstart fuer die vorhandenen Beispiele.
- [`examples_by_level.md`](./examples_by_level.md)
  Sortierung nach Einsteiger, Fortgeschritten, Plattform, Lifecycle und Agenten.
- [`examples_matrix.md`](./examples_matrix.md)
  Tabellarischer Schnellvergleich aller Beispieltypen.
- [`ExamplesAndRecipes.md`](./ExamplesAndRecipes.md)
  Breitere Rezeptsammlung und Einstiegsmuster.
- [`CEOAgentExamples.md`](./CEOAgentExamples.md)
  Tiefere Erklaerung der CEO-Suite.
- [`DecisionPatterns.md`](./DecisionPatterns.md)
  Muster fuer Entscheidungs- und Lifecycle-Design.
- [`Tutorials.md`](./Tutorials.md)
  Lernpfade und gefuehrte Schritte.
