# WatchMonitor Troubleshooting

## Zweck

Diese Seite sammelt die typischen Fehlerbilder des Nova-shell Watch Monitors.
Der Schwerpunkt liegt auf genau den Stoerungen, die im realen Projektbetrieb am haeufigsten auftreten:

- keine Dateievents
- keine Automation
- keine AI-Bewertung
- leerer oder unvollstaendiger Report
- LM Studio oder Ollama sollen statt Atheria genutzt werden

## Erster Diagnoseblock

```powershell
doctor
ns.graph nova_project_monitor.ns
```

Wenn beide Befehle sauber laufen, ist der Monitorpfad grundsaetzlich intakt.

## Keine Dateievents

### Symptom

- der Monitor laeuft
- der Report wird erstellt
- spaetere Dateiänderungen tauchen aber nicht im Report auf

### Pruefung

```powershell
$env:NOVA_PROJECT_MONITOR_WATCH_MODE = "poll"
ns.run nova_project_monitor.ns
```

### Interpretation

- wenn `poll` funktioniert, ist der Monitor selbst gesund und nur der Eventpfad problematisch
- wenn auch `poll` nicht funktioniert, liegt das Problem meist an Pfad, Schreibrechten oder falschem Projektroot

### Typische Ursachen

- `watchdog` fehlt in der installierten Umgebung
- der Monitor wird nicht im Projektroot gestartet
- die geaenderte Datei liegt in einem ausgeschlossenen Pfad

## Keine Automation

### Symptom

- Aenderungen werden erkannt
- im Report erscheint aber kein oder nur ein leerer `Build und Tests`-Block

### Pruefung

```powershell
$env:NOVA_PROJECT_MONITOR_AUTOMATION = "on"
ns.run nova_project_monitor.ns
```

### Danach kontrollieren

- hat `package.json` ein `build`- oder `test`-Script?
- liegen Python-Tests unter `tests/test_*.py`?
- ist der noetige Paketmanager im System vorhanden?

### Typische Ursachen

- `NOVA_PROJECT_MONITOR_AUTOMATION` steht auf `off`
- das Projekt enthaelt keine erkennbaren Build-/Testkommandos
- `npm`, `pnpm`, `yarn` oder Python-Tests sind lokal nicht lauffaehig

## Keine AI-Bewertung

### Symptom

- im Report steht nur heuristische Bewertung
- `provider`, `model` oder `source` zeigen nicht den erwarteten AI-Pfad

### Wichtigstes Grundprinzip

Wenn `NOVA_PROJECT_MONITOR_AI_MODE=auto` gesetzt ist, gilt:

1. zuerst Atheria
2. dann OpenAI-kompatible Provider
3. dann Ollama

Wenn Atheria lokal verfuegbar ist, wird es in `auto` bevorzugt.
Du musst also LM Studio oder Ollama explizit erzwingen, wenn du sie statt Atheria nutzen willst.

## LM Studio statt Atheria nutzen

### Voraussetzung

In LM Studio:

1. ein Modell laden
2. den Local Server starten
3. den OpenAI-kompatiblen Endpoint aktiv lassen

Standardadresse:

```text
http://127.0.0.1:1234/v1
```

### Erzwungene Aktivierung

```powershell
$env:NOVA_PROJECT_MONITOR_AI_MODE = "lmstudio"
$env:LM_STUDIO_BASE_URL = "http://127.0.0.1:1234/v1"
$env:LM_STUDIO_MODEL = "qwen2.5-coder-7b-instruct"
ns.run nova_project_monitor.ns
```

### Wichtig

Du musst Atheria nicht deinstallieren.
`NOVA_PROJECT_MONITOR_AI_MODE = "lmstudio"` uebersteuert Atheria gezielt fuer den Monitor.

### Woran du erkennst, dass LM Studio wirklich genutzt wird

Im Report bei `Review-Agent` oder im Eventblock:

- `Quelle: ai`
- `Provider: lmstudio`
- `Modus: lmstudio`

