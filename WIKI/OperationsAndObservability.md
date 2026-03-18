# Operations and Observability

## Zweck

Diese Seite beschreibt die Betriebs- und Diagnosepfade von Nova-shell.
Sie deckt Telemetrie, Statusabfragen, Backups, Replay, Restore und Laufzeitdiagnose ab.

## Kernpunkte

- Traces und Laufzeitereignisse fuer Flows, Services und Agenten
- Alerts und Diagnosepfade fuer Fehler und Regressionen
- Telemetrieexport ueber CLI und API
- Lens-Lineage und Replay fuer klassische Shell-Stages
- Backups, Restore und Snapshot-Validierung
- Failpoints, Lasttests und Recovery-gestuetzte Betriebspruefung

## Wichtige Zugriffe

### CLI

- `doctor`
- `ns.status`
- `ns.control`
- `ns.snapshot`
- `ns.resume`

### API

- Runtime- und Control-Plane-Endpunkte aus [APIReference](./APIReference.md)
- Status-, Queue-, Replay- und Metrics-Endpunkte

## Testbare Einstiege

### Lokalen Runtime-Status pruefen

```powershell
doctor
ns.status
```

### Snapshot schreiben und wieder laden

```powershell
ns.snapshot
ns.resume
```

### HTML-Wiki als Diagnoseschritt bauen

```powershell
wiki build
```

Der letzte Schritt ist kein Betriebsfeature der Runtime selbst, aber ein schneller Integrationscheck fuer Toolchain und lokale Installation.

### Projektordner mit Watch Monitor beobachten

```powershell
cd F:\DeCoG-TRI
$env:NOVA_PROJECT_MONITOR_AUTOMATION = "auto"
$env:NOVA_PROJECT_MONITOR_AI_MODE = "auto"
ns.run nova_project_monitor.ns
```

Das ist der direkteste Betriebsweg, um:

- Datei-Hotspots zu sehen
- Zeilen-Diffs pro Aenderung nachzuverfolgen
- Review-Agent-Ergebnisse sichtbar zu machen
- Build- und Testlaeufe nach Aenderungen zu protokollieren

Die erzeugten Artefakte liegen unter `.nova_project_monitor/`.

### Lens-Snapshots im klassischen Shell-Pfad pruefen

```powershell
py 2 + 2
lens last
lens list 5
```

Das ist der schnellste Weg, um die persistente Shell-Lineage zu sehen. Die
genauen Speicherstrukturen unter `.nova_lens/lineage.db` und `.nova_lens/cas`
sind in [NovaLens](./NovaLens.md) erklaert.

## Typische Betriebsfragen

### Wo sehe ich, ob die Runtime gesund wirkt?

Mit `doctor` fuer Installationsfaehigkeiten und `ns.status` fuer den Plattformzustand.

### Wie sichere ich den Runtime-Zustand?

Ueber Snapshot- und Control-Plane-Pfade. Fuer umfangreichere Release- oder Betriebspfade siehe [BuildAndRelease](./BuildAndRelease.md).

### Was pruefe ich bei einem unklaren Fehler zuerst?

1. `doctor`
2. `ns.status`
3. `ns.control`
4. relevante Logs oder Trace-Daten

## Verwandte Seiten

- [NovaRuntime](./NovaRuntime.md)
- [NovaLens](./NovaLens.md)
- [RuntimeAndControlPlane](./RuntimeAndControlPlane.md)
- [APIReference](./APIReference.md)
- [Troubleshooting](./Troubleshooting.md)
- [WatchMonitor](./WatchMonitor.md)
- [WatchMonitorReportReference](./WatchMonitorReportReference.md)
