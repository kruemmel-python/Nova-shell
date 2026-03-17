# Tutorial: Project Watch Monitor

## Ziel

Dieses Tutorial zeigt, wie der Nova-shell Watch Monitor in einem echten Projektordner eingesetzt wird.
Am Ende hast du einen laufenden Projektwaechter, der:

- Dateiänderungen erkennt
- Zeilen-Diffs aufzeichnet
- HTML- und JSON-Berichte aktualisiert
- Build- und Testkommandos startet
- Aenderungen mit Heuristik, Atheria oder AI bewertet

## Voraussetzungen

- `doctor` laeuft erfolgreich
- `ns.run` funktioniert
- du hast einen Projektordner, den du beobachten willst
- optional `watchdog` fuer Dateisystemevents

Geeigneter Zielordner:

```text
F:\DeCoG-TRI
```

## Beispielartefakt

Dieses Tutorial nutzt die Datei:

```text
nova_project_monitor.ns
```

Sie wird direkt in den Projektordner gelegt und dort ausgefuehrt.

## Schritte

### 1. Projektordner vorbereiten

Wechsle in den Zielordner:

```powershell
cd F:\DeCoG-TRI
```

Pruefe, ob die Monitor-Datei vorhanden ist:

```powershell
dir nova_project_monitor.ns
```

Erwartung:

- die Datei liegt im Projektroot

### 2. Sicheren Erstlauf ausfuehren

Fuer den ersten Lauf ohne Browser und ohne Dauerbetrieb:

```powershell
$env:NOVA_PROJECT_MONITOR_ONESHOT = "1"
$env:NOVA_PROJECT_MONITOR_OPEN = "0"
ns.run nova_project_monitor.ns
Remove-Item Env:NOVA_PROJECT_MONITOR_ONESHOT
Remove-Item Env:NOVA_PROJECT_MONITOR_OPEN
```

Erwartung:

- `.nova_project_monitor/` wird angelegt
- `project_monitor_report.html` wird geschrieben
- `history.json` enthaelt mindestens ein `baseline`-Ereignis

### 3. Ergebnisdateien pruefen

```powershell
dir .\.nova_project_monitor
Get-Content .\.nova_project_monitor\latest_status.json
```

Wichtige Dateien:

- `.nova_project_monitor/project_monitor_report.html`
- `.nova_project_monitor/project_monitor_analysis.json`
- `.nova_project_monitor/history.json`
- `.nova_project_monitor/latest_status.json`

### 4. Live-Monitor starten

Jetzt den echten Beobachtungsmodus starten:

```powershell
$env:NOVA_PROJECT_MONITOR_WATCH_MODE = "auto"
ns.run nova_project_monitor.ns
```

Erwartung:

- der Prozess bleibt aktiv
- bei installierter Eventbibliothek wird `watchdog` benutzt
- sonst faellt der Monitor auf Polling zurueck

### 5. Eine echte Codeaenderung erzeugen

Oeffne eine Datei im Projekt und aendere einige Zeilen.
Alternativ direkt per PowerShell:

```powershell
Add-Content .\README.md "`nmonitor test line"
```

Erwartung:

- der laufende Monitor erkennt die Änderung
- der Report wird aktualisiert
- das Ereignis erscheint in `history.json`

### 6. HTML-Report ansehen

```powershell
Start-Process .\.nova_project_monitor\project_monitor_report.html
```

Achte im Report auf:

- aktualisierte Aenderungshistorie
- betroffene Datei
- Zeilen-Hunks
- Datei- und Ordner-Hotspots
- Detailseiten-Links fuer geaenderte Dateien

### 7. Detailseite einer Datei pruefen

Wenn im Report eine `Detailseite` verlinkt ist, oeffne sie.
Dort solltest du sehen:

- Vorher-/Nachher-Ansicht
- Unified Diff
- Event-Kontext
- Review-Bezug

## Build und Tests einschalten

Wenn das Projekt `package.json` oder Python-Tests enthaelt, kann der Monitor automatisiert reagieren.

### 8. Automation aktivieren

```powershell
$env:NOVA_PROJECT_MONITOR_AUTOMATION = "auto"
ns.run nova_project_monitor.ns
```

Bei jedem relevanten Change-Event versucht der Monitor dann z. B.:

- `npm run build`
- `npm run test`
- `python -m unittest discover -s tests -p "test_*.py"`

### 9. Automationsblock im Report lesen

Im Report erscheint ein eigener Bereich `Build und Tests`.
Dort sieht man:

- welche Kommandos erkannt wurden
- ob sie erfolgreich waren
- Exit-Code
- `stdout`
- `stderr`

## AI-Review aktivieren

### 10. Atheria priorisiert verwenden

```powershell
$env:NOVA_PROJECT_MONITOR_AI_MODE = "auto"
ns.run nova_project_monitor.ns
```

`auto` bedeutet:

1. zuerst Atheria
2. dann OpenAI-kompatible Provider
3. dann Ollama

### 11. OpenAI explizit erzwingen

```powershell
$env:NOVA_PROJECT_MONITOR_AI_MODE = "openai"
$env:OPENAI_API_KEY = "..."
$env:NOVA_PROJECT_MONITOR_AI_MODEL = "gpt-4o-mini"
ns.run nova_project_monitor.ns
```

### 12. Ollama explizit erzwingen

```powershell
$env:NOVA_PROJECT_MONITOR_AI_MODE = "ollama"
$env:OLLAMA_MODEL = "llama3.2"
ns.run nova_project_monitor.ns
```

## Was dieses Tutorial lehrt

- wie ein `.ns`-Programm als Projektwerkzeug eingesetzt wird
- wie Nova-shell ueber laengere Zeit im Projektordner laeuft
- wie Dateiänderungen zu HTML-, JSON- und Detailreports werden
- wie Build/Test-Automation in den Beobachtungspfad integriert wird
- wie Atheria und AI-Review auf reale Codeänderungen angewendet werden

## Typische Fehlerbilder

### Keine Änderungen im Report

Pruefe:

```powershell
$env:NOVA_PROJECT_MONITOR_WATCH_MODE = "poll"
ns.run nova_project_monitor.ns
```

Wenn Polling funktioniert, liegt das Problem meist nur im Eventpfad.

### Keine Build-/Testläufe

Pruefe:

- `NOVA_PROJECT_MONITOR_AUTOMATION`
- ob `package.json` ein `build`- oder `test`-Script hat
- ob Python-Tests unter `tests/test_*.py` liegen

### Keine AI-Bewertung

Pruefe:

- `NOVA_PROJECT_MONITOR_AI_MODE`
- lokale Atheria-Verfuegbarkeit
- API-Key oder lokales Modell

Wenn kein valides AI-Review verfuegbar ist, faellt der Monitor auf die heuristische Bewertung zurueck.

## Verwandte Seiten

- [WatchMonitor](./WatchMonitor.md)
- [WatchMonitorQuickStart](./WatchMonitorQuickStart.md)
- [WatchMonitorReportReference](./WatchMonitorReportReference.md)
- [WatchMonitorAutomationAndAI](./WatchMonitorAutomationAndAI.md)
- [WatchMonitorTroubleshooting](./WatchMonitorTroubleshooting.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)
- [OperationsAndObservability](./OperationsAndObservability.md)
