# Tutorial: Programmieren mit Nova-shell

## Ziel dieses Tutorials

Dieses Tutorial zeigt Schritt fuer Schritt, wie man in Nova-shell programmiert. Der Fokus liegt auf echten, copy-paste-faehigen Beispielen mit dem aktuellen Stand von Nova-shell 0.8.11.

Die Beispiele sind in erster Linie fuer die interaktive Nova-shell gedacht. Viele Kommandos bauen auf dem Zustand derselben Session auf, zum Beispiel Python-Variablen, Flow-State, Lens-Snapshots oder Zero-Handles.

## 1. Nova-shell starten

Interaktiv:

```bash
python -m nova_shell
```

oder nach Installation:

```bash
nova-shell
```

Einzelne Kommandos ohne REPL:

```bash
nova-shell --no-plugins -c "py 1 + 2"
```

Wichtig:

- In der REPL bleibt der Zustand erhalten.
- Bei `-c` startet jedes Kommando eine neue Session.
- Fuer dieses Tutorial ist die REPL meist die bessere Wahl.

## 2. Erste Orientierung

Verfuegbare Kommandos anzeigen:

```text
nova> help
```

Runtime und Toolchain pruefen:

```text
nova> doctor
nova> doctor json
```

Arbeitsverzeichnis pruefen und wechseln:

```text
nova> pwd
nova> cd .
nova> pwd
```

## 3. Mit Python in Nova-shell programmieren

Der einfachste Einstieg ist `py`.

Ein Ausdruck:

```text
nova> py 1 + 2
3
```

Variablen in der REPL:

```text
nova> py x = 10
nova> py x + 5
15
```

Python kann auch komplexere Datentypen direkt verarbeiten:

```text
nova> py {"name": "Nova", "version": 0.8}
{'name': 'Nova', 'version': 0.8}
```

Merke:

- `py ...` fuehrt Python-Code in einer persistenten Python-Session aus.
- In derselben REPL bleiben Variablen erhalten.
- Das ist ideal fuer schnelles Experimentieren.

## 4. Pipelines verstehen

Nova-shell arbeitet stark pipeline-orientiert. Das Ergebnis einer Stage kann direkt in die naechste Stage fliessen.

Einfaches Textbeispiel:

```text
nova> echo hello | py _.strip().upper()
HELLO
```

Hier bedeutet `_`:

- bei Text-Pipelines: der aktuelle Text
- bei Objekt-Pipelines: das aktuelle Python-Objekt

Mehrstufige Pipeline:

```text
nova> echo hello | py _.strip() | py _.upper()
HELLO
```

Pipes in Strings bleiben erhalten:

```text
nova> py "a|b"
a|b
```

## 5. Parallel ueber Eingaben laufen

Mit `parallel` kann dieselbe Stage auf mehrere Elemente angewendet werden.

```text
nova> printf 'a\nb\n' | parallel py _.upper()
A
B
```

Das ist praktisch fuer:

- Zeilenverarbeitung
- Batch-Transformationen
- parallele Vorstufen vor spaeterer Aggregation

## 6. Mit CSV und strukturierten Daten arbeiten

Lege zunaechst eine Datei `items.csv` an:

```csv
name,price
apple,1.5
banana,2.0
orange,2.5
```

CSV laden:

```text
nova> data load items.csv
[{"name": "apple", "price": "1.5"}, {"name": "banana", "price": "2.0"}, {"name": "orange", "price": "2.5"}]
```

Mit den geladenen Datensaetzen weiterrechnen:

```text
nova> data load items.csv | py len(_)
3
```

Durchschnitt berechnen:

```text
nova> data load items.csv | py sum(float(r["price"]) for r in _) / len(_)
2.0
```

Arrow-Modus verwenden:

```text
nova> data load items.csv --arrow
```

Hinweis:

- `--arrow` benoetigt `pyarrow`.
- Pruefe den Status mit `doctor`.

## 7. Dateien beobachten und Streams verarbeiten

Die einfachste Form ist ein Tail auf die letzten Zeilen:

```text
nova> watch app.log --lines 5
```

