# System Guard Monitor

## Zweck

Der System Guard Monitor ist ein zweites Watch-Modul neben dem Projektmonitor.
Er richtet sich nicht auf Quellcode-Churn in einem einzelnen Repo, sondern auf
kritische Windows-Pfade, in denen Malware typischerweise Persistenz,
Temp-Ausfuehrung oder privilegierte Manipulation etabliert.

Der Guard ist deshalb kein klassischer Signatur-Scanner, sondern ein gezielter
Host-Integrity-Monitor:

- fokussierte Pfade statt Vollscan ueber ganze Laufwerke
- Datei- und Hash-Aenderungserkennung
- Zeilen-Diffs fuer textbasierte Skripte wie `.bat`, `.cmd`, `.ps1`, `.js`
- Authenticode- und Publisher-Pruefung fuer `.exe`, `.dll`, `.sys`, `.msi`, `.ps1`
- Scheduled-Task- und Registry-Run-Key-Inventar
- optionale Quarantaene fuer neue Hochrisiko-Dateien
- HTML-Report und JSON-Status
- Watchdog-Events oder Polling als Laufzeitmodus

## Standardpfade

Standardmaessig bewertet der Guard diese Windows-Bereiche:

- User Startup
- Machine Startup
- `System32\\drivers`
- `System32\\config`
- `SysWOW64`
- User Temp
- Windows Temp
- Downloads
- Chrome Extensions
- Roaming Profile

Wenn das Arbeitsverzeichnis wie ein Projekt aussieht, kann zusaetzlich eine
`Project Integrity`-Scope aktiv werden.

## Start

Lege `nova_system_guard.ns` in ein Arbeitsverzeichnis und starte:

```powershell
ns.run nova_system_guard.ns
```

Ein sicherer Erstlauf ohne Browser:

```powershell
$env:NOVA_SYSTEM_GUARD_ONESHOT = "1"
$env:NOVA_SYSTEM_GUARD_OPEN = "0"
ns.run nova_system_guard.ns
```

## Eigene Testpfade

Fuer kontrollierte Tests oder Laborumgebungen kannst du die Standardpfade
abschalten und nur gezielte Ordner beobachten:

```powershell
$env:NOVA_SYSTEM_GUARD_INCLUDE_DEFAULTS = "0"
$env:NOVA_SYSTEM_GUARD_INCLUDE_PROJECT = "off"
$env:NOVA_SYSTEM_GUARD_PATHS = "C:/lab/startup;C:/lab/temp"
$env:NOVA_SYSTEM_GUARD_ONESHOT = "1"
$env:NOVA_SYSTEM_GUARD_OPEN = "0"
ns.run nova_system_guard.ns
```

Der Guard erkennt dabei auch benutzerdefinierte Pfade heuristisch:

- `startup` -> Persistenzpfad
- `temp` -> Temp-Ausfuehrung
- `downloads` -> eingehende ausfuehrbare Dateien
- `drivers` -> Kernel-nahe Dateien
- `config` -> Registry-/Hive-nahe Dateien

Scheduled Tasks und Run Keys bleiben standardmaessig auch dann aktiv, wenn die
Dateisystem-Standardpfade abgeschaltet werden. Wenn du nur Dateipfade ohne
Windows-Inventar willst:

```powershell
$env:NOVA_SYSTEM_GUARD_INCLUDE_WINDOWS_INVENTORY = "0"
```

## Watch-Modi

```powershell
$env:NOVA_SYSTEM_GUARD_WATCH_MODE = "auto"
ns.run nova_system_guard.ns
```

Verfuegbare Modi:

- `auto`
- `watchdog`
- `poll`

## Aktive Schutzaktionen

Der Guard kann neue Hochrisiko-Dateien direkt in Quarantaene verschieben:

```powershell
$env:NOVA_SYSTEM_GUARD_ACTION = "high"
ns.run nova_system_guard.ns
```

Modi:

- `off`
- `critical`
- `high`
- `all`

## Ausgabe

Artefakte liegen unter:

- `.nova_system_guard/system_guard_report.html`
- `.nova_system_guard/system_guard_analysis.json`
- `.nova_system_guard/history.json`
- `.nova_system_guard/latest_status.json`
- `.nova_system_guard/files/*.html`
- `.nova_system_guard/quarantine/*`

Parallel dazu kann Nova-shell auch allgemeine Shell-Lineage nach
`.nova_lens/` schreiben. Das ist nicht der Fachreport des Guards, sondern die
separate Snapshot- und Replay-Schicht. Details dazu stehen in
[NovaLens](./NovaLens.md).

## Bewertung

Der Guard vergibt pro Datei einen Risiko-Score und stuft Ereignisse in:

- `low`
- `medium`
- `high`
- `critical`

Einflussfaktoren sind unter anderem:

- Scope-Prioritaet
- Dateiart: `driver`, `registry_hive`, `executable`, `script`
- Persistenzpfade
- Scheduled Tasks und Registry-Run-Keys
- ausfuehrbare Dateien in Temp oder Downloads
- fehlende oder nicht vertrauenswuerdige Signatur
- doppelte Dateiendungen
- auffaellige Dateinamen wie `autorun`, `update`, `driver`, `inject`

## Typischer Einsatz

- neue `.exe` oder `.ps1` in Temp-Ordnern erkennen
- geaenderte `.bat`-Dateien im Startup mit Diff pruefen
- unerklaerte Aenderungen in Treiber- oder Hive-Pfaden sichtbar machen
- Projektordner als zweite Prioritaet gegen Missbrauch oder Seiteneffekte beobachten

## Verwandte Seiten

- [ExamplesAndRecipes](./ExamplesAndRecipes.md)
- [NovaLens](./NovaLens.md)
- [WatchMonitor](./WatchMonitor.md)
- [WatchMonitorQuickStart](./WatchMonitorQuickStart.md)
- [OperationsAndObservability](./OperationsAndObservability.md)
