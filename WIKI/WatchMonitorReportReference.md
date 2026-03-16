# WatchMonitor Report Reference

## Zweck

Diese Seite beschreibt den inhaltlichen Aufbau des Watch-Monitor-Reports.
Sie ist die Referenz fuer HTML-Ansicht, Detailseiten und JSON-Dateien.

## Kernobjekte

- `project_monitor_report.html`
- `project_monitor_analysis.json`
- `history.json`
- `latest_status.json`
- `files/*.html`

## HTML-Hauptreport

Der Hauptreport ist die operative Oberflaeche des Monitors.
Er wird nach jedem Scan neu geschrieben.

### Kopfbereich

Der Kopfbereich zeigt:

- Projektname
- Reportpfad
- Analysepfad
- aktuelle Laufzeitkennung

### Zusammenfassungskarten

Typische Karten:

- Projektordner
- letzter Scan
- ueberwachte Dateien
- Historienlaenge
- Watch-Modus

### Review-Agent

Die Review-Karte bewertet die letzte relevante Aenderung.
Sie enthaelt:

- `severity`
- `score`
- `headline`
- `summary`
- `findings`
- `recommendations`
- betroffene Pfade
- Quelle, Provider, Modell und Modus

### Build und Tests

Dieser Block zeigt die Ergebnisse der Automationskommandos:

- erkannte Kommandos
- Exit-Code
- Laufzeit
- `stdout`
- `stderr`

### Analyse

Die Analyse kombiniert heuristische Verdichtungen aus der Historie:

- Warnungen
- Einsichten
- Dateitypranking
- Datei-Hotspots
- Ordner-Hotspots

### Aenderungshistorie

Jedes Ereignis zeigt:

- Zusammenfassung
- Zeitstempel
- Event-Typ
- Review-Zusammenfassung
- optionales Automations-Resultat
- neue Dateien
- entfernte Dateien
- geaenderte Dateien mit Hunk-Ansicht

## Detailseiten pro Datei

Fuer jede geaenderte Datei erzeugt der Monitor eine eigene HTML-Seite unter `.nova_project_monitor/files/`.

Eine Detailseite enthaelt:

- Pfad der Datei
- Event-ID
- Zeitpunkt
- Groesse vorher/nachher
- Review-Kontext
- Vorher-Textansicht
- Nachher-Textansicht
- kompletten Unified Diff

## JSON-Dateien

### `latest_status.json`

Schnellster maschinenlesbarer Einstieg fuer Integrationen.

Typische Felder:

- `generated_at`
- `changed`
- `event`
- `review_agent`
- `automation`
- `runtime`
- `tracked_files`
- `report_path`
- `analysis_path`

### `history.json`

Persistierte Ereignisliste.
Hier steht die langfristige Aenderungshistorie des Projekts.

Typische Event-Felder:

- `id`
- `kind`
- `summary`
- `timestamp`
- `created`
- `modified`
- `deleted`
- `stats`
- `review_agent`
- `automation`

### `project_monitor_analysis.json`

Verdichtete Sicht ueber die Historie.

Typische Felder:

- `warnings`
- `insights`
- `hotspots`
- `file_hotspots`
- `directory_hotspots`
- `extension_ranking`
- `recent_change_count`

## Beispiele

### Hauptreport lesen

```powershell
Start-Process .\.nova_project_monitor\project_monitor_report.html
```

### JSON-Status auslesen

```powershell
Get-Content .\.nova_project_monitor\latest_status.json | ConvertFrom-Json
```

### Letzte Event-Zusammenfassung lesen

```powershell
$status = Get-Content .\.nova_project_monitor\latest_status.json | ConvertFrom-Json
$status.status_line
```

### Review-Daten pruefen

```powershell
$status = Get-Content .\.nova_project_monitor\latest_status.json | ConvertFrom-Json
$status.review_agent | Format-List
```

## Interpretation

### Viele Hotspots in einer Datei

Das spricht meist fuer:

- instabile Kernlogik
- Umbau eines Moduls
- fehlende Zerlegung

### Viele geaenderte Zeilen bei wenigen Dateien

Das spricht eher fuer:

- tiefe Refactorings
- API-Umbauten
- groessere Build- oder Konfigurationsaenderungen

### Viele Dateien mit wenig Churn

Das spricht eher fuer:

- Querschnittsaenderungen
- Formatierungslaeufe
- Versions- oder Importanpassungen

## Verwandte Seiten

- [WatchMonitor](./WatchMonitor.md)
- [WatchMonitorQuickStart](./WatchMonitorQuickStart.md)
- [WatchMonitorAutomationAndAI](./WatchMonitorAutomationAndAI.md)
- [OperationsAndObservability](./OperationsAndObservability.md)
