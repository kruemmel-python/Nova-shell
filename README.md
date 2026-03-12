# Nova-shell

Nova-shell ist eine **Unified Compute & Data Orchestration Runtime** mit polyglotten Engines, DSL, AOT-Pipelines, Lineage, Mesh-Offloading und Security-Enforcement.

Neu in der Runtime-Schicht:

- AI-Provider-Integration fuer `OpenAI`, `Anthropic`, `Gemini`, `Groq`, `OpenRouter`, `Ollama` und `LM Studio`
- lokale `Atheria`-Integration als trainierbare, chatfaehige In-Repo-KI
- `.env`-gestuetzte API-Key- und Modell-Auswahl direkt aus Nova-shell
- lokale `event`-Runtime fuer Event-Driven Workflows
- `agent`-Kommandos fuer wiederverwendbare AI-Agenten
- persistente Vector-Memory-Scopes ueber `memory namespace` und `memory project`
- `agent graph` fuer gerichtete Multi-Agent-Topologien
- `mycelia` als bounded ALife-Layer fuer Populationen, Reproduktion, Selektion und Lineage
- lokale `mesh`-Worker, die echte Worker-Prozesse auf dem Host starten koennen
- `gpu graph` als erster GPU-Task-Graph-Pfad

## Nächste Ebene: 5 professionell umgesetzte Enterprise-Module

### 1) NovaZero — Unified Zero-Copy Memory Bridge
- Neuer globaler Shared-Memory-Pool `NovaZeroPool`.
- Kommandos:
  - `zero put <text>`
  - `zero put-arrow <csv>`
  - `zero get <handle>`
  - `zero list`
  - `zero release <handle>`
- Arrow-Pfade nutzen IPC-Streams in Shared Memory für engine-übergreifenden Austausch ohne JSON-Roundtrips.

### 2) NovaSynth — AI-Native Engine Selector & Autotuner
- Neue Runtime-Komponente `NovaSynth` (heuristisch + Telemetrie-gestützt).
- Kommandos:
  - `synth suggest <code>`
  - `synth autotune <code>`
- Nutzt Mustererkennung + Optimizer-Signale, um Workloads dynamisch auf `py/cpp/gpu/mesh` auszurichten.

### 3) NovaPulse — Real-Time Observability & Visual Debugger Surface
- Vision API erweitert mit Pulse-State-Daten:
  - `GET /pulse/state`
- CLI-Kommandos:
  - `pulse status`
  - `pulse snapshot`
- Liefert Bottleneck-Sicht (Top-Latenzen), Event-Tails und Trigger/Topic-Überblick.

### 4) NovaFlow — Distributed Reactive Workflows
- Neuer verteilter Flow-Layer (`dflow`) zusätzlich zu lokalen `reactive`-Triggern.
- Kommandos:
  - `dflow subscribe <event> <pipeline>`
  - `dflow publish <event> <payload> [--broadcast]`
  - `dflow list`
- Vision-Endpunkt `POST /flow/event` erlaubt Mesh-weite Eventzustellung.

### 5) NovaGuard Sandbox Isolation (WASM-First)
- C++ kann standardmäßig in Sandbox laufen (`WASM-first`) statt nativem Host-Binary.
- Kommandos:
  - `guard sandbox on|off|status`
  - `cpp.sandbox <cpp_code>`
- Erweiterte Guard/eBPF-Flows:
  - `guard ebpf-status`
  - `guard ebpf-compile <policy|file>`
  - `guard ebpf-enforce <policy|file>`
  - `guard ebpf-release`

---

## Weitere Kernfeatures

- Engines: `py/python`, `cpp`, `gpu`, `wasm`, `remote`, `sys`.
- AI Runtime: `ai providers|models|use|config|env reload|prompt|plan` plus `atheria status|init|guardian|sensor|train|search|chat|evolve`
- AI Agents: `agent create|run|show|list|spawn|message|workflow|graph`
- ALife Runtime: `mycelia population|breed|fitness|select|lineage|species|ecology`
- Event Runtime: `event on|emit|list|history`
- GPU Task Graphs: `gpu graph plan|run|show`
- NovaGraph AOT (`graph aot|run|show`) inkl. C++-Expr-Fusion.
- NovaLens CAS-Lineage (`lens list|last|show|replay`).
- Mesh Intelligence (`mesh beat`, `mesh intelligent-run`, `mesh start-worker`, `mesh stop-worker`).
- NovaScript 2.0 Contracts + Reactive Hooks (`watch`, `ns.emit`, `ns.check`).
- Fabric inkl. Remote/RDMA-orientierter Transferpfade.

## Quickstart

```bash
python -m nova_shell
```

oder nach Installation:

```bash
nova-shell
```

Einzelkommando ohne REPL:

```bash
nova-shell --no-plugins -c "py 1 + 1"
```

Runtime-Diagnose:

```bash
nova-shell doctor
nova-shell doctor json
```

AI-Provider aus `.env` oder Umgebung nutzen:

```bash
nova-shell -c "ai providers"
nova-shell -c "ai use lmstudio local-model"
nova-shell -c "ai prompt \"Summarize this dataset\""
```

