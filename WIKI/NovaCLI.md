# Nova CLI

## Zweck

Die CLI ist nicht nur ein Befehlsstarter, sondern die operative Oberflaeche von Nova-shell.
Sie verbindet:

- die klassische Shell-Runtime
- die deklarative Nova-Runtime fuer `.ns`
- lokale AI-, Memory- und Atheria-Pfade
- Mesh-, Remote- und Plattformdienste

Wichtig ist deshalb die Unterscheidung zwischen drei Befehlsarten:

- sofort ausfuehrbare Einzelkommandos wie `py`, `memory`, `wiki`
- zustandsbehaftete Laufzeitkommandos wie `agent`, `mesh`, `vision`
- deklarative Runtime-Kommandos wie `ns.run`, `ns.graph`, `ns.control`

Diese Seite ist die Kommandoreferenz.
Wenn du mit Nova-shell wirklich programmieren willst, lies direkt dazu:

- [ProgrammingWithNovaShell](./ProgrammingWithNovaShell.md)
- [ShellCommandReference](./ShellCommandReference.md)
- [CodeReferenceIndex](./CodeReferenceIndex.md)

## Kernobjekte

- `NovaShell`
- `NovaShellCommandExecutor`
- `CommandResult`
- `MeshWorkerServer`
- `VisionServer`
- `NovaRuntime`

## Methoden und Schnittstellen

Die CLI hat drei Rueckgabeformen:

- Textausgabe fuer einfache Kommandos wie `py 1 + 1`
- JSON-Ausgabe fuer Status-, Listen- und Verwaltungsbefehle
- Seiteneffekte wie Dateierzeugung, Worker-Start, HTTP-Server oder Snapshots

Als Faustregel gilt:

- `status`, `list`, `show`, `config` liefern meist JSON
- `run`, `call`, `message`, `prompt` liefern meist Nutzdaten oder Text
- `start`, `stop`, `build`, `snapshot` veraendern Laufzeit oder Dateien

## CLI

### Grundform

Interaktive Nutzung:

```bash
nova-shell
```

Einzelkommando:

```bash
nova-shell --no-plugins -c "py 1 + 1"
```

JSON-freundliche Nutzung in PowerShell:

```powershell
nova-shell --no-plugins -c "doctor"
nova-shell --no-plugins -c "ai providers" | ConvertFrom-Json
```

### Kommandogruppen

#### Compute

| Kommando | Zweck | Direkt testbares Beispiel | Erwartung |
| --- | --- | --- | --- |
| `py` | Python-Ausdruecke und Code | `py 1 + 1` | Ausgabe `2` |
| `cpp` | native C++-Pfade | `cpp.sandbox int main(){ return 0; }` | Ausgabe `sandbox executed` |
| `gpu` | GPU/OpenCL-Pfade | `gpu graph show` | Struktur- oder Fehlerausgabe, wenn kein Graph geladen ist |
| `wasm` | WebAssembly-Ausfuehrung | `wasm .\module.wasm` | fuehrt ein vorhandenes WASM-Modul aus |
| `sys` | Shell-/Systemaufrufe | `sys echo hello` | Ausgabe `hello` |

#### AI und Knowledge

| Kommando | Zweck | Direkt testbares Beispiel | Erwartung |
| --- | --- | --- | --- |
| `ai` | Provider, Modelle und Prompts | `ai providers` | JSON-Liste verfuegbarer Provider |
| `atheria` | lokales Wissens- und Trainingssystem | `atheria status` | JSON mit `available`, `trained_records`, `core_loaded` |
| `agent` | Agenten, Instanzen und Graphen | `agent list` | JSON-Liste definierter Agenten |
| `memory` | Vector Memory und Namespaces | `memory status` | JSON mit Namespace und Projekt |
| `tool` | Tool-Registrierung und Tool-Aufrufe | `tool list` | JSON-Liste registrierter Tools |

