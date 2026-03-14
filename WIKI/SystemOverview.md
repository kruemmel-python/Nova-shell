# System Overview

## Hauptbestandteile

| Bereich | Rolle |
| --- | --- |
| CLI | interaktive Bedienung |
| Nova Language | deklarative Programme |
| Toolchain | Imports, Lockfiles, Analyse, Tests |
| Graph Engine | AST-zu-DAG-Kompilation |
| Runtime | Flow-Ausfuehrung und Zustand |
| Agents | modellgestuetzte Aufgaben |
| Memory | Wissens- und Suchschicht |
| Mesh | verteilte Worker |
| Control Plane | Queue, Scheduling, API |
| Service Fabric | Services und Packages |
| Traffic Plane | Routing und Health |
| Security | Rollen, Secrets, TLS |
| Operations | Traces, Backup, Load Tests |

## Betriebsmodi

- lokale Entwicklung
- lokale AI- und Agentenausfuehrung
- deklarative Workflow-Ausfuehrung
- verteilte Worker-Ausfuehrung
- Service- und Traffic-Steuerung
