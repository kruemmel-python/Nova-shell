# Nova-shell Dokumentation

Diese Datei ist die zentrale Gesamt- und Kommandoreferenz fuer Nova-shell `0.8.15`.
Sie beschreibt die heute vorhandenen Hauptschichten des Systems:

- Shell und polyglotte Runtime
- Nova Language und deklarative `.ns`-Programme
- Agenten, Atheria und Memory
- Mesh, Control Plane und verteilte Ausfuehrung
- Blob-Seeds, Predictive Shifting und Federated Learning
- HTML-Wiki, Watch Monitor und Release-Pfade

Die Dokumentation beschreibt bewusst den **tatsaechlich vorhandenen** Stand des Projekts. Sie ist deshalb keine Sammlung maximaler Zukunftsbehauptungen, sondern ein Arbeitsdokument fuer reale Nutzung, Einfuehrung und Weiterentwicklung.

Wenn du mit Nova-shell neu beginnst, lies zunaechst:

- [Was-es-Ist.md](Was-es-Ist.md)
- [Whitepaper.md](Whitepaper.md)
- [WIKI/QuickStart.md](WIKI/QuickStart.md)
- [WIKI/nsCreate.md](WIKI/nsCreate.md)

## 1. Grundprinzip

Nova-shell ist nicht nur eine Shell fuer Befehle.
Nova-shell kombiniert heute drei Ebenen:

1. interaktive CLI und Runtime
2. deklarative Sprache fuer `.ns`
3. AI-OS- und Control-Plane-Schicht fuer Agenten, Wissen und Mesh

Das gemeinsame Modell dahinter lautet:

- Eingaben koennen lokal, deklarativ oder ereignisgetrieben entstehen
- Ausfuehrung kann ueber Python, C++, GPU, WASM, AI oder Mesh erfolgen
- Ergebnisse koennen in State, Memory, Atheria, Reports oder Events zurueckfliessen

Wirtschaftlich interessant ist Nova-shell vor allem dort, wo heute mehrere getrennte Werkzeuge fuer Shell-Automation, Projektbeobachtung, AI-Workflows, Dokumentation und verteilte Jobs parallel gepflegt werden.

## 1.1 Wo Nova-shell heute besonders sinnvoll ist

Nova-shell bringt aktuell besonders dann Nutzen, wenn mindestens eines dieser Muster vorliegt:

- wiederkehrende Projekt- und Analyseablaeufe
- hoher Glue-Code-Aufwand zwischen mehreren Werkzeugen
- Bedarf an lokaler oder hybrider AI-Unterstuetzung
- Bedarf an watch- oder event-getriebener Automatisierung
- hoher Dokumentations-, Review- oder Auditdruck

## 2. Schreibweise und Bedienlogik

- `cmd1 | cmd2`: Das Ergebnis der ersten Stage wird an die zweite weitergereicht.
- `parallel <command>`: Wendet dieselbe Stage auf mehrere Eingaben an.
- Relative Pfade beziehen sich auf `pwd` und `cd` innerhalb der Nova-shell-Session.
- Nicht registrierte Kommandos fallen auf die System-Shell zurueck.
- Fuer explizite Shell-Aufrufe ist `sys` der klarere Weg.
- PowerShell-Umgebungsvariablen wie `$env:NAME="wert"` setzt du ausserhalb der Nova-shell-REPL.

## 3. Schnelluebersicht der Kommandofamilien

Die Kommandofamilien decken nicht alle denselben Reifegrad oder denselben wirtschaftlichen Nutzen ab. Fuer die meisten Teams liegen die schnellsten produktiven Gewinne heute in:

- `watch`, `wiki`, `vision`
- `atheria`, `agent`, `memory`
- `blob`
- `mesh`
- `ns.run`, `ns.graph`, `ns.status`

### Basis

- `help`
- `doctor`
- `pwd`
- `cd`
- `clear`
- `cls`
- `exit`
- `sys`

### Compute und Engines

- `py`
- `python`
- `cpp`
- `cpp.sandbox`
- `cpp.expr`
- `cpp.expr_chain`
- `gpu`
- `wasm`
- `jit_wasm`

### Daten und Handles

- `data`
- `data.load`
- `watch`
- `zero`
- `fabric`