#### Deklarative Runtime

| Kommando | Zweck | Direkt testbares Beispiel | Erwartung |
| --- | --- | --- | --- |
| `ns.exec` | Inline-Ausfuehrung | `ns.exec values = sys printf '1\n2\n'; for v in values:;     py $v` | Pipeline-Ausgabe aus Inline-Skript |
| `ns.run` | `.ns`-Datei ausfuehren | `ns.run .\control.ns` | Runtime laeuft und initialisiert Flows/Events |
| `ns.graph` | kompilierten Graph zeigen | `ns.graph .\control.ns` | JSON oder Graphbeschreibung |
| `ns.status` | Runtime- und Plattformstatus | `ns.status` | JSON mit geladenen Systemen und Laufzeitstatus |
| `ns.control` | Queue, API, Replay, Metrics | `ns.control status` | JSON mit Queue-, Event- und Schedule-Status |
| `ns.snapshot` | Snapshot schreiben | `ns.snapshot .\snap.json` | Snapshot-Datei wird erzeugt |
| `ns.resume` | Snapshot wieder laden | `ns.resume .\snap.json` | Snapshot wird wiederhergestellt |

#### Plattform

| Kommando | Zweck | Direkt testbares Beispiel | Erwartung |
| --- | --- | --- | --- |
| `mesh` | Worker und verteilte Ausfuehrung | `mesh start-worker --caps cpu,py` | lokaler Worker startet |
| `blob` | verifizierbare Seed-Kapselung, Rehydrierung und Mesh-Transport | `blob pack --text "21 * 2" --type py` | `.nsblob.json` und `inline_seed` werden erzeugt |
| `synth` | prädiktive Engine-Wahl und delegierte Ausfuehrung | `synth forecast` | JSON-Forecast oder Shift-Empfehlung |
| `wiki` | Markdown-Wiki nach HTML bauen und serven | `wiki build` | HTML-Site wird erzeugt |
| `remote` | Remote-Ausfuehrung | `remote http://127.0.0.1:PORT py 1 + 1` | Remote-Worker liefert Ergebnis |
| `vision` | Web- und UI-Flaechen | `vision start 8877` | lokaler Vision-Server startet |
| `guard` | Sicherheits- und Sandbox-Pfade | `guard list` | JSON mit Policies und eBPF-Profilen |

#### Watch Monitor als `.ns`-Betriebspfad

Der Projektmonitor ist kein eigenes Top-Level-Kommando.
Er wird ueber `ns.run` gestartet und arbeitet dann als langlebiger Beobachter im Projektordner.

Direkt testbares Beispiel:

```powershell
cd F:\DeCoG-TRI
ns.run nova_project_monitor.ns
```

Erwartung:

- `.nova_project_monitor/` wird aufgebaut
- der HTML-Report aktualisiert sich nach Projektänderungen
- je nach Konfiguration laufen Build, Tests und Review-Agent mit

## API

Die CLI spricht nicht nur lokal.
Mit `ns.control api start` stellt sie eine HTTP-Control-Plane bereit.
Fuer Endpunkte, Payloads und HTTP-Aufrufe siehe [APIReference](./APIReference.md).

## Beispiele

### Schnell pruefbar: AI und Knowledge

Die folgenden Befehle sind lokal testbar und benoetigen keine externe Cloud-Session.

#### Provider und AI-Konfiguration

```powershell
ai providers
ai config
```

Erwartung:

- `ai providers` liefert JSON mit den bekannten Providern
- `ai config` zeigt aktiven Provider, Modell und geladene Umgebungsdateien

#### Atheria initialisieren und pruefen

```powershell
atheria status
atheria init
```

Erwartung:

- `atheria status` zeigt, ob die lokale Atheria-Installation gefunden wurde
- `atheria init` laedt den Atheria-Kern und meldet danach `core_loaded`

#### Memory mit einem echten Suchlauf