Datei kurzzeitig live verfolgen:

```text
nova> watch app.log --follow-seconds 5 | py _.upper()
```

Typische Einsatzmuster:

- Logs normalisieren
- Fehler oder Warnungen extrahieren
- Live-Events in weitere Pipelines uebergeben

## 8. Beobachtbarkeit: Events, Observe und Lens

Eine Ausfuehrung tracebar machen:

```text
nova> observe run py 2 + 3
{"trace_id": "...", "result_preview": "5\n", "stats": {...}}
```

Letztes Event ansehen:

```text
nova> events last
```

Event-Statistik:

```text
nova> events stats
```

Pulse-Status und Snapshot:

```text
nova> pulse status
nova> pulse snapshot
```

Lens-Snapshots verwenden:

```text
nova> py 40 + 2
42
nova> lens last
```

Danach kannst du mit der Snapshot-ID weiterarbeiten:

```text
nova> lens show <snapshot_id>
nova> lens replay <snapshot_id>
```

Lens ist hilfreich, wenn du wissen willst:

- welches Ergebnis eine Stage geliefert hat
- welche Pipeline zuletzt gelaufen ist
- ob ein Ergebnis spaeter reproduzierbar ist

## 9. Zero-Copy mit NovaZero

NovaZero speichert Payloads in einem Shared-Memory-Pool und gibt dafuer Handles zurueck.

Text speichern:

```text
nova> zero put hello-zero
{"handle": "wnsm_...", "size": 10, "type": "text", "refs": 1}
```

Alle Handles auflisten:

```text
nova> zero list
```

Handle wieder lesen:

```text
nova> zero get <handle>
hello-zero
```

Handle freigeben:

```text
nova> zero release <handle>
released
```

CSV direkt als Arrow in den Pool schreiben:

```text
nova> zero put-arrow items.csv
```

Hinweis:

- `zero put-arrow` benoetigt `pyarrow`.
- Zero-Handles sind besonders interessant fuer engine-uebergreifende Datenpfade.

## 10. Fabric fuer Datentransfer

Lokalen Wert in Fabric schreiben:

```text
nova> fabric put hello-fabric
<handle>
```

Wert wieder lesen:

```text
nova> fabric get <handle>
hello-fabric
```

Arrow-CSV ueber Fabric registrieren:

```text
nova> fabric put-arrow items.csv
```

Fabric ist relevant, wenn du Daten nicht nur lokal in einer Pipeline weiterreichen, sondern explizit als Handle verwalten willst.

## 11. NovaScript lernen

NovaScript ist die eingebaute DSL von Nova-shell. Du kannst inline arbeiten oder Skripte aus Dateien ausfuehren.

### 11.1 Inline mit `ns.exec`

Dieses Beispiel erzeugt zwei Werte und iteriert darueber:

```text
nova> ns.exec values = sys printf '1\n2\n'; for v in values:;     py $v
1
2
```

### 11.2 Ein Skript aus Datei mit `ns.run`

Lege `sample.ns` an:

```text
x = py 5*5
py $x
```

Dann ausfuehren:

```text
nova> ns.run sample.ns
25
```

### 11.3 Watches in NovaScript

Lege dafuer `watch.ns` an:

```text
value = py 1 + 1
watch value:
    py "updated: " + $value
```

Lade das Skript:

```text
nova> ns.run watch.ns
```

Danach kannst du in derselben Session ein Event ausloesen:

```text
nova> ns.emit value 42
```

### 11.4 Contracts pruefen

Ein Skript statisch pruefen:

```text
nova> ns.check sample.ns
```

## 12. Flow-State und CRDT-Sync

Nova-shell kann zustaendige Runtime-Daten ablegen.

Flow-State setzen und lesen:

```text
nova> flow state set mode active
ok
nova> flow state get mode
active
```

Aktivitaet der letzten Sekunden zaehlen:

```text
nova> flow count-last 10 py*
```

CRDT-Counter inkrementieren:

```text
nova> sync inc global_counter 2
2
nova> sync get global_counter
2
```

Key/Value im Sync-Store:

```text
nova> sync set feature_x enabled
ok
nova> sync get-key feature_x
enabled
```

