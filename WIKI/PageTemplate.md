# Wiki Page Template

Diese Seite definiert das bevorzugte Format fuer technische Wiki-Seiten in Nova-shell.
Nicht jede Seite braucht jeden Abschnitt, aber die Reihenfolge soll moeglichst stabil bleiben.

## Standardschema

```text
# Seitentitel

## Zweck
Kurze Einordnung: Was beschreibt die Seite und warum ist sie relevant?

## Kernobjekte
Klassen, Komponenten, Datenstrukturen oder Subsysteme.

## Methoden und Schnittstellen
Wichtige Methoden, Endpunkte, Kommandos oder Integrationspunkte.

## CLI
Falls es direkte CLI-Pfade gibt.

## API
Falls es direkte HTTP- oder Programmierschnittstellen gibt.

## Beispiele
Kurze, echte Anwendungsbeispiele.

## Verwandte Seiten
Nahe Architektur-, Referenz- oder Tutorialseiten.
```

## Hinweise

- Portal-Seiten wie `Home`, `README`, `GermanLanguage` oder `FAQ` duerfen kompakter bleiben.
- Tutorial-Seiten duerfen statt `Kernobjekte` einen Abschnitt `Ziel` und `Schritte` haben.
- Referenzseiten sollen Tabellen fuer Klassen, Methoden und Endpunkte bevorzugen.
- Jede technische Seite sollte mindestens ein konkretes Beispiel enthalten.
