# Nova Planner

## Zweck

Der Planner ist die Schicht hinter `ai plan`. Er versucht, aus einer natuerlichen Aufgabenbeschreibung eine handhabbare Nova-shell-Aktion oder Pipeline abzuleiten.

## Kernpunkte

- Der Planner kann heuristisch oder providerbasiert arbeiten.
- Heuristische Plaene greifen bevorzugt auf registrierte Tools und bekannte Muster zurueck.
- Providerbasierte Plaene koennen JSON- oder Pipeline-Vorschlaege liefern.
- Der Planner ist ein Uebersetzer zwischen Prompt und operativer Ausfuehrung, kein Ersatz fuer `.ns`-Programme.

## Praktische Nutzung

- Nutze `ai plan`, wenn du aus einer Aufgabenbeschreibung einen ersten Shell- oder Toolpfad ableiten willst.
- Nutze `ai plan --run`, wenn du den Vorschlag unmittelbar ausfuehren willst.

## Testbare Einstiege

### Heuristischen Toolplan pruefen

```powershell
tool register csv_average --description "calculate csv average from file" --schema "{\"type\":\"object\",\"properties\":{\"file\":{\"type\":\"string\"}}}" --pipeline "data load {{file}} | py sum(float(r[\"A\"]) for r in _) / len(_)"
ai plan "calculate csv average"
```

Erwartung:

- Der Planner bevorzugt das registrierte Tool.
- Die Rueckgabe ist ein konkreter, ausfuehrbarer Vorschlag.

## Typische Fragen und Fehler

### Ein Plan ist zu allgemein

- Es fehlt ein registriertes Tool oder ein aktiver Provider.
- Die Eingabe beschreibt kein klar zuordenbares Muster.

## Verwandte Seiten

- [NovaCLI](./NovaCLI.md)
- [NovaTools](./NovaTools.md)
- [ProgrammingWithNovaShell](./ProgrammingWithNovaShell.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)
