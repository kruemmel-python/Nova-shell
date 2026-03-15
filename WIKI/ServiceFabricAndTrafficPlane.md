# Service Fabric and Traffic Plane

## Zweck

Diese Seite beschreibt die Service-, Package- und Routing-Schicht von Nova-shell.
Sie erklaert, wie laufende Dienste, Revisionen, Ingress, Probes und Traffic-Shifts in die Plattform eingebettet sind.

## Kernpunkte

- Service-Definitionen
- Package-Installation
- Revisionen und Rollouts
- Ingress
- Health-Probes
- Traffic-Shifts

## Praktische Nutzung

### Relevante CLI-Pfade

```powershell
ns.deploy
ns.status
ns.control
```

### Typische Einsatzfaelle

- einen Dienst mit neuer Revision ausrollen
- Traffic schrittweise von einer alten auf eine neue Revision verschieben
- Service-Gesundheit ueber Probes beobachten
- Konfiguration, Secret-Nutzung und Routing gemeinsam betrachten

## Wichtige Zusammenhaenge

- Die Service-Schicht baut auf Runtime- und Control-Plane-Zustaenden auf.
- Observability ist fuer sichere Traffic-Shifts unverzichtbar.
- Performancefragen tauchen oft zuerst an Service- oder Probe-Kanten auf.

## Typische Fehlerbilder

### Neue Revision ist registriert, bekommt aber keinen Traffic

Dann muessen Ingress-, Health- oder Traffic-Shift-Regeln geprueft werden.

### Service ist erreichbar, aber instabil

Dann ist oft die Probe-Definition oder die Runtime-Abhaengigkeit unvollstaendig.

## Verwandte Seiten

- [NovaRuntime](./NovaRuntime.md)
- [OperationsAndObservability](./OperationsAndObservability.md)
- [PerformanceAndScaling](./PerformanceAndScaling.md)
- [APIReference](./APIReference.md)
