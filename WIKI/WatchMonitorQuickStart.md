# WatchMonitor Quick Start

## Zweck

Diese Seite zeigt den kuerzesten belastbaren Weg, um den Nova-shell Watch Monitor in einem Projekt produktiv zu starten.

## Voraussetzungen

- Nova-shell ist installiert und `ns.run` funktioniert
- der Projektordner enthaelt Schreibrechte
- optional `watchdog` fuer echte Dateisystemevents

Wenn `watchdog` nicht vorhanden ist, faellt der Monitor automatisch auf Polling zurueck.

## Schnellstart

### 1. Monitor-Datei in den Projektordner legen

Dateiname:

```text
nova_project_monitor.ns
```

### 2. In den Projektordner wechseln

```powershell
cd F:\DeCoG-TRI
```

### 3. Monitor starten

```powershell
ns.run nova_project_monitor.ns
```

Erwartung:

- `.nova_project_monitor/` wird angelegt
- eine Baseline wird erzeugt
- `project_monitor_report.html` wird geschrieben
- der Monitor bleibt aktiv und beobachtet weitere Aenderungen

## Sicherer Erstlauf

Wenn du den Monitor zuerst ohne Browser und ohne Dauerlauf pruefen willst:

```powershell
$env:NOVA_PROJECT_MONITOR_ONESHOT = "1"
$env:NOVA_PROJECT_MONITOR_OPEN = "0"
ns.run nova_project_monitor.ns
Remove-Item Env:NOVA_PROJECT_MONITOR_ONESHOT
Remove-Item Env:NOVA_PROJECT_MONITOR_OPEN
```

## Sinnvolle erste Einstellungen

### Live-Events bevorzugen

```powershell
$env:NOVA_PROJECT_MONITOR_WATCH_MODE = "auto"
```

### Build- und Testchecks aktivieren

```powershell
$env:NOVA_PROJECT_MONITOR_AUTOMATION = "auto"
```

### Atheria priorisieren

```powershell
$env:NOVA_PROJECT_MONITOR_AI_MODE = "auto"
```

`auto` bedeutet:

1. zuerst Atheria
2. danach OpenAI-kompatible Provider
3. danach Ollama

## Minimaler produktiver Start

```powershell
cd F:\DeCoG-TRI
$env:NOVA_PROJECT_MONITOR_WATCH_MODE = "auto"
$env:NOVA_PROJECT_MONITOR_AUTOMATION = "auto"
$env:NOVA_PROJECT_MONITOR_AI_MODE = "auto"
ns.run nova_project_monitor.ns
```

## Wichtige Ausgabedateien

Nach dem ersten Lauf findest du:

- `.nova_project_monitor/project_monitor_report.html`
- `.nova_project_monitor/project_monitor_analysis.json`
- `.nova_project_monitor/history.json`
- `.nova_project_monitor/latest_status.json`

## Typische erste Pruefung

1. Datei im Projekt aendern
2. speichern
3. Report im Browser neu laden

Im Report sollten jetzt sichtbar sein:

- betroffene Datei
- Zeilen-Hunks
- aktualisierte Hotspots
- optional Build-/Testergebnis
- optional Review-Agent-Ergebnis

## Haeufige Startprobleme

### Der Monitor beendet sich sofort

Pruefe:

```powershell
ns.graph nova_project_monitor.ns
```

### Der Browser soll nicht automatisch aufgehen

```powershell
$env:NOVA_PROJECT_MONITOR_OPEN = "0"
```

### Es werden keine Live-Events erkannt

Pruefe den Watch-Modus:

```powershell
$env:NOVA_PROJECT_MONITOR_WATCH_MODE = "poll"
ns.run nova_project_monitor.ns
```

Wenn Polling funktioniert und `watchdog` nicht, fehlt meist die Event-Bibliothek in der konkreten Installation.

## Verwandte Seiten

- [WatchMonitor](./WatchMonitor.md)
- [TutorialProjectWatchMonitor](./TutorialProjectWatchMonitor.md)
- [WatchMonitorReportReference](./WatchMonitorReportReference.md)
- [WatchMonitorAutomationAndAI](./WatchMonitorAutomationAndAI.md)
- [WatchMonitorTroubleshooting](./WatchMonitorTroubleshooting.md)
- [Troubleshooting](./Troubleshooting.md)