Wenn dort weiter `atheria` oder `heuristic` steht, ist LM Studio nicht korrekt aktiv.

### Typische Ursachen, wenn LM Studio nicht genutzt wird

- Local Server in LM Studio nicht gestartet
- falscher Port oder falsche Base-URL
- `LM_STUDIO_MODEL` nicht gesetzt
- `NOVA_PROJECT_MONITOR_AI_MODE` steht noch auf `auto`

## Ollama statt Atheria nutzen

### Voraussetzung

Das Modell muss lokal verfuegbar sein.

```powershell
ollama pull llama3.2
```

Dann sicherstellen, dass Ollama laeuft:

```powershell
ollama run llama3.2 "hello"
```

Standardadresse:

```text
http://127.0.0.1:11434
```

### Erzwungene Aktivierung

```powershell
$env:NOVA_PROJECT_MONITOR_AI_MODE = "ollama"
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
$env:OLLAMA_MODEL = "llama3.2"
ns.run nova_project_monitor.ns
```

### Woran du erkennst, dass Ollama wirklich genutzt wird

Im Report:

- `Quelle: ai`
- `Provider: ollama`
- `Modus: ollama`

### Typische Ursachen, wenn Ollama nicht genutzt wird

- Ollama-Dienst laeuft nicht
- Modellname stimmt nicht mit dem lokal installierten Modell ueberein
- `NOVA_PROJECT_MONITOR_AI_MODE` steht noch auf `auto`

## Zurueck auf Atheria

Wenn du wieder den bevorzugten lokalen Standard willst:

```powershell
$env:NOVA_PROJECT_MONITOR_AI_MODE = "auto"
Remove-Item Env:LM_STUDIO_MODEL -ErrorAction SilentlyContinue
Remove-Item Env:OLLAMA_MODEL -ErrorAction SilentlyContinue
ns.run nova_project_monitor.ns
```

## Leerer oder unvollstaendiger Report

### Symptom

- `project_monitor_report.html` existiert
- es fehlen aber Aenderungen, Hotspots oder Diff-Hunks

### Typische Ursachen

- Baseline ist vorhanden, aber es gab seitdem keine relevante Aenderung
- Datei ist binaer oder zu gross fuer Text-Diff
- aenderte Datei lag nur in einem ausgeschlossenen Pfad

### Pruefung

```powershell
Get-Content .\.nova_project_monitor\latest_status.json
Get-Content .\.nova_project_monitor\history.json
```

Wenn `history.json` keine `change`-Events enthaelt, wurde noch keine echte Aenderung aufgezeichnet.

## Report wird nicht im Browser geoeffnet

### Symptom

- Dateien werden erzeugt
- es oeffnet sich aber kein Browser

### Ursache

Meist ist das gewollt und kommt von:

```powershell
$env:NOVA_PROJECT_MONITOR_OPEN = "0"
```

### Wiedereinschalten

```powershell
Remove-Item Env:NOVA_PROJECT_MONITOR_OPEN -ErrorAction SilentlyContinue
ns.run nova_project_monitor.ns
```

## Empfohlene Minimaldiagnose

Wenn du schnell eingrenzen willst:

1. `doctor`
2. `ns.graph nova_project_monitor.ns`
3. `NOVA_PROJECT_MONITOR_ONESHOT=1`
4. `NOVA_PROJECT_MONITOR_WATCH_MODE=poll`
5. `NOVA_PROJECT_MONITOR_AI_MODE=lmstudio` oder `ollama`, wenn Atheria bewusst uebergangen werden soll

## Verwandte Seiten

- [WatchMonitor](./WatchMonitor.md)
- [WatchMonitorQuickStart](./WatchMonitorQuickStart.md)
- [WatchMonitorAutomationAndAI](./WatchMonitorAutomationAndAI.md)
- [WatchMonitorReportReference](./WatchMonitorReportReference.md)
- [TutorialProjectWatchMonitor](./TutorialProjectWatchMonitor.md)
- [Troubleshooting](./Troubleshooting.md)