```powershell
memory namespace docs
memory project wiki
memory embed --id intro "Nova-shell kombiniert CLI, Runtime, Graph und AI-OS."
memory search "Graph Runtime"
```

Erwartung:

- der `embed`-Aufruf legt einen neuen Memory-Eintrag an
- `memory search` liefert Treffer inklusive Score, Namespace und Projekt

#### Tool-Registrierung mit direktem Funktionsbeweis

```powershell
tool register greet --description "Greet user" --schema "{\"type\":\"object\",\"properties\":{\"name\":{\"type\":\"string\"}},\"required\":[\"name\"]}" --pipeline "py \"Hello \" + {{py:name}}"
tool call greet name=Nova
tool show greet
```

Erwartung:

- `tool register` erzeugt ein registriertes Tool
- `tool call greet name=Nova` gibt `Hello Nova` aus
- `tool show greet` zeigt Schema und Pipeline

#### Agenten: nur testbar, wenn ein Provider konfiguriert ist

```powershell
agent create helper "Summarize {{input}}" --provider lmstudio --model local-model --system "You are precise."
agent run helper quarterly report
agent show helper
```

Erwartung:

- `agent create` speichert die Agent-Definition
- `agent run` fuehrt den Prompt ueber den konfigurierten Provider aus
- `agent show` liefert Definition, Provider und Modell

Hinweis:
`agent` ist absichtlich nicht rein lokal wie `memory` oder `tool`.
Fuer produktive Tests muss ein funktionierender Provider oder lokaler Modellserver verfuegbar sein.

### Schnell pruefbar: Deklarative Runtime

Die folgenden Beispiele erzeugen erst eine kleine `.ns`-Datei und arbeiten dann mit `ns.run`, `ns.graph`, Queue und Snapshot.

#### Minimales Control-Plane-Beispiel anlegen

```powershell
@'
system control_plane {
  daemon_autostart: false
}

flow queued_job {
  system.log "queued" -> queue_output
  state.set queue_value queue_output
}

event ping_handler {
  on: ping
  flow: queued_job
}
'@ | Set-Content .\control.ns
```

#### Runtime laden und Graph anzeigen

```powershell
ns.run .\control.ns
ns.graph .\control.ns
ns.status
```

Erwartung:

- `ns.run` laedt das System, den Flow und den Event-Handler
- `ns.graph` zeigt den kompilierten Ausfuehrungsgraphen
- `ns.status` zeigt den aktuellen Runtime-Zustand

#### Queue, Event und Daemon testen

```powershell
ns.control queue enqueue queued_job
ns.control queue run
event emit ping now
ns.control events ping 0 10
ns.control status
```

Erwartung:

- `queue enqueue` stellt einen Lauf in die Queue
- `queue run` verarbeitet mindestens einen Eintrag
- `event emit` erzeugt ein Laufzeitereignis
- `ns.control events ping 0 10` zeigt das eingegangene Event

#### Blob-Seeds lokal testen

```powershell
blob pack --text "21 * 2" --type py
blob verify .\calc.nsblob.json
blob exec .\calc.nsblob.json
```

Erwartung:

- der Seed ist verifiziert
- `blob exec` liefert `42`

### Schnell pruefbar: Predictive Shifting

```powershell
py 1 + 1
py 2 + 1
py 3 + 1
synth forecast
synth shift suggest "for item in rows: total += item"
```

Erwartung:

- `synth forecast` liefert `status`, `engine_pressure` und `projection`
- `synth shift suggest ...` liefert `engine`, `delegated_command`, `pressure_index` und `reasons`

### Schnell pruefbar: Federated Learning Mesh

```powershell
mesh federated status
mesh federated publish --statement "Inter-core resonance raised" --namespace swarm --project lab
mesh federated history 5
```

Erwartung:

- Status der Federated-Schicht
- ein signiertes Update
- sichtbare Historie

