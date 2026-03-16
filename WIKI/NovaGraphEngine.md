# Nova Graph Engine

## Zweck

Die Graph-Engine ist die Schicht, die deklarative Programme in ausfuehrbare Knoten- und Kantenstrukturen ueberfuehrt.

## Kernpunkte

- Graphknoten repraesentieren Agenten, Datasets, Tools, Flows, Events oder Systemoperationen.
- Kanten repraesentieren Datenfluss oder Kontrollfluss.
- Der Graph ist auf deterministische Ausfuehrung und Diagnostik ausgelegt, nicht auf dekorative Visualisierung.
- `ns.graph` ist der wichtigste Einstieg, um diese Schicht sichtbar zu machen.

## Praktische Nutzung

- Pruefe neue `.ns`-Programme zuerst mit `ns.graph`.
- Verwende die Graphsicht, um Reihenfolge- oder Abhaengigkeitsfehler von Laufzeitproblemen zu trennen.

## Testbare Einstiege

### Graph eines Programms anzeigen

```powershell
ns.graph .\examples\market_radar.ns
```

Erwartung:

- Der kompilierte Graph zeigt Flows und beteiligte Knoten.

## Typische Fragen und Fehler

### Graphaufbau scheitert

- Die Datei ist kein gueltiges deklaratives Nova-Programm.
- Eine Deklaration ist syntaktisch oder strukturell unvollstaendig.

## Verwandte Seiten

- [NovaLanguage](./NovaLanguage.md)
- [ParserAndASTReference](./ParserAndASTReference.md)
- [RuntimeMethodReference](./RuntimeMethodReference.md)
- [ComponentModel](./ComponentModel.md)