Kompletten Sync-Zustand exportieren:

```text
nova> sync export
```

## 13. Reaktive Workflows

Dateibasierter Trigger:

```text
nova> reactive on-file './incoming/*.txt' 'py _.endswith(".txt")'
```

Trigger ansehen:

```text
nova> reactive list
```

Trigger stoppen:

```text
nova> reactive stop <id>
```

Alle Trigger loeschen:

```text
nova> reactive clear
```

Dieses Modell eignet sich fuer:

- eingehende Dateien
- asynchrone Batch-Verarbeitung
- lokale Automatisierung

## 14. Event-Driven Runtime

Lokale Event-Subscriptions anlegen:

```text
nova> event on local_event 'py _.upper()'
subscribed
```

Event emittieren:

```text
nova> event emit local_event hello nova
```

Event-Historie ansehen:

```text
nova> event history 10
```

Wenn Mesh-Worker vorhanden sind, kann das Event auch verteilt werden:

```text
nova> event emit local_event hello nova --broadcast
```

## 15. Verteilte Events mit NovaFlow

Auf ein Event abonnieren:

```text
nova> dflow subscribe test_event 'py _ + "!"'
subscribed
```

Alle Subscriptions anzeigen:

```text
nova> dflow list
```

Event publizieren:

```text
nova> dflow publish test_event ping
```

Wenn Mesh-Worker existieren, kann mit `--broadcast` auch remote verteilt werden:

```text
nova> dflow publish test_event ping --broadcast
```

## 16. NovaSynth und Optimierung

AI-Provider-Konfiguration anzeigen:

```text
nova> ai providers
nova> ai config
```

Modelle fuer LM Studio oder einen anderen Provider anzeigen:

```text
nova> ai models lmstudio
nova> ai use lmstudio local-model
```

`.env` erneut laden:

```text
nova> ai env reload
```

Live-Prompt gegen den aktiven Provider senden:

```text
nova> ai prompt "Summarize this dataset"
```

Fuer echte Datenkontexte ist die Datei- oder Pipeline-Variante besser:

```text
nova> ai prompt --file items.csv "Summarize this dataset"
nova> data load items.csv | ai prompt "Summarize this dataset"
```

Wenn ein lokales Modell in LM Studio langsam startet, kann das Timeout ueber `LM_STUDIO_TIMEOUT` oder global ueber `NOVA_AI_TIMEOUT` erhoeht werden.

Die lokale Atheria-KI direkt aus dem Repo laden, trainieren und ansprechen:

```text
nova> atheria status
nova> atheria init
nova> atheria train qa --question "What is Nova-shell?" --answer "Nova-shell is a unified compute runtime." --category product
nova> atheria train file podcastVideoTranscript_publish_safe.md --category video
nova> atheria search "Nova-shell runtime"
nova> atheria chat "What is Nova-shell?"
```

### 16.1 Atheria-Sensoren und Monitoring-Skripte

Nova-shell bringt jetzt einen praktischen Sensor-/Monitoring-Pfad fuer Atheria mit:

- [industry_scanner.py](industry_scanner.py)
- [sample_news.json](sample_news.json)
- [watch_the_big_players_test.ns](watch_the_big_players_test.ns)
- [watch_the_big_players.ns](watch_the_big_players.ns)

Wichtig:

- PowerShell-Syntax wie `$env:INDUSTRY_SCAN_FILE="..."` funktioniert nur vor dem Start von Nova-shell in einer echten PowerShell.
- Innerhalb der Nova-shell-REPL setzt du Umgebungsvariablen mit Python:

```text
nova> py import os
nova> py os.environ["INDUSTRY_SCAN_FILE"] = r"D:\Nova-shell\sample_news.json"
```

Sensor direkt pruefen:

```text
nova> cd D:\Nova-shell
nova> py import os
nova> py os.environ["INDUSTRY_SCAN_FILE"] = r"D:\Nova-shell\sample_news.json"
nova> atheria sensor load "industry_scanner.py" --name "BigPlayerWatcher"
nova> atheria sensor run "BigPlayerWatcher"
```

