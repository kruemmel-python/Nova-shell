# Nova-shell Dokumentation

Diese Datei ist die vollstaendige Command-Referenz fuer Nova-shell 0.8.1. Sie listet die verfuegbaren Kommandos, ihre Subcommands, eine kurze Erklaerung und jeweils mindestens ein Beispiel.

## Schreibweise und Grundprinzip

- `cmd1 | cmd2`: Das Ergebnis der ersten Stage wird an die zweite Stage weitergereicht.
- `parallel <command>`: Pipeline-Modifier, der dieselbe Stage auf mehrere Eingaben anwendet.
- Relative Pfade beziehen sich auf das aktuelle Nova-shell-Arbeitsverzeichnis, also auf `pwd` / `cd`.
- Unbekannte Kommandos fallen auf die System-Shell zurueck. Fuer explizite Shell-Aufrufe ist `sys` die klarere Variante.

## Schnelluebersicht

- Basis und REPL: `help`, `doctor`, `pwd`, `cd`, `clear`, `cls`, `exit`
- Ausfuehrungs-Engines: `py`, `python`, `cpp`, `cpp.sandbox`, `cpp.expr`, `cpp.expr_chain`, `gpu`, `wasm`, `jit_wasm`
- Daten und Handles: `data`, `data.load`, `zero`, `fabric`
- AI und Agenten: `ai`, `atheria`, `agent`, `memory`, `tool`
- Events und Workflow: `event`, `events`, `flow`, `sync`, `reactive`, `dflow`, `watch`, `observe`, `pulse`, `lens`, `rag`
- Optimierung und Graphen: `opt`, `synth`, `graph`, `studio`
- Runtime und Deployment: `mesh`, `remote`, `vision`, `pack`
- Sicherheit: `guard`, `secure`
- NovaScript: `ns.exec`, `ns.run`, `ns.emit`, `ns.check`

## REPL und Basisbefehle

### `help`

- `help`: Listet alle registrierten Kommandos. Beispiel: `help`

### `doctor`

- `doctor`: Zeigt Runtime-, Modul- und Toolchain-Status in Textform. Beispiel: `doctor`
- `doctor json`: Gibt dieselben Informationen als JSON aus. Beispiel: `doctor json`

### `pwd`

- `pwd`: Zeigt das aktuelle Nova-shell-Arbeitsverzeichnis. Beispiel: `pwd`

### `cd`

- `cd <pfad>`: Wechselt das Arbeitsverzeichnis der Nova-shell-Session. Beispiel: `cd D:\Nova-shell`
- `cd` ohne Argument: Springt ins Home-Verzeichnis. Beispiel: `cd`

### `clear` und `cls`

- `clear`: Leert die Konsole. Beispiel: `clear`
- `cls`: Windows-Alias fuer `clear`. Beispiel: `cls`

### `exit`

- `exit`: Beendet die interaktive REPL. Beispiel: `exit`

## Python und allgemeine Ausfuehrung

### `py`

- `py <python_code>`: Fuehrt Python-Code in der persistenten Nova-shell-Python-Session aus. Beispiel: `py 1 + 2`
- `py` kann auch mehrzeilige Bloecke in der REPL annehmen. Beispiel:

```text
py with open("items.csv","w",encoding="utf-8") as f:
    f.write("id,name\n1,Brot\n")
```

### `python`

- `python <python_code>`: Alias fuer `py`. Beispiel: `python _.strip().upper()`

### `sys`

- `sys <kommando>`: Fuehrt ein Shell-/Systemkommando explizit im aktuellen Nova-shell-CWD aus. Beispiel: `sys dir`

## C++, GPU, WASM und JIT

### `cpp`

- `cpp <cpp_code>`: Kompiliert und fuehrt nativen C++20-Code mit `g++` aus. Beispiel:

```text
cpp '#include <iostream>\nint main(){ std::cout << "hello cpp\\n"; }'
```

### `cpp.sandbox`

- `cpp.sandbox <cpp_code>`: Kompiliert C++ nach WASM und fuehrt es in der Sandbox aus. Beispiel:

```text
cpp.sandbox 'int main(){ return 0; }'
```

### `cpp.expr`

- `cpp.expr <ausdruck mit x>`: Wandelt eine Zahlen-Pipeline in einen kleinen C++-Kernel um. Beispiel: `printf '1\n2\n' | cpp.expr x+1`

### `cpp.expr_chain`

- `cpp.expr_chain <expr1 ; expr2 ; ...>`: Fuehrt mehrere mathematische Schritte als einen fusionierten C++-Kernel aus. Beispiel: `printf '1\n2\n' | cpp.expr_chain "x+1 ; x*2"`

