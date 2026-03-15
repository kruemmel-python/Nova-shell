# Tutorial: LM Studio Integration

## Ziel

Dieses Tutorial zeigt, wie ein lokaler Modellpfad in denselben Workflow-Rahmen eingebettet wird wie andere Provider.
Der Kernpunkt ist: Nova-shell trennt Providerwahl und Ablaufmodell.

## Voraussetzungen

- lokale Installation mit funktionierendem `doctor`
- ein konfigurierter lokaler AI-Pfad oder ein kompatibler Provider
- Grundverstaendnis von Agenten in `.ns`

## Schrittfolge

### 1. Providerstatus pruefen

```powershell
doctor
ai
```

### 2. Agentenkonfiguration verstehen

In Nova-shell wird der lokale Modellpfad nicht als Sonderfall des Gesamtflusses behandelt.
Wichtig sind:

- Agentendefinition
- Providerwahl
- Modellname
- optionale Memory- oder Prompt-Konfiguration

### 3. Deklarativen Ablauf testen

Ein einfacher Weg ist, zuerst ein vorhandenes Agentenbeispiel mit `ns.graph` anzusehen und dann den Provider anzupassen.

```powershell
ns.graph examples\advanced_agent_fabric.ns
```

### 4. Ergebnis und Memory pruefen

Nach der Ausfuehrung sollten Agentenoutput und gegebenenfalls der Memory-Pfad nachvollziehbar sein.

## Ergebnispruefung

Das Tutorial ist erfolgreich, wenn:

- der Agent ueber einen lokalen Provider angesprochen werden kann
- der restliche Flow unveraendert im Nova-Modell bleibt
- Prompt-, Tool- und Memory-Pfade weiterhin nachvollziehbar sind

## Typische Fehlerbilder

- lokaler Provider nicht erreichbar
- Modellname stimmt nicht mit der lokalen Laufzeit ueberein
- der Provider ist verfuegbar, aber der deklarative Agent verweist noch auf einen anderen Pfad

## Verwandte Seiten

- [NovaAgents](./NovaAgents.md)
- [NovaCLI](./NovaCLI.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)
