# Glossary

## Zweck

Dieses Glossar definiert die zentralen Begriffe der Nova-shell-Plattform.
Es soll unklare oder ueberladene Begriffe vereinheitlichen, damit CLI-, Runtime- und Sprachseiten dieselbe Sprache verwenden.

## Kernbegriffe

| Begriff | Bedeutung |
| --- | --- |
| Agent | modellgestuetzte Laufzeitinstanz, die Modelle, Tools, Memory und Governance kombiniert |
| Dataset | strukturierte Eingabemenge oder Datenquelle in einem deklarativen Flow |
| Flow | deklarativer Ablauf, der in einen Execution Graph kompiliert wird |
| Tool | benannte Operation, lokal oder verteilt aufrufbar |
| Event | Signal fuer Automation und Trigger in der Runtime |
| Service | laufender Dienst in der Plattform, typischerweise mit Route, Probe und Traffic-Regeln |
| Package | installierbares Artefakt fuer deklarative oder laufzeitnahe Nutzung |
| Mesh | verteilte Worker-Schicht fuer Remote-Ausfuehrung |
| Control Plane | Queue-, Schedule-, Replay- und API-Ebene der Plattform |
| Traffic Plane | Routing-, Probe- und Traffic-Shift-Schicht fuer Services |
| Lockfile | reproduzierbare Modul- und Paketaufloesung der Toolchain |
| Atheria | lokales Wissens- und Trainingssystem von Nova-shell |

## Sprachbegriffe

- `agent`: beschreibt Agentenrollen und ihre Ausfuehrungsparameter
- `dataset`: beschreibt Datenquellen oder Datenobjekte
- `flow`: beschreibt ausfuehrbare Graphen
- `event`: beschreibt Trigger und Signale
- `tool`: beschreibt Werkzeuge oder Tool-Bindungen
- `system`: beschreibt System- oder Plattformkontext

## Praktische Nutzung

Wenn eine Seite einen Begriff anders verwendet als hier definiert, sollte sie angepasst oder ergaenzt werden.
Das Glossar ist besonders wichtig fuer Nutzer, die zwischen Shell-Kommandos und deklarativer Sprache wechseln.

## Verwandte Seiten

- [NovaLanguage](./NovaLanguage.md)
- [Architecture](./Architecture.md)
- [SystemOverview](./SystemOverview.md)