### AI und Knowledge

- `ai`
- `atheria`
- `agent`
- `mycelia`
- `memory`
- `tool`

### Event, Analyse und Workflow

- `event`
- `events`
- `flow`
- `sync`
- `reactive`
- `dflow`
- `on`
- `observe`
- `pulse`
- `lens`
- `rag`
- `studio`

### Optimierung, Graphen und Mobilitaet

- `opt`
- `synth`
- `graph`
- `blob`

### Verteilung und Plattform

- `remote`
- `mesh`
- `vision`
- `wiki`
- `pack`

### Deklarative Runtime und Plattformsteuerung

- `ns.exec`
- `ns.run`
- `ns.graph`
- `ns.status`
- `ns.control`
- `ns.snapshot`
- `ns.resume`
- `ns.cluster`
- `ns.auth`
- `ns.deploy`
- `ns.recover`

### Sicherheit

- `guard`
- `secure`

## 4. Basisbefehle

### `help`

- `help`: Listet die registrierten Hauptkommandos.

### `doctor`

- `doctor`: Zeigt Runtime-, Modul- und Toolchain-Status.
- `doctor json`: Gibt dieselben Informationen als JSON aus.

### `pwd`

- `pwd`: Zeigt das aktuelle Nova-shell-Arbeitsverzeichnis.

### `cd`

- `cd <pfad>`: Wechselt das Arbeitsverzeichnis der Nova-shell-Session.
- `cd`: Springt ins Home-Verzeichnis.

### `clear` und `cls`

- `clear`: Leert die Konsole.
- `cls`: Windows-Alias fuer `clear`.

### `exit`

- `exit`: Beendet die REPL.

### `sys`

- `sys <kommando>`: Fuehrt ein Shell-/Systemkommando explizit im aktuellen Nova-shell-CWD aus.

Beispiel:

```text
sys dir
```

## 5. Python, C++, GPU und WASM

### `py` und `python`

- `py <python_code>`: Fuehrt Python-Code in der persistenten Nova-shell-Python-Session aus.
- `python <python_code>`: Alias fuer `py`.

Beispiele:

```text
py 1 + 2
python _.strip().upper()
```

Mehrzeilig:

```text
py with open("items.csv","w",encoding="utf-8") as f:
    f.write("id,name\n1,Brot\n")
```

### `cpp`

- `cpp <cpp_code>`: Kompiliert und fuehrt nativen C++20-Code aus.

### `cpp.sandbox`

- `cpp.sandbox <cpp_code>`: Kompiliert C++ nach WASM und fuehrt es kontrolliert aus.

### `cpp.expr`

- `cpp.expr <ausdruck mit x>`: Baut einen kleinen C++-Kernel fuer Zahlenpipelines.

### `cpp.expr_chain`

- `cpp.expr_chain <expr1 ; expr2 ; ...>`: Fuehrt mehrere mathematische Schritte als fusionierten C++-Kernel aus.

### `gpu`

- `gpu <kernel_file>`
- `gpu graph plan <kernel1> [kernel2 ...]`
- `gpu graph run <kernel1> [kernel2 ...]`
- `gpu graph show <graph_id>`

### `wasm`

- `wasm <module.wasm>`: Fuehrt ein vorhandenes WASM-Modul aus.

### `jit_wasm`

- `jit_wasm <arithmetischer_ausdruck>`: Kompiliert einen einfachen Ausdruck in den WASM-Pfad.

## 6. Daten, Handles und Zero-Copy

### `data` und `data.load`

- `data load <csv_file>`
- `data load <csv_file> --arrow`
- `data.load <csv_file>`

### `watch`

- `watch <file>`
- `watch <file> --lines N`
- `watch <file> --follow-seconds S`

### `zero`

- `zero put <text>`
- `zero put-arrow <csv>`
- `zero get <handle>`
- `zero list`
- `zero release <handle>`

### `fabric`

- `fabric put <text>`
- `fabric get <handle>`
- `fabric put-arrow <csv>`
- `fabric remote-put <url> <text>`
- `fabric remote-get <url> <handle>`
- `fabric rdma-put <url> <file>`
- `fabric rdma-get <url> <handle> <out_file>`