### `gpu`

- `gpu <kernel_file>`: Fuehrt ein einzelnes OpenCL-Kernel-File aus. Beispiel: `gpu vector_add.cl`
- `gpu graph plan <kernel1> [kernel2 ...] [--input werte]`: Plant einen GPU-Task-Graphen. Beispiel: `gpu graph plan first.cl second.cl --input "1 2 3"`
- `gpu graph run <kernel1> [kernel2 ...] [--input werte]`: Fuehrt einen GPU-Task-Graphen aus. Beispiel: `gpu graph run first.cl second.cl --input "1 2 3"`
- `gpu graph show <graph_id>`: Zeigt einen zuvor geplanten GPU-Task-Graphen. Beispiel: `gpu graph show ab12cd34ef56`

### `wasm`

- `wasm <module.wasm>`: Fuehrt ein vorhandenes WASM-Modul aus. Beispiel: `wasm hello.wasm`

### `jit_wasm`

- `jit_wasm <arithmetischer_ausdruck>`: Kompiliert einen einfachen Ausdruck JIT-nah in den WASM-Pfad. Beispiel: `jit_wasm 1 + 2 * 3`

## Daten, Dateien und Handles

### `data`

- `data load <csv_file>`: Laedt eine CSV-Datei als Objektliste. Beispiel: `data load items.csv`
- `data load <csv_file> --arrow`: Laedt eine CSV-Datei ueber `pyarrow`. Beispiel: `data load items.csv --arrow`

### `data.load`

- `data.load <csv_file>`: Alias fuer `data load`. Beispiel: `data.load items.csv`
- `data.load <csv_file> --arrow`: Alias fuer `data load ... --arrow`. Beispiel: `data.load items.csv --arrow`

### `watch`

- `watch <file>`: Gibt die letzten 10 Zeilen einer Datei aus. Beispiel: `watch app.log`
- `watch <file> --lines N`: Begrenzt die Anzahl gelesener Zeilen. Beispiel: `watch app.log --lines 5`
- `watch <file> --follow-seconds S`: Liefert fuer einige Sekunden einen Dateistream fuer Pipelines. Beispiel: `watch app.log --follow-seconds 5 | py _.upper()`

### `zero`

- `zero put <text>`: Legt Text im NovaZero-Shared-Memory-Pool ab. Beispiel: `zero put hello-zero`
- `zero put-arrow <csv>`: Legt eine CSV als Arrow-IPC-Payload im Shared Memory ab. Beispiel: `zero put-arrow items.csv`
- `zero get <handle>`: Liest einen NovaZero-Handle wieder aus. Beispiel: `zero get wnsm_12345678`
- `zero list`: Listet alle NovaZero-Handles. Beispiel: `zero list`
- `zero release <handle>`: Gibt einen Handle frei. Beispiel: `zero release wnsm_12345678`

### `fabric`

- `fabric put <text>`: Legt Text in der Fabric ab und gibt einen Handle zurueck. Beispiel: `fabric put hello-fabric`
- `fabric get <handle>`: Liest einen Fabric-Handle wieder aus. Beispiel: `fabric get wnsm_abcdef12`
- `fabric put-arrow <csv>`: Registriert eine CSV als Arrow-Payload in der Fabric. Beispiel: `fabric put-arrow items.csv`
- `fabric remote-put <url> <text>`: Schreibt Text auf eine entfernte Fabric. Beispiel: `fabric remote-put http://127.0.0.1:8899 hello`
- `fabric remote-get <url> <handle>`: Liest einen Remote-Fabric-Handle. Beispiel: `fabric remote-get http://127.0.0.1:8899 wnsm_abcdef12`
- `fabric rdma-put <url> <file>`: Uebertraegt eine Datei ueber den RDMA-orientierten Pfad. Beispiel: `fabric rdma-put http://127.0.0.1:8899 items.csv`
- `fabric rdma-get <url> <handle> <out_file>`: Holt einen Remote-Handle in eine lokale Datei. Beispiel: `fabric rdma-get http://127.0.0.1:8899 wnsm_abcdef12 output.bin`

## AI, Atheria, Agenten, Memory und Tools

### `ai`

