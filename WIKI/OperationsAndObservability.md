# Operations and Observability

## Zweck

Diese Seite beschreibt Telemetrie, Traces, Alerts, Backup/Restore, Failpoints, Recovery und Lasttests.

## Zentrale Quellen

- [nova/runtime/observability.py](../nova/runtime/observability.py)
- [nova/runtime/telemetry.py](../nova/runtime/telemetry.py)
- [nova/runtime/operations.py](../nova/runtime/operations.py)
- [docs/NOVA_AI_OS_ARCHITECTURE](../docs/NOVA_AI_OS_ARCHITECTURE.md)
- [docs/RELEASE](../docs/RELEASE.md)

## Themen

- Trace- und Event-Korrelation
- Histogramme und Alerts
- Prometheus- und OTLP-Export
- Backup und Restore
- Failpoints und Chaos-Hooks
- Migrationsvalidierung
- Lasttests und Betriebspruefung

## Sinnvolle Anschlussseiten

- [RuntimeAndControlPlane](./RuntimeAndControlPlane.md)
- [SecurityAndTrust](./SecurityAndTrust.md)
- [ToolchainAndTesting](./ToolchainAndTesting.md)