Sensor-Organell aus der Gallery erzeugen:

```text
nova> atheria sensor gallery
nova> atheria sensor spawn quantencomputing --template RSS_Base --name quantum_watch
nova> atheria sensor show quantum_watch
nova> atheria guardian status
nova> atheria guardian prune --dry-run
nova> ns.run morning_briefing.ns
```

Schnelle Testvorlage ausfuehren:

```text
nova> ns.run watch_the_big_players_test.ns
```

Die Datei gibt sofort `SCAN RESULT` und `TEST ALARM` aus und ist fuer Sichttests gedacht.

Langlaufvorlage mit steuerbarer Konfiguration:

```text
nova> py os.environ["NOVA_RESONANCE_THRESHOLD"] = "0.45"
nova> py os.environ["NOVA_SCAN_INTERVAL_SECONDS"] = "1"
nova> py os.environ["NOVA_SCAN_ITERATIONS"] = "1"
nova> ns.run watch_the_big_players.ns
```

Die Langlaufdatei nutzt standardmaessig:

- Schwellwert `0.85`
- Intervall `3600` Sekunden
- `100` Iterationen

Der Sensor akzeptiert diese Datenquellen:

- `INDUSTRY_SCAN_FILE` fuer eine lokale JSON-/RSS-/Text-Datei
- `INDUSTRY_FEEDS` fuer RSS-/Atom-Feeds
- `NEWSAPI_KEY` plus optional `INDUSTRY_NEWS_QUERY` fuer NewsAPI

Morning-Briefing als lokale Web-Oberflaeche:

```text
nova> vision start 8765
```

Dann im Browser:

```text
http://127.0.0.1:8765/briefing
```

In der Web-Oberflaeche gibst du das Thema der Trendanalyse ein. Nova-shell fuehrt danach intern `morning_briefing.ns` aus, erzeugt die Report-Dateien und zeigt sie direkt im Browser an. Gleichzeitig stehen Download-Links fuer diese Dateien bereit:

- `rss_resonance_report.txt`
- `rss_resonance_report.html`
- `rss_trend_report.txt`
- `rss_trend_report.html`
- `rss_morning_briefing.txt`
- `rss_morning_briefing.html`

Neu in der Web-UI:

- Checkbox fuer Auto-Spawn direkt beim Start
- Checkbox fuer Auto-Training direkt beim Start
- Guardian-Empfehlungen nach dem Lauf sichtbar im Browser
- Button, um empfohlene Sensoren nachtraeglich direkt aus dem Briefing heraus zu erzeugen
- Trainingsstatus fuer die in Atheria und Memory uebernommenen Reports

Fuer einen Offline-Test kannst du davor in derselben Session eine lokale Eingabedatei setzen:

```text
nova> py os.environ["INDUSTRY_SCAN_FILE"] = r"D:\Nova-shell\sample_news.json"
nova> vision start 8765
```

Wenn du Atheria als aktiven Provider fuer `ai` und `agent` verwenden willst:

```text
nova> ai use atheria atheria-core
nova> ai prompt "Explain Nova-shell in one paragraph"
nova> agent create storyteller "Tell a concise story about {{input}}" --provider atheria --model atheria-core
nova> agent run storyteller "Nova-shell and Atheria"
```

Kontrollierte Evolutionsphase aus einem Trend-Report:

```text
nova> atheria evolve plan --file reports/rss_trend_report.txt
nova> atheria evolve simulate --file reports/rss_trend_report.txt
nova> atheria evolve apply --reason "align to edge-ai and infrastructure trend"
nova> atheria evolve status
```

Ohne aktiven Provider bleibt `ai plan` der lokale Heuristikpfad:

```text
nova> ai plan "calculate csv average"
```

Heuristische Engine-Empfehlung:

```text
nova> synth suggest py 1 + 1
{"engine": "py", "reason": "default python path", "input": "py 1 + 1"}
```

Autotuning ausfuehren:

```text
nova> synth autotune py 1 + 1
```

Einfachen KI-Hinweis generieren:

```text
nova> ai "calculate csv average"
data load file.csv | py sum(float(r['A']) for r in _) / len(_)
```