- `ai providers`: Listet verfuegbare AI-Provider und Konfiguration. Beispiel: `ai providers`
- `ai models [provider]`: Listet Modelle fuer den aktiven oder angegebenen Provider. Beispiel: `ai models lmstudio`
- `ai use <provider> [model]`: Aktiviert einen Provider und optional ein Modell. Beispiel: `ai use lmstudio local-model`
- `ai config`: Zeigt die aktuelle AI-Konfiguration. Beispiel: `ai config`
- `ai env reload [file]`: Laedt `.env`-Dateien neu ein. Beispiel: `ai env reload .env.local`
- `ai prompt <prompt>`: Sendet einen Prompt an den aktiven Provider. Beispiel: `ai prompt "Explain Nova-shell briefly"`
- `ai prompt --file <pfad> <prompt>`: Fuegt Dateikontext zum Prompt hinzu. Beispiel: `ai prompt --file items.csv "Summarize this dataset"`
- `ai plan <ziel>`: Erstellt einen Tool- oder Pipeline-Plan fuer ein Ziel. Beispiel: `ai plan "calculate average price in items.csv"`
- `ai plan --run <ziel>`: Plant und fuehrt den Plan direkt aus. Beispiel: `ai plan --run "calculate average price in items.csv"`
- `ai plan --run --retries N <ziel>`: Erlaubt Re-Planning bei Fehlern. Beispiel: `ai plan --run --retries 2 "calculate average price in items.csv"`
- `ai <prompt>`: Kurzform fuer heuristische oder providerbasierte AI-Nutzung. Beispiel: `ai "calculate csv average"`

### `atheria`

- `atheria status`: Zeigt Status, Quelle und Trainingsumfang der lokalen Atheria-Runtime. Beispiel: `atheria status`
- `atheria init`: Initialisiert AtheriaCore und den lokalen Runtime-Zustand. Beispiel: `atheria init`
- `atheria sensor list`: Listet geladene Sensor-Plugins. Beispiel: `atheria sensor list`
- `atheria sensor load <file.py> [--name name] [--mapping json|file]`: Laedt ein Sensor-Plugin dynamisch und haengt optional ein Mapping an. Beispiel: `atheria sensor load ops_sensor.py --name ops_sensor --mapping mapping.json`
- `atheria sensor show <name>`: Zeigt Konfiguration und Metadaten eines Sensor-Plugins. Beispiel: `atheria sensor show ops_sensor`
- `atheria sensor map <name> <mapping.json|yaml|json>`: Aktualisiert das JSON-Key-Mapping eines Sensors. Beispiel: `atheria sensor map ops_sensor mapping.json`
- `atheria sensor run <name> [--input json] [--file payload.json] [--train]`: Fuehrt einen Sensor aus und erzeugt ein standardisiertes Atheria-Event. Beispiel: `atheria sensor run ops_sensor --input '{"system":{"cpu_usage":0.91,"latency":18}}' --train`
- `atheria train qa --question <text> --answer <text> [--category name]`: Trainiert Atheria mit einem Q/A-Paar. Beispiel: `atheria train qa --question "What is Nova-shell?" --answer "A unified runtime." --category product`
- `atheria train json <file>`: Uebernimmt Trainingsdaten aus einer JSON-Datei mit `questions`. Beispiel: `atheria train json model_with_qa.json`
- `atheria train csv <file>`: Uebernimmt Trainingsdaten aus einer CSV-Datei. Beispiel: `atheria train csv faq.csv`
- `atheria train file <file> [--category name]`: Zerlegt eine Textdatei in Trainingssegmente. Beispiel: `atheria train file Whitepaper.md --category whitepaper`
- `atheria train memory <memory_id> [--category name]`: Uebernimmt einen Nova-Memory-Eintrag ins Atheria-Training. Beispiel: `atheria train memory final_transcript --category video`
- `atheria search <query>`: Sucht im Atheria-Trainingsspeicher. Beispiel: `atheria search "Nova-shell runtime"`
- `atheria chat <prompt>`: Chattet direkt mit Atheria. Beispiel: `atheria chat "What is Nova-shell?"`
- `atheria chat --file <pfad> <prompt>`: Chat mit Dateikontext. Beispiel: `atheria chat --file items.csv "Summarize this dataset"`
- `atheria chat --system <text> <prompt>`: Chat mit Systemfokus. Beispiel: `atheria chat --system "Answer as an architect." "How should Nova-shell use Atheria?"`

### `Atheria komplett`

Das ist der empfohlene End-to-End-Ablauf fuer Atheria in einer frischen Session:

1. Verfuegbarkeit pruefen:

```text
atheria status
```

2. Runtime initialisieren:

```text
atheria init
```

3. Einfaches Q/A-Wissen trainieren:

