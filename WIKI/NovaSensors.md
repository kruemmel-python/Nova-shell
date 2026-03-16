# Nova Sensors

## Zweck

Sensoren sind in Nova-shell die Schicht fuer strukturierte Informationsaufnahme. Im aktuellen Projekt sind sie vor allem ueber Atheria-Sensorpfade sichtbar.

## Kernpunkte

- Sensoren liefern strukturierte Eingangsdaten fuer Wissen, Beobachtung und Trainingspfade.
- Die Sensorik ist pluginartig organisiert und kann gezeigt, geladen und ausgefuehrt werden.
- Sensoren sind kein Ersatz fuer allgemeine Shell-Kommandos, sondern ein semantischer Erfassungspfad.

## Praktische Nutzung

- Nutze `atheria sensor gallery` und `atheria sensor list`, um vorhandene Sensoren zu entdecken.
- Nutze Sensoren, wenn du systematische Beobachtung statt einzelner Ad-hoc-Abfragen brauchst.

## Testbare Einstiege

### Atheria-Sensoren erkunden

```powershell
atheria sensor gallery
atheria sensor list
```

Erwartung:

- Die Gallery zeigt verfuegbare Sensortypen.
- Die Liste zeigt bereits registrierte oder installierte Sensorpfade.

## Typische Fragen und Fehler

### Ein Sensor fehlt

- Das Plugin wurde nicht geladen oder existiert lokal nicht.
- Atheria wurde noch nicht korrekt initialisiert.

## Verwandte Seiten

- [AgentsAndKnowledge](./AgentsAndKnowledge.md)
- [NovaMemory](./NovaMemory.md)
- [TutorialTechnologyRadar](./TutorialTechnologyRadar.md)
- [NovaAgents](./NovaAgents.md)