## 7. Blob-Seeds und mobile Logik

Nova-shell kann Logikbausteine als verifizierbare, komprimierte Seeds kapseln.

### `blob`

- `blob pack <file> [--type auto|ns|py|text|bin]`
- `blob pack --text <content> [--type auto|ns|py|text|bin]`
- `blob info <blob_file|inline_seed>`
- `blob verify <blob_file|inline_seed>`
- `blob inline <blob_file|inline_seed>`
- `blob unpack <blob_file|inline_seed> [--output file]`
- `blob exec <blob_file|inline_seed>`
- `blob exec-inline <inline_seed>`
- `blob mesh-run <capability> <blob_file|inline_seed>`

Beispiel:

```text
blob pack --text "21 * 2" --type py
blob verify C:\Users\ralfk\.nova_shell_memory\ns_blobs\inline-blob-....nsblob.json
blob exec C:\Users\ralfk\.nova_shell_memory\ns_blobs\inline-blob-....nsblob.json
```

Wichtig:

- `blob exec-inline` erwartet den vollstaendigen `nsblob:...`-Seed.
- `nsblob:...` mit drei Punkten ist nur ein Platzhalter in Doku und Beispielen, kein ausfuehrbarer Wert.

Wirtschaftlich ist dieser Bereich besonders dann interessant, wenn Logik zwischen Projekten, Workern oder Standorten transportiert werden soll, ohne jedes Mal neue Verzeichnis- oder Installationslogik aufzubauen.

Mehr dazu:

- [WIKI/NSBlobGenerator.md](WIKI/NSBlobGenerator.md)
- [WIKI/TutorialBlobSeeds.md](WIKI/TutorialBlobSeeds.md)

## 8. AI, Atheria, Agenten und Memory

Dieser Bereich ist einer der staerksten Nova-shell-Pfade fuer praktischen Nutzen, weil hier Wissensnutzung, Analyse und operative Automatisierung zusammenlaufen.

### `ai`

- `ai providers`
- `ai models [provider]`
- `ai use <provider> [model]`
- `ai config`
- `ai env reload [file]`
- `ai prompt <prompt>`
- `ai prompt --file <pfad> <prompt>`
- `ai plan <ziel>`
- `ai plan --run <ziel>`

### `atheria`

Wichtige Pfade:

- `atheria status`
- `atheria init`
- `atheria train qa --question <text> --answer <text>`
- `atheria train file <file> [--category name]`
- `atheria train memory <memory_id> [--category name]`
- `atheria search <query>`
- `atheria chat <prompt>`
- `atheria chat --file <pfad> <prompt>`
- `atheria sensor ...`
- `atheria guardian ...`
- `atheria evolve status|plan|simulate|apply`

Beispiel:

```text
atheria init
atheria train file Whitepaper.md --category whitepaper
atheria search "Nova-shell runtime"
atheria chat "What is Nova-shell?"
```

### `agent`

Wichtige Pfade:

- `agent create <name> <prompt>`
- `agent run <name> <input>`
- `agent workflow ...`
- `agent graph ...`
- `agent spawn ...`
- `agent message ...`

### `mycelia`

Wichtige Pfade:

- `mycelia population create ...`
- `mycelia population tick ...`
- `mycelia population status ...`
- `mycelia select ...`
- `mycelia lineage ...`
- `mycelia coevolve run <population> [--cycles n]`
- `mycelia coevolve status <population>`

### `memory`

- `memory namespace <name>`
- `memory project <name>`
- `memory embed --id <id> <text|--file>`
- `memory search <query>`
- `memory show <id>`

### `tool`

- `tool register ...`
- `tool call ...`
- `tool list`
- `tool show <name>`

## 9. Event-, Flow- und Analysebefehle

### `event` und `events`

- `event emit <name> [payload]`
- `events last`
- `events stats`
- `events history`

### `flow`

- `flow state set <key> <value>`
- `flow state get <key>`
- `flow state count`
- `flow state last`

### `sync`

- CRDT- und Synchronisationskommandos fuer Counter- und Map-Pfade.

### `reactive`

- Lokale reaktive Trigger und Lebenszykluspfade.

### `dflow`