```text
atheria train qa --question "What is Nova-shell?" --answer "Nova-shell is a unified compute runtime." --category product
```

4. Eine Datei als Wissensquelle trainieren:

```text
atheria train file podcastVideoTranscript_publish_safe.md --category video
```

5. Optional Nova-Memory nach Atheria uebernehmen:

```text
memory namespace video_production
memory project nova_shell_explainer
memory embed --id final_transcript --file podcastVideoTranscript_publish_safe.md
atheria train memory final_transcript --category video
```

6. Im trainierten Wissen suchen:

```text
atheria search "Nova-shell runtime"
```

7. Direkt mit Atheria chatten:

```text
atheria chat "What is Nova-shell?"
atheria chat --file items.csv "Summarize this dataset"
atheria chat --system "Answer as a technical architect." "How should Nova-shell use Atheria?"
```

8. Atheria als aktiven Provider fuer `ai` und `agent` verwenden:

```text
ai use atheria atheria-core
ai prompt "Explain Nova-shell in one paragraph"
agent create storyteller "Tell a concise story about {{input}}" --provider atheria --model atheria-core
agent run storyteller "Nova-shell and Atheria"
```

### `agent`

- `agent list`: Listet definierte Agenten. Beispiel: `agent list`
- `agent show <name>`: Zeigt einen Agenten samt Prompt-Template und Provider. Beispiel: `agent show analyst`
- `agent create <name> <prompt_template> [--provider p] [--model m] [--system text]`: Erstellt einen Agenten. Beispiel: `agent create analyst "Summarize {{input}}" --provider lmstudio --model local-model`
- `agent run <name> [input]`: Fuehrt einen Agenten einmalig aus. Beispiel: `agent run analyst quarterly report`
- `agent run <name> --file <pfad> <input>`: Fuehrt einen Agenten mit festem Dateikontext aus. Beispiel: `agent run script_monitor --file podcastVideoTranscript_publish_safe.md "Gib mir die Einleitung von Sprecher 1."`
- `agent run <name> --memory <id> <input>`: Fuehrt einen Agenten mit festem Memory-Kontext aus. Beispiel: `agent run script_monitor --memory final_transcript "Gib mir die Einleitung von Sprecher 1."`
- `agent spawn <instance_name> --from <agent>`: Startet eine laufende Agent-Instanz aus einer Definition. Beispiel: `agent spawn analyst_rt --from analyst`
- `agent spawn <instance_name> --prompt <template> [--provider p] [--model m] [--system text]`: Startet eine Instanz ohne vorherige Agent-Definition. Beispiel: `agent spawn temp_rt --prompt "Review {{input}}" --provider atheria --model atheria-core`
- `agent message <instance_name> <message>`: Sendet einer laufenden Agent-Instanz eine Nachricht. Beispiel: `agent message analyst_rt "prepare the quarterly report outline"`
- `agent message <instance_name> --file <pfad> <message>`: Nachricht an eine Instanz mit Dateikontext. Beispiel: `agent message script_monitor_rt --file podcastVideoTranscript_publish_safe.md "Gib mir die Einleitung von Sprecher 1."`
- `agent message <instance_name> --memory <id> <message>`: Nachricht an eine Instanz mit Memory-Kontext. Beispiel: `agent message script_monitor_rt --memory final_transcript "Gib mir die Einleitung von Sprecher 1."`
- `agent workflow --agents a,b[,c] --input text`: Fuehrt mehrere Agenten nacheinander aus. Beispiel: `agent workflow --agents analyst,reviewer --input "quarterly report"`
- `agent workflow --agents a,b --file <pfad> --input text`: Workflow mit Dateikontext. Beispiel: `agent workflow --agents analyst,reviewer --file Whitepaper.md --input "summarize the architecture"`
- `agent workflow --agents a,b --memory <id> --input text`: Workflow mit Memory-Kontext. Beispiel: `agent workflow --agents analyst,reviewer --memory final_transcript --input "check wording"`
- `agent workflow --swarm --agents a,b[,c] --input text`: Verteilt die Workflow-Schritte als Agent-Swarm ueber Mesh-Worker. Beispiel: `agent workflow --swarm --agents planner,analyst,reviewer --input "quarterly report"`

### `agent graph`