Einfachen Agenten anlegen und ausfuehren:

```text
nova> agent create analyst "Summarize {{input}}" --provider lmstudio --model local-model
nova> agent run analyst quarterly report
nova> agent list
```

Vector Memory fuer laengerfristigen Projektkontext:

```text
nova> memory namespace pricing
nova> memory project q1
nova> memory embed --id sales-q1 "Q1 revenue grew 18 percent in DACH"
nova> memory status
nova> memory list
nova> memory search "DACH revenue"
```

Schema-basiertes Tool registrieren und aufrufen:

```text
nova> tool register summarize_csv --description "summarize a csv file" --schema '{"type":"object","properties":{"file":{"type":"string"}},"required":["file"]}' --pipeline 'ai prompt --file {{file}} "Summarize this dataset"'
nova> tool.call summarize_csv file=items.csv
```

Wenn ein Tool Python-Literale einsetzen soll, kann das Template `{{py:name}}` nutzen:

```text
nova> tool register greet --description "say hello" --schema '{"type":"object","properties":{"name":{"type":"string"}},"required":["name"]}' --pipeline 'py "Hello " + {{py:name}}'
nova> tool.call greet name=Nova
```

Planner-Agent fuer Pipeline-Generierung:

```text
nova> ai plan "calculate csv average"
nova> ai plan "summarize the latest dataset"
nova> ai plan --run "calculate average price in items.csv"
nova> ai plan --run --retries 2 "calculate average price in items.csv"
```

Multi-Agent-Runtime mit Spawn, Message, Workflow und Graph:

```text
nova> agent create reviewer "Review {{input}}" --provider lmstudio --model local-model
nova> agent spawn analyst_rt --from analyst
nova> agent message analyst_rt "prepare the quarterly report outline"
nova> agent run analyst --file podcastVideoTranscript_publish_safe.md "Gib mir die Einleitung von Sprecher 1"
nova> agent message script_monitor_rt --memory final_transcript "Gib mir die Einleitung von Sprecher 1"
nova> agent workflow --agents analyst,reviewer --input "quarterly report"
nova> agent graph create review_chain --nodes analyst,reviewer
nova> agent graph run review_chain --input "quarterly report"
```

### 16.2 Mycelia: bounded ALife fuer Agentenpopulationen

`mycelia` ist die Schicht fuer reproduzierbare, nachvollziehbare Agentenpopulationen. Sie baut nicht auf freien Selbstmodifikationen auf, sondern auf:

- vorhandenen Agent-Definitionen als Startgenome
- bounded Mutation
- Fitness-Bewertung pro Zyklus
- Selektion mit Spezies-Champions
- auditierbarer Lineage

Zuerst zwei Basis-Agenten definieren:

```text
nova> agent create analyst "Analyze {{input}}" --provider atheria --model atheria-core
nova> agent create reviewer "Review {{input}}" --provider atheria --model atheria-core
```

Dann eine Population anlegen:

```text
nova> mycelia population create colony --goal "review infrastructure trend signals" --seed analyst,reviewer --target-size 4 --mutation-rate 0.18 --selection-pressure 0.55
```

Die Population einmal oder mehrfach ticken:

```text
nova> mycelia population tick colony --input "edge ai trend report" --cycles 2
```

Wenn passende Mesh-Worker laufen, kann derselbe Tick als Swarm ausgefuehrt werden:

```text
nova> mesh start-worker --caps cpu,py,ai
nova> mycelia population tick colony --input "edge ai trend report" --cycles 1 --swarm
```

Fitness, Spezies und Abstammung ansehen:

```text
nova> mycelia fitness colony
nova> mycelia species colony
nova> mycelia lineage colony --limit 10
```

Gezielt neue Nachkommen erzeugen und danach selektieren:

```text
nova> mycelia breed colony --count 2
nova> mycelia select colony --keep 4
nova> mycelia population show colony
```

Wichtig:

- `mycelia` ist bewusst begrenzt und sicherheitsorientiert.
- Es entstehen keine unkontrollierten freien Prompt-Mutationen.
- Populationen speichern ihren Zustand persistent und koennen spaeter wieder geladen werden.
- Nach jedem Tick steht ein kompakter Snapshot in `flow state get mycelia.last_tick`.

Lokalen Mesh-Worker starten und fuer Remote-Ausfuehrung nutzen:

```text
nova> mesh start-worker --caps cpu,py,ai
nova> mesh list
nova> mesh run py py 1 + 1
nova> mesh stop-worker <worker_id>
```

## 17. NovaGraph und C++-Fusion

GPU-Task-Graph planen:

```text
nova> gpu graph plan kernel_a.cl kernel_b.cl --input "1 2 3"
```

GPU-Task-Graph ausfuehren:

```text
nova> gpu graph run kernel_a.cl kernel_b.cl --input "1 2 3"
```

Pipeline optimiert analysieren:

```text
nova> graph aot "printf '1\n2\n' | cpp.expr x+1 | cpp.expr x*2"
```

Optimierte Pipeline direkt ausfuehren:

```text
nova> graph run "printf '1\n2\n' | cpp.expr x+1 | cpp.expr x*2"
```

Ein vorhandenes Graph-Artefakt anzeigen:

```text
nova> graph show <graph_id>
```

Hinweis:

- Fuer `cpp` und `graph run` mit C++-Stages wird `g++` benoetigt.
- Auf Windows hilft `doctor` beim Toolchain-Check.

## 18. Security und Sandbox

Aktuellen Sandbox-Status pruefen:

```text
nova> guard sandbox status
{"sandbox_default": false}
```

Sandbox einschalten:

```text
nova> guard sandbox on
```

Sandbox wieder ausschalten:

```text
nova> guard sandbox off
```

Policy setzen:

```text
nova> guard set minimal
nova> sys echo blocked
```

Explizit mit `secure` ausfuehren:

```text
nova> secure open py 1 + 1
2
```

eBPF-nahe Guard-Kommandos:

```text
nova> guard ebpf-status
nova> guard ebpf-compile strict-ebpf
nova> guard ebpf-enforce strict-ebpf
nova> guard ebpf-release
```

`strict-ebpf` ist als eingebautes Profil verfuegbar. Eigene Policy-Dateien koennen direkt verwendet werden:

```text
nova> guard ebpf-compile guard.json
nova> guard ebpf-enforce guard.json
```

## 19. Was braucht Zusatz-Tooling?

Einige Beispiele funktionieren nur mit optionalen Modulen oder Toolchains:

- `data load ... --arrow`, `zero put-arrow`, `fabric put-arrow`: `pyarrow`
- `cpp`, `graph run` mit C++-Stages: `g++`
- `cpp.sandbox`: `emcc` und `wasmtime`
- `wasm`: `wasmtime`
- `gpu`: `numpy` und `pyopencl`

Pruefe alles gesammelt mit:

```text
nova> doctor
```

## 20. Empfohlener Lernpfad

Wenn du Nova-shell systematisch lernen willst, ist diese Reihenfolge sinnvoll:

1. `py`, `pwd`, `cd`, `help`, `doctor`
2. einfache Pipelines mit `echo`, `printf`, `py`
3. CSV-Daten mit `data load`
4. Watch- und Event-Kommandos
5. NovaScript mit `ns.exec` und `ns.run`
6. Observability mit `observe`, `events`, `lens`, `pulse`
7. Zero-Copy und Fabric
8. `synth`, `graph`, `cpp`
9. `reactive`, `dflow`, `mesh`
10. Guard, Sandbox und sichere Ausfuehrung

## 21. Naechste Schritte

Nach diesem Tutorial sind die besten Anschlusspunkte:

- [README.md](README.md) fuer den Produktueberblick
- [Whitepaper.md](Whitepaper.md) fuer Architektur und Positionierung
- [docs/RELEASE.md](docs/RELEASE.md) fuer Packaging, Installer und Signierung

Wenn du die Beispiele reproduzierbar lernen willst, arbeite am besten in einer interaktiven Nova-shell-Session und fuehre die Kommandos Abschnitt fuer Abschnitt aus.
