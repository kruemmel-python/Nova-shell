# WatchMonitor Automation and AI

## Zweck

Diese Seite dokumentiert die Automations- und Reviewpfade des Watch Monitors.
Sie beschreibt, wann Build und Tests gestartet werden, wie AI-Review ausgewaehlt wird und welche Modi erzwingbar sind.

## Kernobjekte

- Automations-Erkennung ueber Projektdateien
- AI-Review mit Prioritaeten und Fallbacks
- Watch-Modi fuer Eventbetrieb oder Polling
- Laufzeitkonfiguration ueber Umgebungsvariablen

## Methoden und Schnittstellen

Wichtige Variablen:

- `NOVA_PROJECT_MONITOR_AUTOMATION`
- `NOVA_PROJECT_MONITOR_AUTOMATION_TIMEOUT`
- `NOVA_PROJECT_MONITOR_AI_MODE`
- `NOVA_PROJECT_MONITOR_AI_MODEL`
- `NOVA_PROJECT_MONITOR_AI_TIMEOUT`
- `NOVA_PROJECT_MONITOR_WATCH_MODE`
- `NOVA_PROJECT_MONITOR_DEBOUNCE`

## Watch-Modi

### `auto`

Bevorzugt echte Dateisystemevents ueber `watchdog`.
Falls `watchdog` nicht verfuegbar ist, faellt der Monitor auf Polling zurueck.

### `watchdog`

Erzwingt den Eventpfad.
Wenn `watchdog` fehlt, wird im Status ein Fallback-Grund festgehalten.

### `poll`

Erzwingt klassisches Polling ueber einen Zeitintervall.

## Automation

### Automatische Erkennung

Der Monitor erkennt zurzeit vor allem:

- `package.json` mit `build`-Script
- `package.json` mit `test`-Script
- Python-Tests unter `tests/test_*.py`

Typische automatisch ausgefuehrte Kommandos:

- `npm run build`
- `npm run test`
- `python -m unittest discover -s tests -p "test_*.py"`

### Automationsmodi

- `auto`: nur bei relevanten Aenderungen
- `on`: immer nach jedem Change-Event
- `off`: keine Build-/Testchecks

### Timeout

```powershell
$env:NOVA_PROJECT_MONITOR_AUTOMATION_TIMEOUT = "900"
```

## AI-Review

### Prioritaet in `auto`

Wenn `NOVA_PROJECT_MONITOR_AI_MODE=auto` gesetzt ist, nutzt der Monitor diese Reihenfolge:

1. `atheria`
2. OpenAI-kompatible Provider
3. `ollama`

### Unterstuetzte Modi

- `auto`
- `atheria`
- `openai`
- `openrouter`
- `groq`
- `lmstudio`
- `ollama`

### Sichtbarkeit im Report

Der Report zeigt fuer jedes Review:

- `source`
- `provider`
- `model`
- `mode`

So ist immer sichtbar, ob die Bewertung aus:

- Heuristik
- Atheria
- OpenAI-kompatibler API
- LM Studio
- Ollama

stammt.

## CLI

### Atheria priorisieren

```powershell
$env:NOVA_PROJECT_MONITOR_AI_MODE = "auto"
ns.run nova_project_monitor.ns
```

### Atheria erzwingen

```powershell
$env:NOVA_PROJECT_MONITOR_AI_MODE = "atheria"
ns.run nova_project_monitor.ns
```

### OpenAI erzwingen

```powershell
$env:NOVA_PROJECT_MONITOR_AI_MODE = "openai"
$env:OPENAI_API_KEY = "..."
$env:NOVA_PROJECT_MONITOR_AI_MODEL = "gpt-4o-mini"
ns.run nova_project_monitor.ns
```

### Ollama erzwingen

```powershell
$env:NOVA_PROJECT_MONITOR_AI_MODE = "ollama"
$env:OLLAMA_MODEL = "llama3.2"
ns.run nova_project_monitor.ns
```

### Build und Tests immer ausfuehren

```powershell
$env:NOVA_PROJECT_MONITOR_AUTOMATION = "on"
ns.run nova_project_monitor.ns
```

### Nur Dateisystemevents nutzen

```powershell
$env:NOVA_PROJECT_MONITOR_WATCH_MODE = "watchdog"
$env:NOVA_PROJECT_MONITOR_DEBOUNCE = "1.0"
ns.run nova_project_monitor.ns
```

## Beispiele

### Lokales Teamprojekt mit Atheria und Auto-Build

```powershell
cd F:\DeCoG-TRI
$env:NOVA_PROJECT_MONITOR_AI_MODE = "auto"
$env:NOVA_PROJECT_MONITOR_AUTOMATION = "auto"
$env:NOVA_PROJECT_MONITOR_WATCH_MODE = "auto"
ns.run nova_project_monitor.ns
```

### API-Review fuer Cloud-Session

```powershell
$env:NOVA_PROJECT_MONITOR_AI_MODE = "openai"
$env:OPENAI_API_KEY = "..."
$env:NOVA_PROJECT_MONITOR_AI_MODEL = "gpt-4o-mini"
$env:NOVA_PROJECT_MONITOR_AUTOMATION = "on"
ns.run nova_project_monitor.ns
```

### Nur Report, kein Browser, keine Automation

```powershell
$env:NOVA_PROJECT_MONITOR_ONESHOT = "1"
$env:NOVA_PROJECT_MONITOR_OPEN = "0"
$env:NOVA_PROJECT_MONITOR_AUTOMATION = "off"
ns.run nova_project_monitor.ns
```

## Typische Fehlerbilder

### Keine AI-Bewertung trotz gesetztem Modus

Pruefe:

- API-Key oder lokales Modell
- ob Atheria lokal verfuegbar ist
- ob der Provider valide JSON-Reviewdaten liefert

Wenn kein valides Review zurueckkommt, faellt der Monitor kontrolliert auf die heuristische Bewertung zurueck.

### Build oder Tests laufen nicht

Pruefe:

- `NOVA_PROJECT_MONITOR_AUTOMATION`
- ob ein `build`- oder `test`-Script in `package.json` existiert
- ob Python-Tests unter `tests/test_*.py` liegen

### Watchdog reagiert nicht

Pruefe:

```powershell
$env:NOVA_PROJECT_MONITOR_WATCH_MODE = "poll"
ns.run nova_project_monitor.ns
```

Wenn Polling funktioniert, ist der Projektmonitor selbst gesund und nur die Eventbibliothek der Installation fehlt oder reagiert nicht.

## Verwandte Seiten

- [WatchMonitor](./WatchMonitor.md)
- [WatchMonitorQuickStart](./WatchMonitorQuickStart.md)
- [WatchMonitorReportReference](./WatchMonitorReportReference.md)
- [TutorialProjectWatchMonitor](./TutorialProjectWatchMonitor.md)
- [NovaAgents](./NovaAgents.md)
- [OperationsAndObservability](./OperationsAndObservability.md)