- `agent graph list`: Listet definierte Agent-Graphen. Beispiel: `agent graph list`
- `agent graph show <name>`: Zeigt einen Agent-Graphen mit Nodes und Edges. Beispiel: `agent graph show review_chain`
- `agent graph create <name> --nodes a,b[,c] [--edges a>b,b>c]`: Erstellt einen gerichteten Agent-Graphen. Beispiel: `agent graph create review_chain --nodes analyst,reviewer --edges analyst>reviewer`
- `agent graph run <name> --input text`: Fuehrt einen Agent-Graphen aus. Beispiel: `agent graph run review_chain --input "quarterly report"`
- `agent graph run <name> --file <pfad> --input text`: Fuehrt einen Graphen mit Dateikontext aus. Beispiel: `agent graph run review_chain --file Whitepaper.md --input "review this"`
- `agent graph run <name> --memory <id> --input text`: Fuehrt einen Graphen mit Memory-Kontext aus. Beispiel: `agent graph run review_chain --memory final_transcript --input "check consistency"`
- `agent graph run <name> --swarm --input text`: Orchestriert einen Agent-Graphen dynamisch ueber das Mesh. Beispiel: `agent graph run review_chain --swarm --input "Create a release memo"`

### `memory`

- `memory namespace`: Zeigt den aktiven Namespace. Beispiel: `memory namespace`
- `memory namespace <name>`: Setzt den aktiven Namespace. Beispiel: `memory namespace video_production`
- `memory project`: Zeigt das aktive Projekt. Beispiel: `memory project`
- `memory project <name>`: Setzt das aktive Projekt. Beispiel: `memory project nova_shell_explainer`
- `memory status`: Zeigt aktuelle Scope-Informationen. Beispiel: `memory status`
- `memory embed <text>`: Speichert Text im aktuellen Memory-Scope. Beispiel: `memory embed "Q1 revenue grew 18 percent in DACH"`
- `memory embed --id <name> <text>`: Speichert einen Eintrag mit fixer ID. Beispiel: `memory embed --id sales-q1 "Q1 revenue grew 18 percent in DACH"`
- `memory embed --file <pfad>`: Speichert den Dateiinhalt als Memory-Eintrag. Beispiel: `memory embed --id final_transcript --file podcastVideoTranscript_publish_safe.md`
- `memory embed --namespace <n> --project <p> <text>`: Ueberschreibt Namespace und Projekt fuer einen Eintrag. Beispiel: `memory embed --namespace pricing --project q1 "VAT rules for DE"`
- `memory embed --meta <json> <text>`: Speichert zusaetzliche Metadaten. Beispiel: `memory embed --meta '{"source":"meeting"}' "Decision: release core first"`
- `memory search <query>`: Sucht im aktuellen Memory-Scope. Beispiel: `memory search "DACH revenue"`
- `memory search --all <query>`: Sucht scope-uebergreifend. Beispiel: `memory search --all "release policy"`
- `memory search --limit N <query>`: Begrenzt die Trefferzahl. Beispiel: `memory search --limit 3 "video script"`
- `memory list`: Listet Eintraege im aktuellen Scope. Beispiel: `memory list`
- `memory list --all`: Listet Eintraege ueber alle Scopes. Beispiel: `memory list --all`

### `tool`

- `tool list`: Listet registrierte Tools. Beispiel: `tool list`
- `tool show <name>`: Zeigt Beschreibung, Schema und Pipeline eines Tools. Beispiel: `tool show summarize_csv`
- `tool register <name> --description text --schema json --pipeline template`: Registriert ein Tool mit Schema und Pipeline-Template. Beispiel: `tool register greet --description "say hello" --schema '{"type":"object","properties":{"name":{"type":"string"}},"required":["name"]}' --pipeline 'py "Hello " + {{py:name}}'`
- `tool call <name> [json|key=value ...]`: Fuehrt ein Tool mit JSON oder Key/Value-Payload aus. Beispiel: `tool call greet name=Nova`

### `tool.*` Alias-Kommandos

- `tool.register ...`: Alias fuer `tool register ...`. Beispiel: `tool.register greet --description "say hello" --schema '{"type":"object","properties":{"name":{"type":"string"}},"required":["name"]}' --pipeline 'py "Hello " + {{py:name}}'`
- `tool.call ...`: Alias fuer `tool call ...`. Beispiel: `tool.call greet name=Nova`
- `tool.list`: Alias fuer `tool list`. Beispiel: `tool.list`
- `tool.show <name>`: Alias fuer `tool show <name>`. Beispiel: `tool.show greet`

## Events, Flows und Reaktivitaet

### `event`