### Schnell pruefbar: Co-Evolution

```powershell
mycelia coevolve run research-pop --cycles 2 --input "edge inference pressure rises"
mycelia coevolve status research-pop
```

Erwartung:

- Population wird bewertet
- Rueckgabe enthaelt Co-Evolution-Daten statt nur simpler Populationstakte

#### Snapshot und Resume

```powershell
ns.snapshot .\control-snapshot.json
ns.resume .\control-snapshot.json
ns.status
```

Erwartung:

- Snapshot-Datei entsteht auf dem Dateisystem
- `ns.resume` laedt den letzten Zustand wieder ein

### Schnell pruefbar: Plattform und Betrieb

#### Mesh lokal starten

```powershell
mesh start-worker --caps cpu,py
mesh list
mesh run py py 1 + 1
```

Erwartung:

- ein lokaler Worker wird auf `127.0.0.1` gestartet
- `mesh list` zeigt URL, Faehigkeiten und Heartbeat-Status
- `mesh run py py 1 + 1` fuehrt Python ueber den Worker aus

#### Remote gegen einen bekannten Worker testen

```powershell
remote http://127.0.0.1:8766 py 1 + 1
```

Erwartung:

- der angegebene Worker fuehrt den Befehl remote aus

Hinweis:
Die URL muss zu einem laufenden Worker passen.
Falls du den Port nicht kennst, starte erst `mesh start-worker --caps cpu,py` und lies ihn mit `mesh list` aus.

#### HTML-Wiki bauen und oeffnen

```powershell
wiki build
wiki serve --open
wiki status
wiki stop
```

Erwartung:

- `wiki build` erzeugt die HTML-Dateien
- `wiki serve --open` startet einen lokalen Server und oeffnet `Home.html`
- `wiki status` zeigt Build- und Serverstatus
- `wiki stop` beendet den lokalen Wiki-Server

#### Vision-Server starten

```powershell
vision start 8877
vision status
vision stop
```

Erwartung:

- ein lokaler HTTP-Server fuer Vision/UI startet auf Port `8877`
- `vision status` liefert `running` oder `stopped`

#### Guard und Sandbox pruefen

```powershell
guard list
guard sandbox on
guard sandbox status
guard sandbox off
guard ebpf-status
```

Erwartung:

- `guard list` zeigt eingebaute und geladene Policies
- `guard sandbox on|off` schaltet den Standard-Sandboxpfad um
- `guard ebpf-status` zeigt, ob Kernel-eBPF oder Userspace-Fallback aktiv ist

## Kommando-Referenz im Detail

### `ai`

Zweck:
Provider, Modellwahl, Prompt-Ausfuehrung und Planerzugriff.

Syntax:

```text
ai providers
ai models [provider]
ai use <provider> [model]
ai config
ai env reload [file]
ai plan <prompt>
ai prompt <prompt>
```

Wann benutzen:

- `providers` und `config` fuer Diagnose
- `use` fuer Provider- und Modellwechsel
- `plan` fuer Pipeline- oder Tool-Vorschlaege
- `prompt` fuer direkte Modellaufrufe

### `atheria`

Zweck:
lokales Wissenssystem, Kerninitialisierung, Suche, Chat, Sensoren und Evolution.

Syntax:

```text
atheria status
atheria init
atheria search <query>
atheria chat <prompt>
atheria sensor gallery|list|show ...
atheria evolve status|plan|simulate|apply ...
```

Wann benutzen:

- `status` und `init` als erster Integrationscheck
- `search` fuer lokales Wissens-Querying
- `chat` fuer Atheria-gestuetzte Interaktion
- `sensor` fuer Plugin- und Sensorpfade
- `evolve` fuer adaptive Wissens- und Systemanpassung

### `agent`

Zweck:
Agent-Definitionen, Laufzeitinstanzen, Agent-Workflows und Agent-Graphen.

Syntax:

