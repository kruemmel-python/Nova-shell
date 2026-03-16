# Watch Monitor

## Zweck

Der Watch Monitor ist ein selbstbootstrappender Nova-shell-Projektwaechter.
Er wird als `.ns`-Datei in einen Projektordner kopiert und dort direkt mit `ns.run` ausgefuehrt.

Sein Zweck ist nicht nur Dateibeobachtung, sondern eine kombinierte Betriebsfunktion:

- Aenderungen im Projektbaum erkennen
- Zeilen-Diffs pro Datei aufzeichnen
- HTML- und JSON-Berichte laufend aktualisieren
- Build- und Testkommandos nach Aenderungen ausfuehren
- Aenderungen durch Heuristik, Atheria oder externe AI bewerten

## Kernobjekte

- `nova_project_monitor.ns`
- `.nova_project_monitor/project_monitor_report.html`
- `.nova_project_monitor/project_monitor_analysis.json`
- `.nova_project_monitor/history.json`
- `.nova_project_monitor/latest_status.json`
- `.nova_project_monitor/files/*.html`

## Methoden und Schnittstellen

Der Monitor wird ueber die normale deklarative Runtime gestartet:

```powershell
cd F:\DeCoG-TRI
ns.run nova_project_monitor.ns
```

Wichtige Steuerung erfolgt ueber Umgebungsvariablen:

- `NOVA_PROJECT_MONITOR_WATCH_MODE`
- `NOVA_PROJECT_MONITOR_INTERVAL`
- `NOVA_PROJECT_MONITOR_DEBOUNCE`
- `NOVA_PROJECT_MONITOR_AUTOMATION`
- `NOVA_PROJECT_MONITOR_AUTOMATION_TIMEOUT`
- `NOVA_PROJECT_MONITOR_AI_MODE`
- `NOVA_PROJECT_MONITOR_AI_MODEL`
- `NOVA_PROJECT_MONITOR_OPEN`
- `NOVA_PROJECT_MONITOR_ONESHOT`

## Betriebsmodell

### 1. Baseline

Beim ersten Lauf scannt der Monitor den Projektbaum rekursiv und schreibt eine Baseline in `snapshot.json`.
Das erste Ereignis in `history.json` ist deshalb typischerweise `baseline`.

### 2. Change Event

Sobald spaeter Dateien hinzukommen, veraendert oder geloescht werden, erzeugt der Monitor ein Ereignis vom Typ `change`.
Dieses Ereignis enthaelt:

- betroffene Dateien
- hinzugefuegte und entfernte Zeilen
- Diff-Hunks
- Review-Ergebnis
- Build-/Test-Ergebnis

### 3. Report-Update

Nach jedem Scan oder Event werden mindestens diese Artefakte neu geschrieben:

- `project_monitor_report.html`
- `project_monitor_analysis.json`
- `latest_status.json`

### 4. Detailseiten

Fuer geaenderte Dateien entstehen eigene HTML-Detailseiten unter `.nova_project_monitor/files/`.
Dort sieht man Vorher/Nachher und einen kompletten Unified Diff.

## CLI

### Standardstart

```powershell
cd F:\DeCoG-TRI
ns.run nova_project_monitor.ns
```

### Einmaliger Scan

```powershell
$env:NOVA_PROJECT_MONITOR_ONESHOT = "1"
$env:NOVA_PROJECT_MONITOR_OPEN = "0"
ns.run nova_project_monitor.ns
Remove-Item Env:NOVA_PROJECT_MONITOR_ONESHOT
Remove-Item Env:NOVA_PROJECT_MONITOR_OPEN
```

### Watchdog erzwingen

```powershell
$env:NOVA_PROJECT_MONITOR_WATCH_MODE = "watchdog"
ns.run nova_project_monitor.ns
```

### Polling erzwingen

```powershell
$env:NOVA_PROJECT_MONITOR_WATCH_MODE = "poll"
ns.run nova_project_monitor.ns
```

## API

Der Monitor ist kein eigener HTTP-Dienst.
Er arbeitet dateibasiert und laeuft innerhalb der Nova-shell-Runtime.

Seine maschinenlesbaren Schnittstellen sind deshalb die erzeugten JSON-Dateien:

- `snapshot.json`
- `history.json`
- `latest_status.json`
- `project_monitor_analysis.json`

## Beispiele

### Projektordner ueberwachen

```powershell
cd F:\DeCoG-TRI
ns.run nova_project_monitor.ns
```

Erwartung:

- `.nova_project_monitor/` wird angelegt
- der HTML-Report oeffnet sich einmalig im Browser, sofern `NOVA_PROJECT_MONITOR_OPEN` nicht auf `0` steht
- jede relevante Codeaenderung aktualisiert den Report

### Report gezielt ohne Browser erzeugen

```powershell
$env:NOVA_PROJECT_MONITOR_ONESHOT = "1"
$env:NOVA_PROJECT_MONITOR_OPEN = "0"
ns.run nova_project_monitor.ns
```

Erwartung:

- keine Browseroeffnung
- aktualisierte HTML- und JSON-Dateien

## Typische Einsatzfaelle

- lokaler Projektwaechter fuer aktive Codebasen
- Aenderungsreport fuer Solo-Entwicklung
- visuelle Churn-Analyse fuer Teamrepos
- schnelle Build-/Test-Rueckmeldung nach Dateiupdates
- Review-Hilfe fuer Ordner mit vielen parallelen Aenderungen

## Verwandte Seiten

- [WatchMonitorQuickStart](./WatchMonitorQuickStart.md)
- [WatchMonitorReportReference](./WatchMonitorReportReference.md)
- [WatchMonitorAutomationAndAI](./WatchMonitorAutomationAndAI.md)
- [TutorialProjectWatchMonitor](./TutorialProjectWatchMonitor.md)
- [NovaCLI](./NovaCLI.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)
- [OperationsAndObservability](./OperationsAndObservability.md)