- `event on <name> <pipeline>`: Registriert eine lokale Event-Pipeline. Beispiel: `event on local_event 'py _.upper()'`
- `event emit <name> <payload>`: Loest ein Event lokal aus. Beispiel: `event emit local_event hello nova`
- `event emit <name> <payload> --broadcast`: Emittiert lokal und broadcastet bei vorhandenen Mesh-Workern. Beispiel: `event emit local_event hello nova --broadcast`
- `event list`: Listet alle Event-Subscriptions. Beispiel: `event list`
- `event history [n]`: Zeigt die letzten lokal emittierten Events. Beispiel: `event history 10`

### `events`

- `events last`: Zeigt das letzte Runtime-Event. Beispiel: `events last`
- `events clear`: Leert den Event-Puffer. Beispiel: `events clear`
- `events stats`: Zeigt aggregierte Event-Statistiken. Beispiel: `events stats`

### `flow`

- `flow state set <key> <value>`: Setzt einen einfachen Flow-State-Wert. Beispiel: `flow state set mode active`
- `flow state get <key>`: Liest einen Flow-State-Wert. Beispiel: `flow state get mode`
- `flow count-last <sekunden> [pattern]`: Zaehlt passende Events in einem Zeitfenster. Beispiel: `flow count-last 10 py*`

### `sync`

- `sync inc <counter> [amount]`: Inkrementiert einen GCounter-CRDT. Beispiel: `sync inc global_counter 2`
- `sync get <counter>`: Liest den Wert eines Counters. Beispiel: `sync get global_counter`
- `sync set <key> <value>`: Setzt einen Key im verteilbaren Map-State. Beispiel: `sync set feature_x enabled`
- `sync get-key <key>`: Liest einen Key aus dem Map-State. Beispiel: `sync get-key feature_x`
- `sync export`: Exportiert Counter- und Map-State als JSON. Beispiel: `sync export`
- `sync merge <json_state>`: Merged einen externen Sync-State. Beispiel: `sync merge '{"counters":{"global_counter":{"nodeA":3}},"map":{"feature_x":"enabled"}}'`

### `reactive`

- `reactive on-file <glob> <pipeline> [--continuous]`: Registriert einen dateibasierten Trigger. Beispiel: `reactive on-file "./incoming/*.txt" 'py _.upper()' --continuous`
- `reactive on-sync <counter> <threshold> <pipeline> [--continuous]`: Reagiert auf Counter-Schwellenwerte. Beispiel: `reactive on-sync global_counter 5 'py "threshold reached"'`
- `reactive list`: Listet aktive Trigger. Beispiel: `reactive list`
- `reactive stop <id>`: Stoppt einen Trigger. Beispiel: `reactive stop trig_abcd1234`
- `reactive clear`: Entfernt alle Trigger. Beispiel: `reactive clear`

### `dflow`

- `dflow subscribe <event> <pipeline>`: Registriert eine verteilte Event-Pipeline. Beispiel: `dflow subscribe test_event 'py _ + "!"'`
- `dflow publish <event> <payload>`: Publiziert ein verteiltes Event lokal. Beispiel: `dflow publish test_event ping`
- `dflow publish <event> <payload> --broadcast`: Publiziert und broadcastet an Mesh-Worker. Beispiel: `dflow publish test_event ping --broadcast`
- `dflow list`: Listet alle dflow-Subscriptions. Beispiel: `dflow list`

### `on`

- `on file "<glob>" --timeout <sekunden> "<pipeline mit _>"`: Wartet auf eine neue Datei und fuehrt danach eine Pipeline aus. Beispiel: `on file "./incoming/*.txt" --timeout 5 "py _.upper()"`

## Beobachtbarkeit und Analyse

### `observe`

- `observe run <pipeline>`: Fuehrt eine Pipeline mit neuer Trace-ID und Statistik aus. Beispiel: `observe run "py 2 + 3"`

### `pulse`

- `pulse status`: Zeigt Vision-, Event- und Trigger-Uebersicht. Beispiel: `pulse status`
- `pulse snapshot`: Zeigt Event-Tail und Bottlenecks. Beispiel: `pulse snapshot`

### `lens`

- `lens list [n]`: Listet die letzten Lens-Snapshots. Beispiel: `lens list 5`
- `lens last`: Zeigt den letzten Snapshot. Beispiel: `lens last`
- `lens show <id>`: Zeigt einen Snapshot im Detail. Beispiel: `lens show 7fd9c0f2b5d1`
- `lens replay <id>`: Replayed den Snapshot-Kontext. Beispiel: `lens replay 7fd9c0f2b5d1`
- `lens fork <snapshot_id> --inject json`: Forkt einen Snapshot, injiziert Werte und erzeugt Diff plus Simulation. Beispiel: `lens fork 7fd9c0f2b5d1 --inject '{"trauma_pressure":0.1}'`
- `lens forks [n]`: Listet Snapshot-Forks. Beispiel: `lens forks 5`
- `lens diff <fork_id>`: Zeigt Diff und Simulationsdaten eines Forks. Beispiel: `lens diff fork_ab12cd34`