- `dflow subscribe <event> <pipeline>`
- `dflow publish <event> <payload> [--broadcast]`
- `dflow list`

### `on`

- Dateibasierte Trigger-Pipelines.

### `observe`

- `observe run <command>`: Fuehrt ein Kommando beobachtbar aus.

### `pulse`

- `pulse status`
- `pulse snapshot`

`pulse status` ist besonders wichtig, weil dort auch prädiktive Engine-Signale mit einfliessen koennen.

### `lens`

- Snapshots, Replay, Forks und Diff-Ansichten.

### `rag`

- `rag ingest`
- `rag watch`

### `studio`

- Hilfspfade fuer Completion-, Graph- und Entwicklungsunterstuetzung.

## 10. Optimierung, Graphen und prädiktive Steuerung

### `opt`

- Optimierungs- und Suggestion-Pfade fuer Pipelines und Compute-Stages.

### `graph`

- Graph-Planung und Laufzeitdarstellung fuer Pipelines.

### `synth`

NovaSynth ist die prädiktive Schicht fuer Engine-Wahl und Shift-Empfehlungen.

Wichtige Befehle:

- `synth forecast`
- `synth suggest <code>`
- `synth autotune <code>`
- `synth shift suggest <code>`
- `synth shift run <code>`

Beispiele:

```text
synth forecast
synth shift suggest "for item in rows: total += item"
```

Mehr dazu:

- [WIKI/NovaSynthPredictiveEngineShifting.md](WIKI/NovaSynthPredictiveEngineShifting.md)

Realistisch ist dieser Bereich heute vor allem fuer:

- Ressourcenauswahl
- Laufzeitempfehlungen
- experimentelle Optimierung

Er ist weniger als vollautonome Universalsteuerung zu lesen, sondern als gezielte Laufzeitverbesserung in passenden Szenarien.

## 11. Mesh, Federated Learning und Remote

Die groesste wirtschaftliche Wirkung liegt hier meist nicht in "globalem Clusterbetrieb", sondern in der pragmatischen Nutzung vorhandener Rechner, Worker und Standorte.

### `remote`

- Remote-Ausfuehrung auf einem expliziten Endpunkt.

### `mesh`

Wichtige Pfade:

- `mesh add`
- `mesh list`
- `mesh run`
- `mesh intelligent-run`
- `mesh beat`
- `mesh start-worker`
- `mesh stop-worker`

Federated Learning Mesh:

- `mesh federated status`
- `mesh federated history [limit]`
- `mesh federated publish --statement <text> [...] [--broadcast]`
- `mesh federated chronik-latest [...] [--broadcast]`

Beispiele:

```text
mesh federated status
mesh federated publish --statement "Inter-core resonance raised" --namespace swarm --project lab --broadcast
mesh federated history 5
```

Mehr dazu:

- [WIKI/ZeroCopyFederatedLearningMesh.md](WIKI/ZeroCopyFederatedLearningMesh.md)

### `vision`

- UI- und Webflaechen fuer Briefings, Live-Ansichten und lokale Oberflaechen.

### `pack`

- Build-/Bundle-Pfade fuer Artefakte und Paketlogik.

## 12. HTML-Wiki

Nova-shell kann seine Wiki lokal als moderne HTML-Dokumentation bauen und serven.

### `wiki`

- `wiki build`
- `wiki build --source WIKI --output .nova\wiki-site`
- `wiki serve --open`
- `wiki status`
- `wiki open Home`
- `wiki stop`

Beispiele:

```text
wiki build
wiki serve --open
```

Das ist wirtschaftlich besonders nuetzlich fuer Teams, die technische Dokumentation nicht als Nebenprodukt, sondern als lauffaehigen Teil ihrer Plattform behandeln wollen.

## 13. Nova Language und deklarative Runtime

Nova-shell hat mit der Nova Language einen eigenen deklarativen Programmierpfad.

### `ns.exec`

- Fuehrt inline Nova-Quelltext aus.

### `ns.run`

- Fuehrt eine `.ns`-Datei aus.

### `ns.graph`

- Zeigt den kompilierten Graph einer `.ns`-Datei.

### `ns.status`

- Zeigt Runtime-, Plattform- und Kontextstatus.

### `ns.control`