```text
agent list
agent show <name>
agent create <name> <prompt_template> [--provider p] [--model m] [--system text]
agent run <name> [input]
agent spawn <instance_name> --from <agent>
agent message <instance_name> <message>
agent workflow --agents a,b[,c] --input text
agent graph create <name> --nodes a,b[,c] [--edges a>b,b>c]
agent graph run <name> --input text
```

Wann benutzen:

- `create` und `run` fuer einzelne Agenten
- `spawn` und `message` fuer zustandsbehaftete Instanzen
- `workflow` fuer lineare Mehragentenlaeufe
- `graph` fuer explizite Agent-DAGs

### `memory`

Zweck:
lokales semantisches Memory mit Namespace- und Projekt-Scope.

Syntax:

```text
memory namespace [name]
memory project [name]
memory status
memory embed [--id name] [--file path] [--meta json] <text>
memory search [--namespace n] [--project p] [--all] [--limit n] <query>
memory list
```

Wann benutzen:

- `namespace` und `project` fuer saubere Trennung von Daten
- `embed` fuer Wissensaufnahme
- `search` fuer Retrieval
- `status` und `list` fuer Scope- und Inhaltspruefung

### `tool`

Zweck:
registrierbare CLI- oder Runtime-Werkzeuge mit Schema und Pipeline-Template.

Syntax:

```text
tool list
tool show <name>
tool register <name> --description text --schema json --pipeline template
tool call <name> [json|key=value ...]
```

Wann benutzen:

- `register` fuer wiederverwendbare Operationen
- `call` fuer strukturierte Aufrufe mit validierten Argumenten
- `show` fuer Debugging und Schema-Pruefung

### `ns.exec`

Zweck:
Inline-Ausfuehrung eines kurzen Nova-Skripts ohne Datei.

Syntax:

```text
ns.exec <inline_script>
```

Wann benutzen:

- fuer schnelle Experimente
- fuer kurze Pipeline-Tests
- fuer Shell-nahe Skripte ohne `.ns`-Datei

### `ns.run`

Zweck:
eine `.ns`-Datei laden und in die deklarative Runtime uebernehmen.

Syntax:

```text
ns.run <script.ns>
```

Wann benutzen:

- fuer echte Programme
- fuer Flows, Events, Systeme, Services und Packages

### `ns.graph`

Zweck:
den kompilierten Graph einer deklarativen Nova-Datei sichtbar machen.

Syntax:

```text
ns.graph <script.ns>
```

Wann benutzen:

- vor dem ersten produktiven Lauf
- zur Fehlersuche bei Knoten, Kanten und Abhaengigkeiten

### `ns.status`

Zweck:
Momentaufnahme der geladenen deklarativen Runtime.

Syntax:

```text
ns.status
```

Wann benutzen:

- nach `ns.run`
- nach `ns.resume`
- nach Queue-, Schedule- oder API-Aktionen

### `ns.control`

Zweck:
Control-Plane fuer Queue, Scheduler, API, Events, State, Replikation, Workflows, Metrics, Services und Packages.

Syntax:

```text
ns.control status
ns.control queue enqueue <flow>
ns.control queue list
ns.control queue run
ns.control schedule add-flow <job> <flow> <interval_seconds>
ns.control daemon start|stop|tick|status
ns.control api start|stop|status [host] [port] [token]
ns.control metrics prometheus
```

Wann benutzen:

- fuer Betrieb und Observability
- fuer Replay, Scheduling und Queue-Tests
- fuer API- und Daemon-Steuerung

### `mesh`

Zweck:
Worker-Registry und verteilte Ausfuehrung.

Syntax:

```text
mesh add <worker_url> <cap1,cap2,...>
mesh list
mesh run <capability> <command>
mesh intelligent-run <capability> <command>
mesh beat <worker_url> [latency_ms] [handle1,handle2]
mesh start-worker --caps cpu,py
mesh stop-worker <worker_id|url|port>
```

