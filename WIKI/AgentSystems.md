# Agent Systems

## Zweck

Diese Seite beschreibt das Agentenmodell in Nova-shell aus konzeptioneller Sicht. Sie ist absichtlich theoretischer als die konkrete Laufzeitdokumentation in `NovaAgents`.

## Kernpunkte

- Ein Agent ist in Nova-shell eine definierte Prompt- und Ausfuehrungseinheit, kein eigenstaendiger Scheduler-Prozess.
- Agenten koennen einmalig laufen, als Instanz gespawnt werden oder als Knoten in einem Agent-Graph ausgefuehrt werden.
- Das System unterstuetzt lineare Workflows, Graph-DAGs und swarm-artige Verteilung auf Mesh-Worker.
- Wichtig ist die Trennung zwischen Agent-Definition, Agent-Instanz und Agent-Graph.

## Praktische Nutzung

- Lege Agent-Definitionen an, wenn du wiederkehrende Rollen wie `analyst` oder `reviewer` brauchst.
- Nutze Agent-Instanzen fuer Sitzungen mit Verlauf und Folgefragen.
- Nutze Agent-Graphen, wenn Abhaengigkeiten zwischen Rollen explizit modelliert werden sollen.
- Nutze Swarm-Modus nur dann, wenn passende Mesh-Worker und Policies bereitstehen.

## Testbare Einstiege

### Ein einfacher Agent-Graph

```powershell
agent create analyst "Analyze {{input}}" --provider lmstudio --model analyst-model
agent create reviewer "Review {{input}}" --provider lmstudio --model reviewer-model
agent graph create review_chain --nodes analyst,reviewer
agent graph run review_chain --input "quarterly report"
```

Erwartung:

- Der Graph enthaelt beide Rollen in einer topologisch gueltigen Reihenfolge.
- Die Ausgabe der ersten Rolle dient als Eingabe der zweiten Rolle.

## Typische Fragen und Fehler

### Graphlauf scheitert sofort

- Mindestens ein referenzierter Agent existiert nicht.
- Der Graph enthaelt einen Zyklus oder ungueltige Kanten.
- Die Eingabe wurde ohne `--input` uebergeben.

## Verwandte Seiten

- [NovaAgents](./NovaAgents.md)
- [AgentsAndKnowledge](./AgentsAndKnowledge.md)
- [NovaMesh](./NovaMesh.md)
- [Research](./Research.md)