- Queue, Scheduler, Replay, API, State, Replica, Workflow, Metrics, Services und Packages.

### `ns.snapshot`

- Schreibt einen Snapshot des deklarativen Runtime-Zustands.

### `ns.resume`

- Laedt einen Snapshot wieder.

### `ns.cluster`

- Cluster- und Leader-/Node-nahe Verwaltungsbefehle.

### `ns.auth`

- Auth-, Trust-, Worker- und Namespace-Pfade.

### `ns.deploy`

- Rollout- und Health-Auswertung.

### `ns.recover`

- Recovery- und Playbook-Pfade.

Beispiel:

```text
ns.graph examples\blob_runtime.ns
ns.run examples\blob_runtime.ns
ns.status
```

Mehr dazu:

- [WIKI/nsCreate.md](WIKI/nsCreate.md)
- [WIKI/nsReference.md](WIKI/nsReference.md)
- [WIKI/nsPatterns.md](WIKI/nsPatterns.md)

## 14. Watch Monitor und Projektanalyse

Der Watch Monitor ist eine `.ns`-basierte Projektueberwachung mit HTML-Reports, Diffs, Hotspots, Automation und AI-Review.

Wichtige Punkte:

- Projektordner live ueberwachen
- Datei- und Zeilen-Diffs protokollieren
- HTML-Reports aktualisieren
- Build-/Test-Automation optional ausloesen
- Atheria, LM Studio, Ollama oder OpenAI-kompatible Provider fuer Reviews nutzen

Der Watch Monitor ist derzeit einer der unmittelbarsten Nova-shell-Nutzenpfade fuer Unternehmen, weil er ohne grosse Zusatzarchitektur direkte Transparenz, Review-Hilfe und Projektbeobachtung liefert.

Wichtige Seiten:

- [WIKI/WatchMonitor.md](WIKI/WatchMonitor.md)
- [WIKI/WatchMonitorQuickStart.md](WIKI/WatchMonitorQuickStart.md)
- [WIKI/WatchMonitorReportReference.md](WIKI/WatchMonitorReportReference.md)
- [WIKI/WatchMonitorAutomationAndAI.md](WIKI/WatchMonitorAutomationAndAI.md)
- [WIKI/WatchMonitorTroubleshooting.md](WIKI/WatchMonitorTroubleshooting.md)
- [WIKI/TutorialProjectWatchMonitor.md](WIKI/TutorialProjectWatchMonitor.md)

## 15. Sicherheit

### `guard`

Wichtige Pfade:

- `guard sandbox on|off|status`
- `guard ebpf-status`
- `guard ebpf-compile <policy>`
- `guard ebpf-enforce <policy>`
- `guard ebpf-release`

### `secure`

- Zusätzliche Security- und Policy-Pfade fuer kontrollierte Ausfuehrung.

## 16. Lernen in der richtigen Reihenfolge

Empfohlene Reihenfolge:

1. `help`, `doctor`, `py`, `sys`
2. `data`, `watch`, `zero`, `fabric`
3. `ai`, `atheria`, `agent`, `memory`
4. `blob`, `synth`, `mesh federated`
5. `wiki build`
6. `ns.run`, `ns.graph`, `ns.status`
7. Watch Monitor und Control Plane

Diese Reihenfolge ist auch wirtschaftlich sinnvoll: zuerst die Bereiche nutzen, die schnell Sichtbarkeit und Produktivitaet schaffen, danach die tieferen Plattform- und Verteilungsschichten.

## 17. Weiterfuehrende Dateien

- [Was-es-Ist.md](Was-es-Ist.md)
- [Whitepaper.md](Whitepaper.md)
- [WIKI/Home.md](WIKI/Home.md)
- [WIKI/NovaCLI.md](WIKI/NovaCLI.md)
- [WIKI/NovaLanguage.md](WIKI/NovaLanguage.md)
- [WIKI/NovaRuntime.md](WIKI/NovaRuntime.md)
- [WIKI/NovaAgents.md](WIKI/NovaAgents.md)
- [WIKI/NovaMesh.md](WIKI/NovaMesh.md)
- [WIKI/ExamplesAndRecipes.md](WIKI/ExamplesAndRecipes.md)