Wann benutzen:

- fuer lokale oder entfernte Worker
- fuer Lastverteilung
- fuer capability-basierte Ausfuehrung

### `wiki`

Zweck:
die Projekt-Wiki lokal nach HTML bauen, serven und oeffnen.

Syntax:

```text
wiki status
wiki build
wiki serve [--host HOST] [--port PORT] [--open]
wiki open [PAGE]
wiki stop
```

Wann benutzen:

- fuer lokale Dokumentationsarbeit
- fuer HTML-Preview vor Release
- fuer Installer- und Bundle-Checks

### `remote`

Zweck:
ein einzelnes Kommando an einen bekannten Worker senden.

Syntax:

```text
remote <worker_url> <command>
```

Wann benutzen:

- fuer gezielte Remote-Ausfuehrung
- wenn die Ziel-URL schon bekannt ist

### `vision`

Zweck:
lokale Web- oder UI-Flaechen fuer Nova-shell starten und stoppen.

Syntax:

```text
vision start [port]
vision status
vision stop
```

Wann benutzen:

- fuer lokale Demo- oder UI-Pfade
- fuer Browser-gestuetzte Oberflaechen

### `guard`

Zweck:
Policy-, Sandbox- und eBPF-Steuerung.

Syntax:

```text
guard list
guard set <policy>
guard load <policy.yaml|policy.json>
guard sandbox on|off|status
guard ebpf-status
guard ebpf-compile <policy|file>
guard ebpf-enforce <policy|file>
guard ebpf-release
```

Wann benutzen:

- fuer Sicherheitsprofile
- fuer Sandbox-Steuerung
- fuer eBPF-gestuetzte Enforcement-Pfade

## Typische Fehlerbilder

### `agent run` liefert einen Providerfehler

Ursache:

- kein Provider aktiv
- lokaler Modellserver nicht gestartet
- API-Schluessel oder `.env` fehlt

Erster Check:

```powershell
ai providers
ai config
```

### `remote` oder `mesh run` findet keinen Worker

Ursache:

- kein Worker gestartet
- URL oder Port falsch
- Capability fehlt

Erster Check:

```powershell
mesh list
```

### `cpp.sandbox` oder `wasm` schlagen fehl

Ursache:

- `emcc` oder `wasmtime` fehlen
- Sandbox-Konfiguration ist nicht aktiv

Erster Check:

```powershell
doctor
cpp.sandbox int main(){ return 0; }
```

### `ns.graph` oder `ns.run` schlagen auf einer Datei fehl

Ursache:

- Syntaxfehler in `.ns`
- falscher Laufzeitpfad
- Datei ist keine deklarative Nova-Datei

Erster Check:

```powershell
ns.graph .\control.ns
```

## Verwandte Seiten

- [ExamplesAndRecipes](./ExamplesAndRecipes.md)
- [ProgrammingWithNovaShell](./ProgrammingWithNovaShell.md)
- [ShellCommandReference](./ShellCommandReference.md)
- [CodeReferenceIndex](./CodeReferenceIndex.md)
- [NSBlobGenerator](./NSBlobGenerator.md)
- [NovaSynthPredictiveEngineShifting](./NovaSynthPredictiveEngineShifting.md)
- [ZeroCopyFederatedLearningMesh](./ZeroCopyFederatedLearningMesh.md)
- [MyceliaAtheriaCoEvolution](./MyceliaAtheriaCoEvolution.md)
- [APIReference](./APIReference.md)
- [NovaLanguage](./NovaLanguage.md)
- [NovaRuntime](./NovaRuntime.md)
- [ClassReference](./ClassReference.md)
- [PageTemplate](./PageTemplate.md)
- [WatchMonitor](./WatchMonitor.md)
- [WatchMonitorAutomationAndAI](./WatchMonitorAutomationAndAI.md)