Mit Dateikontext oder Pipeline:

```bash
nova-shell -c "ai prompt --file items.csv \"Summarize this dataset\""
nova-shell -c "data load items.csv | ai prompt \"Summarize this dataset\""
```

Fuer langsame lokale Modelle kann das Timeout per `LM_STUDIO_TIMEOUT` oder `NOVA_AI_TIMEOUT` erhoeht werden.

Lokale Atheria-KI initialisieren, trainieren und direkt befragen:

```bash
nova-shell -c "atheria status"
nova-shell -c "atheria init"
nova-shell -c "atheria train qa --question \"What is Nova-shell?\" --answer \"Nova-shell is a unified compute runtime.\" --category product"
nova-shell -c "atheria train file podcastVideoTranscript_publish_safe.md --category video"
nova-shell -c "atheria search \"Nova-shell runtime\""
nova-shell -c "atheria chat \"What is Nova-shell?\""
nova-shell -c "atheria sensor gallery"
nova-shell -c "atheria sensor spawn quantencomputing --template RSS_Base --name quantum_watch"
nova-shell -c "atheria guardian status"
nova-shell -c "atheria evolve plan --file reports/rss_trend_report.txt"
nova-shell -c "atheria evolve simulate --file reports/rss_trend_report.txt"
nova-shell -c "atheria evolve apply --reason \"align to infrastructure trend\""
nova-shell -c "ai use atheria atheria-core"
nova-shell -c "ai prompt \"Explain Nova-shell in one paragraph\""
```

Atheria-Sensoren und NovaScript-Monitoring lokal testen:

```powershell
$env:INDUSTRY_SCAN_FILE="D:\Nova-shell\sample_news.json"
$env:NOVA_RESONANCE_THRESHOLD="0.45"
$env:NOVA_SCAN_INTERVAL_SECONDS="1"
$env:NOVA_SCAN_ITERATIONS="1"
nova-shell
```

Dann in der Nova-shell-REPL:

```text
cd D:\Nova-shell
atheria sensor load "industry_scanner.py" --name "BigPlayerWatcher"
atheria sensor run "BigPlayerWatcher"
atheria sensor gallery
atheria sensor spawn quantencomputing --template RSS_Base --name quantum_watch
atheria guardian status
ns.run morning_briefing.ns
ns.run watch_the_big_players_test.ns
ns.run watch_the_big_players.ns
```

Wichtig:

- PowerShell-Syntax wie `$env:INDUSTRY_SCAN_FILE=...` funktioniert nicht innerhalb der Nova-shell-REPL.
- Innerhalb von Nova-shell setzt du Umgebungsvariablen stattdessen mit `py import os` und `py os.environ["NAME"] = "wert"`.
- `watch_the_big_players_test.ns` ist die schnelle Sichtprobe.
- `watch_the_big_players.ns` ist die Langlaufvariante und nutzt standardmaessig `0.85`, `3600` Sekunden und `100` Iterationen.
- `morning_briefing.ns` ist die kompakte Tagesroutine und erzeugt Resonanz-, Trend- und Guardian-Reports in `reports/`.

Lokale Web-Oberflaeche fuer RSS-Trendanalyse und Morning Briefings:

```text
vision start 8765
```

Dann im Browser:

```text
http://127.0.0.1:8765/briefing
```

Die Web-UI kann:

- ein Thema der Trendanalyse entgegennehmen
- daraus die Feed-Kombination fuer `morning_briefing.ns` ableiten
- optional empfohlene Sensoren direkt automatisch erzeugen
- optional die erzeugten TXT-Reports direkt in Atheria und das Vector Memory trainieren
- automatisch diese Dateien erzeugen:
  - `rss_resonance_report.txt`
  - `rss_resonance_report.html`
  - `rss_trend_report.txt`
  - `rss_trend_report.html`
  - `rss_morning_briefing.txt`
  - `rss_morning_briefing.html`
- die Inhalte direkt im Browser anzeigen
- alle erzeugten Reports als Dateien zum Download anbieten
- Guardian-Empfehlungen anzeigen und nach dem Lauf per Button in echte Sensoren umsetzen
- den Trainingsstatus mit trainierten Records und Memory-Eintraegen anzeigen

Fuer einen offline-faehigen Test kannst du vor dem Start von `vision` auch `INDUSTRY_SCAN_FILE` auf `sample_news.json` setzen.

Vector Memory, Tool Schemas, Planner, Agent Graphs und Mesh-Worker:

```bash
nova-shell -c "memory namespace pricing"
nova-shell -c "memory project q1"
nova-shell -c "memory embed --id sales-q1 \"Q1 revenue grew 18 percent in DACH\""
nova-shell -c "memory search \"DACH revenue\""
nova-shell -c "tool register summarize_csv --description \"summarize a csv file\" --schema '{\"type\":\"object\",\"properties\":{\"file\":{\"type\":\"string\"}},\"required\":[\"file\"]}' --pipeline 'ai prompt --file {{file}} \"Summarize this dataset\"'"
nova-shell -c "tool.call summarize_csv file=items.csv"
nova-shell -c "ai plan \"calculate csv average\""
nova-shell -c "ai plan --run \"calculate average price in items.csv\""
nova-shell -c "ai plan --run --retries 2 \"calculate average price in items.csv\""
nova-shell -c "agent graph create review_chain --nodes analyst,reviewer"
nova-shell -c "agent graph run review_chain --input \"quarterly report\""
nova-shell -c "mycelia population create colony --goal \"review incoming platform signals\" --seed analyst,reviewer --target-size 4"
nova-shell -c "mycelia population tick colony --input \"edge ai trend report\" --cycles 2"
nova-shell -c "mycelia fitness colony"
nova-shell -c "mycelia lineage colony --limit 10"
nova-shell -c "agent spawn analyst_rt --from analyst"
nova-shell -c "agent message analyst_rt \"quarterly report\""
nova-shell -c "agent run analyst --file podcastVideoTranscript_publish_safe.md \"Gib mir die Einleitung von Sprecher 1\""
nova-shell -c "agent message script_monitor_rt --memory final_transcript \"Gib mir die Einleitung von Sprecher 1\""
nova-shell -c "agent workflow --agents analyst,reviewer --input \"quarterly report\""
nova-shell -c "mesh start-worker --caps cpu,py,ai"
nova-shell -c "mesh list"
```

Lernpfad mit vielen Programmierbeispielen:

[Tutorial.md](Tutorial.md)

Vollstaendige Command-Referenz:

[Dokumentation.md](Dokumentation.md)

Schnellster Einstieg fuer Endnutzer:

[Atheria_Schnellstart.md](Atheria_Schnellstart.md)

Eigene Anleitung fuer Training, Chat und Agentenbetrieb mit Atheria:

[use_atheria.md](use_atheria.md)

Ausfuehrliche Betriebsanleitung fuer einen lokalen Multi-Agenten-Cluster mit LM Studio:

[Multi-Agenten-Clusters.md](Multi-Agenten-Clusters.md)

Ideen und Produktbilder dazu, was man konkret mit Nova-shell bauen kann:

[Was_waere_wenn.md](Was_waere_wenn.md)

## Packaging & Release

- Paket-Metadaten liegen in `pyproject.toml`.
- CLI-Entry-Point: `nova-shell`.
- Release-Profile:
  - `core`
  - `enterprise`
- Standalone-Builds erfolgen mit Nuitka.
- Der Windows-Enterprise-Installer liefert `Atheria/` plus die benoetigten Laufzeitpakete fuer lokale Atheria-Initialisierung direkt mit.
- Installer-Artefakte:
  - Windows: `MSI` plus optionale `winget`-Manifeste
  - Linux: `AppImage` plus `.deb`
- Supply-Chain-Artefakte:
  - CycloneDX-SBOM pro Build (`*.sbom.cyclonedx.json`)
  - Subject-Checksums für Attestations (`*-subjects.checksums.txt`)
  - GitHub Artifact Attestations für Provenance und SBOM
- Windows-Wrapper:
  - `./scripts/build_windows.ps1` lädt `VsDevCmd` automatisch, damit MSVC-Header wie `excpt.h` im Build verfügbar sind
- Signierung & Release-Notes:
  - Windows Authenticode via `signtool`
  - detached GPG signatures via `scripts/sign_release.py`
  - aggregierte Release-Notes via `scripts/generate_release_notes.py`
- Cross-Platform-Wrapper:
  - Windows: `./scripts/build_windows.ps1`
  - Linux: `./scripts/build_linux.sh`
- Vollständige Release-Dokumentation: `docs/RELEASE.md`

Beispiele:

```powershell
./scripts/build_windows.ps1 -Profile core
./scripts/build_windows.ps1 -Profile enterprise
./scripts/build_windows.ps1 -Profile core -SourceDateEpoch 1700000000
```

```bash
./scripts/build_linux.sh core
./scripts/build_linux.sh enterprise
SOURCE_DATE_EPOCH=1700000000 ./scripts/build_linux.sh core
```

Direkter Installer-Build:

```bash
python scripts/build_release.py --profile core --mode installers
SOURCE_DATE_EPOCH=1700000000 python scripts/build_release.py --profile core --mode all --clean
python scripts/build_release.py --profile core --mode all --base-download-url "https://github.com/<org>/<repo>/releases/download/v0.8.9"
python scripts/generate_release_notes.py --root dist/release --output dist/release/release-notes.md
python scripts/sign_release.py --root dist/release --verify
```

Verifikation:

```bash
gpg --verify dist/release/<...>/<artifact>.sig dist/release/<...>/<artifact>
gh attestation verify dist/release/<...>/<artifact> --repo <org>/<repo>
gh attestation verify dist/release/<...>/<artifact> --repo <org>/<repo> --predicate-type https://cyclonedx.org/bom
```

```powershell
signtool verify /pa dist\release\<...>\nova-shell.msi
```

## Tests

```bash
python -m unittest discover -s tests -v
```
