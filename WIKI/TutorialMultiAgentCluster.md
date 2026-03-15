# Tutorial: Multi-Agent Cluster

## Ziel

Dieses Tutorial zeigt, wie mehrere Plattformfunktionen zusammenwirken: Agenten, Runtime, Mesh, Queue und Control Plane.
Der Schwerpunkt liegt nicht nur auf Agenten, sondern auf der Orchestrierung in einer clusterartigen Laufzeit.

## Voraussetzungen

- `doctor` laeuft erfolgreich
- du kannst `.ns`-Dateien mit `ns.graph` und `ns.run` aufrufen
- fuer verteilte Ausfuehrung sollten Mesh- oder Worker-Pfade verfuegbar sein

## Beispielprogramme

Geeignete Referenzen im Repository:

- `examples/ai_os_cluster.ns`
- `examples/distributed_pipeline.ns`

## Schritte

### 1. Graph des Cluster-Beispiels ansehen

```powershell
ns.graph examples\ai_os_cluster.ns
```

### 2. Wichtige Rollen im Beispiel verstehen

Im Beispiel sind mehrere Plattformideen sichtbar:

- `system control_plane` fuer den Betriebsmodus
- `tool publish_signal` als explizites Werkzeug
- `agent strategist`
- `dataset signals`
- `flow daily_ops`
- `event scheduler`

### 3. Lauf ausfuehren

```powershell
ns.run examples\ai_os_cluster.ns
```

### 4. Plattformzustand pruefen

```powershell
ns.status
ns.control
```

## Ergebnispruefung

Dieses Tutorial ist erfolgreich, wenn du nicht nur eine Agentenantwort siehst, sondern auch nachvollziehen kannst:

- welche Schritte als Graph modelliert wurden
- wo Tools und Events eingebunden sind
- wie Runtime-Status und Control-Plane-Befehle zur Diagnose genutzt werden

## Typische Fehlerbilder

- Kein passender Worker oder keine passende Capability
- Event- oder Tool-Schritt ist logisch definiert, aber die Laufzeitvoraussetzung fehlt
- Queue oder Control-Plane-Zustand ist nicht wie erwartet

## Verwandte Seiten

- [NovaAgents](./NovaAgents.md)
- [NovaMesh](./NovaMesh.md)
- [RuntimeAndControlPlane](./RuntimeAndControlPlane.md)
- [OperationsAndObservability](./OperationsAndObservability.md)