### `rag`

- `rag ingest --file <pfad> [--namespace n] [--project p]`: Fuehrt einen Auto-RAG-Ingest fuer ein Dokument aus. Beispiel: `rag ingest --file Whitepaper.md --namespace docs --project research`
- `rag ingest --file <pfad> --no-summary --no-atheria`: Fuehrt nur Chunking und Memory-Embedding aus. Beispiel: `rag ingest --file notes.md --no-summary --no-atheria`
- `rag watch <glob> [--namespace n] [--project p]`: Ueberwacht ein Verzeichnis und ingestiert neue Dokumente automatisch. Beispiel: `rag watch './docs_incoming/*.*' --namespace auto_ingest --project podcast`
- `rag list`: Listet aktive Auto-RAG-Watcher. Beispiel: `rag list`
- `rag stop <id>`: Stoppt einen Auto-RAG-Watcher. Beispiel: `rag stop rag_ab12cd34`

### `studio`

- `studio completions <prefix>`: Zeigt Command-Autocomplete-Vorschlaege. Beispiel: `studio completions ag`
- `studio graph`: Zeigt den zuletzt gebauten Pipeline-Graphen. Beispiel: `studio graph`
- `studio events`: Zeigt den kompletten Event-Puffer. Beispiel: `studio events`

## Optimierung, Planung und Graphen

### `opt`

- `opt suggest <task> [payload]`: Schlaegt eine Engine fuer eine Aufgabe vor. Beispiel: `opt suggest matrix_mul 1+2`
- `opt run <task> [payload]`: Fuehrt die Aufgabe ueber den vorgeschlagenen Delegationspfad aus. Beispiel: `opt run matrix_mul 1+2`

### `synth`

- `synth suggest <code>`: Liefert eine heuristische Engine-Empfehlung. Beispiel: `synth suggest py 1 + 1`
- `synth autotune <code>`: Fuehrt den Autotuner auf einem Codepfad aus. Beispiel: `synth autotune py 1 + 1`

### `graph`

- `graph aot <pipeline>`: Optimiert eine Pipeline vorab und zeigt das Artefakt. Beispiel: `graph aot "printf '1\n2\n' | cpp.expr x+1 | cpp.expr x*2"`
- `graph run <pipeline>`: Optimiert und fuehrt die Pipeline direkt aus. Beispiel: `graph run "printf '1\n2\n' | cpp.expr x+1 | cpp.expr x*2"`
- `graph show <id>`: Zeigt ein vorhandenes Graph-Artefakt. Beispiel: `graph show 1a2b3c4d5e6f`

## Distribution, Mesh und Remote

### `remote`

- `remote <worker_url> <command>`: Fuehrt ein Kommando auf einem Remote-Worker aus. Beispiel: `remote http://127.0.0.1:8899 "py 1 + 1"`

### `mesh`

- `mesh start-worker [--host h] [--port p] [--caps c1,c2,...]`: Startet einen lokalen verwalteten Worker. Beispiel: `mesh start-worker --caps cpu,py,ai`
- `mesh stop-worker <worker_id|url|port>`: Stoppt einen lokalen Worker. Beispiel: `mesh stop-worker 3fa91c2d`
- `mesh add <worker_url> <cap1,cap2,...>`: Registriert einen externen Worker. Beispiel: `mesh add http://127.0.0.1:8899 cpu,py`
- `mesh beat <worker_url> [latency_ms] [handle1,handle2]`: Aktualisiert Health und Datennahe-Metadaten eines Workers. Beispiel: `mesh beat http://127.0.0.1:8899 3.5 handleA,handleB`
- `mesh list`: Listet bekannte Worker. Beispiel: `mesh list`
- `mesh run <capability> <command>`: Fuehrt ein Kommando auf einem passenden Worker aus. Beispiel: `mesh run py py 1 + 1`
- `mesh intelligent-run <capability> <command> [--handle h]`: Waehlt einen Worker intelligent nach Faehigkeit und Datennahe. Beispiel: `mesh intelligent-run gpu py 1 + 1 --handle handleA`

### `vision`

- `vision start [port]`: Startet den Vision-HTTP-Server. Beispiel: `vision start 8877`
- `vision stop`: Stoppt den Vision-Server. Beispiel: `vision stop`
- `vision status`: Zeigt den Vision-Server-Status. Beispiel: `vision status`

