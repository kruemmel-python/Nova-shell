# Operations and Observability

## Zweck

Diese Seite beschreibt die Betriebs- und Diagnosepfade von Nova-shell.
Sie deckt Telemetrie, Statusabfragen, Backups, Replay, Restore und Laufzeitdiagnose ab.

## Kernpunkte

- Traces und Laufzeitereignisse fuer Flows, Services und Agenten
- Alerts und Diagnosepfade fuer Fehler und Regressionen
- Telemetrieexport ueber CLI und API
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
- [RuntimeAndControlPlane](./RuntimeAndControlPlane.md)
- [APIReference](./APIReference.md)
- [Troubleshooting](./Troubleshooting.md)
