# Runtime And Control Plane

## Zweck

Diese Seite fasst Runtimekern, Queue, Scheduler, API, Replay, State und Plattformzustand zusammen.

## Kernpunkte

- `NovaRuntime` fuehrt deklarative Programme aus und verwaltet den geladenen Zustand.
- `ns.control` exponiert Queue, Schedules, Daemon, API, State, Replication, Workflows, Services und Packages.
- Die Control Plane ist die Betriebsoberflaeche des AI-OS-Pfads.

## Praktische Nutzung

- Verwende `ns.status` fuer den schnellen Runtime-Ueberblick.
- Verwende `ns.control status` fuer Plattform- und Control-Plane-Zustand.
- Verwende Queue-, Schedule- und Daemon-Kommandos fuer wiederholbare Workloads.

## Testbare Einstiege

### Queue und Daemon pruefen

```powershell
ns.run .\control.ns
ns.control queue enqueue queued_job
ns.control queue run
ns.control daemon tick 4
ns.control status
```

Erwartung:

- Ein Queue-Task wird verarbeitet.
- Der Plattformstatus zeigt Event- und Schedule-Zaehler.

## Typische Fragen und Fehler

### `ns.control` liefert Fehler

- Es ist noch keine deklarative Runtime geladen.
- Der aufgerufene Unterpfad ist nur fuer Adminoperationen gedacht.
- Eine benoetigte Datei oder ein Snapshot fehlt.

## Verwandte Seiten

- [NovaRuntime](./NovaRuntime.md)
- [APIReference](./APIReference.md)
- [OperationsAndObservability](./OperationsAndObservability.md)
- [SecurityModel](./SecurityModel.md)