### `pack`

- `pack <script.ns> --output <bundle.npx> [--requirements req.txt]`: Packt ein NovaScript-Bundle. Beispiel: `pack sample.ns --output sample.npx`

## Sicherheit

### `guard`

- `guard`: Zeigt die aktuell aktive Policy. Beispiel: `guard`
- `guard list`: Listet eingebaute, geladene und eingebaute eBPF-Profile. Beispiel: `guard list`
- `guard set <policy>`: Aktiviert eine Guard-Policy. Beispiel: `guard set minimal`
- `guard load <policy.yaml|policy.json>`: Laedt eine Policy-Datei. Beispiel: `guard load guard.json`
- `guard sandbox on`: Aktiviert den WASM-First-Sandbox-Default fuer `cpp`. Beispiel: `guard sandbox on`
- `guard sandbox off`: Deaktiviert den WASM-First-Sandbox-Default. Beispiel: `guard sandbox off`
- `guard sandbox status`: Zeigt den Sandbox-Status. Beispiel: `guard sandbox status`
- `guard ebpf-status`: Zeigt eBPF-/Fallback-Status. Beispiel: `guard ebpf-status`
- `guard ebpf-compile <policy|file>`: Bereitet ein eBPF-Profil vor. Beispiel: `guard ebpf-compile strict-ebpf`
- `guard ebpf-enforce <policy|file>`: Erzwingt ein eBPF-Profil. Beispiel: `guard ebpf-enforce strict-ebpf`
- `guard ebpf-release`: Hebt den aktuellen eBPF-Enforcement-Zustand auf. Beispiel: `guard ebpf-release`

### `secure`

- `secure <policy> <command>`: Fuehrt ein Kommando explizit unter einer Policy aus. Beispiel: `secure open py 1 + 1`

## NovaScript

### `ns.exec`

- `ns.exec <inline_script>`: Parst und fuehrt ein Inline-NovaScript aus. Beispiel: `ns.exec x = py 5*5; py $x`

### `ns.run`

- `ns.run <script.ns>`: Fuehrt eine NovaScript-Datei aus. Beispiel: `ns.run sample.ns`

### `ns.emit`

- `ns.emit <variable> <value>`: Loest einen WatchHook in der aktuellen NovaScript-Runtime aus. Beispiel: `ns.emit value 42`

### `ns.check`

- `ns.check <script_file.ns>`: Fuehrt eine statische Strukturpruefung fuer ein NovaScript aus. Beispiel: `ns.check sample.ns`

## Pipeline-Modifier und Nuetzliches im Alltag

### `parallel`

- `parallel <command>`: Pipeline-Modifier fuer parallele Verarbeitung ueber mehrere Eingaben. Beispiel: `printf 'a\nb\n' | parallel py _.upper()`

### Shell-Fallback

- Ein unbekanntes Kommando wird an die System-Shell delegiert. Beispiel: `echo hello`
- Fuer klaren, reproduzierbaren Stil ist `sys <kommando>` meist die bessere Wahl. Beispiel: `sys echo hello`

## Alias-Hinweise

- `python` ist ein Alias fuer `py`.
- `data.load` ist ein Alias fuer `data load`.
- `tool.register`, `tool.call`, `tool.list` und `tool.show` sind Aliase fuer die entsprechenden `tool`-Subcommands.
- `clear` und `cls` verhalten sich identisch.

## Empfohlene Reihenfolge zum Lernen

1. `help`, `doctor`, `pwd`, `cd`
2. `py`, `python`, einfache Pipelines, `watch`, `parallel`
3. `data`, `data.load`, `zero`, `fabric`
4. `event`, `events`, `flow`, `sync`, `reactive`, `dflow`
5. `ai`, `atheria`, `memory`, `tool`, `agent`
6. `graph`, `synth`, `opt`, `gpu graph`
7. `mesh`, `remote`, `vision`
8. `guard`, `secure`, `pack`, `ns.*`

## Weiterfuehrende Dateien

- [README.md](README.md): Produktueberblick und Release-Hinweise
- [Tutorial.md](Tutorial.md): Lernpfad mit Beispielen
- [use_atheria.md](use_atheria.md): Atheria im Detail
- [Atheria_Schnellstart.md](Atheria_Schnellstart.md): schneller Atheria-Einstieg
- [Multi-Agenten-Clusters.md](Multi-Agenten-Clusters.md): lokaler Multi-Agenten-Cluster mit LM Studio
