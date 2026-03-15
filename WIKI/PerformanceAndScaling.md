# Performance and Scaling

## Zweck

Diese Seite beschreibt die wichtigsten Skalierungsachsen von Nova-shell und die Stellen, an denen Performancefragen im System sichtbar werden.

## Skalierungsachsen

- lokale vs. verteilte Ausfuehrung
- mehr Worker im Mesh
- mehr Service-Replicas
- hoehere Queue- und Scheduler-Last
- groessere Agent-, Memory- und Datenmengen

## Wichtige Hebel

- passende Backends waehlen
- Worker-Capabilities sauber trennen
- Service-Replicas und Traffic-Shifts abstimmen
- Observability fuer Bottlenecks nutzen
- Load-Tests regelmaessig ausfuehren

## Praktische Nutzung

### Lokale Last von verteilter Last trennen

Wenn ein Flow lokal langsam ist, sollte zuerst geprueft werden, ob das Problem im Parser-, Tool- oder Agent-Pfad liegt.
Wenn die Last erst im Cluster sichtbar wird, sind Mesh-, Queue- oder Service-Fabric-Pfade wahrscheinlicher.

### Diagnose mit CLI

```powershell
doctor
ns.status
ns.control
```

### Typische Skalierungsentscheidungen

- CPU- oder C++-Last eher ueber dedizierte Worker-Klassen ausfuehren
- GPU-Last nur auf Worker mit passenden Capabilities routen
- Agenten- und Atheria-Pfade getrennt beobachten, wenn Memory oder Embeddings stark wachsen

## Typische Fehlerbilder

### Queue waechst, aber nichts wird schneller

Dann ist oft nicht die Queue selbst das Problem, sondern fehlende Worker-Kapazitaet oder eine zu grobe Routing-Aufteilung.

### Service ist gesund, aber langsam

Dann sollten Traffic-Plane, Probes und Replica-Verteilung geprueft werden.

## Verwandte Seiten

- [NovaMesh](./NovaMesh.md)
- [ServiceFabricAndTrafficPlane](./ServiceFabricAndTrafficPlane.md)
- [OperationsAndObservability](./OperationsAndObservability.md)
