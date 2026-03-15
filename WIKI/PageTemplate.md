# Wiki Page Template

## Zweck

Diese Seite definiert das bevorzugte Format fuer Wiki-Seiten in Nova-shell.
Sie ist die redaktionelle Vorlage, mit der die Dokumentation konsistent, technisch brauchbar und testbar bleibt.

## Grundprinzipien

- Jede technische Seite braucht einen klaren Zweck.
- Jede Seite soll zeigen, wie etwas benutzt wird, nicht nur was es ist.
- Jede Fachseite soll mindestens ein konkretes Beispiel oder einen testbaren Einstieg enthalten.
- Jede Seite soll sinnvoll auf naechste Seiten verweisen.

## Standardschema fuer technische Fachseiten

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

## Typische Fehler oder Fragen
Die ersten sinnvollen Diagnose- oder Denkpfade.

## Verwandte Seiten
Nahe Architektur-, Referenz- oder Tutorialseiten.
```

## Schema fuer Tutorial-Seiten

```text
# Tutorialtitel

## Ziel

## Voraussetzungen

## Schritte

## Ergebnispruefung

## Typische Fehler

## Verwandte Seiten
```

## Schema fuer Portal- und Navigationsseiten

```text
# Seitentitel

## Zweck

## Startpunkte oder Bereiche

## Empfohlene Lesepfade

## Verwandte Seiten
```

## Schema fuer FAQ- oder Troubleshooting-Seiten

```text
# Seitentitel

## Zweck

## Erster Diagnoseblock

## Fragen oder Fehlerbilder

## Verwandte Seiten
```

## Redaktionsregeln

- keine reine Schlagwortliste ohne Erklaerung
- keine leeren Kommandotabellen ohne Beispiel
- keine Verweise auf externe Projekt-Markdown-Dateien als Ersatz fuer Inhalt
- keine Theorie ohne Bezug zu realen Kommandos, Klassen oder Ablaufen

## Qualitaetscheck fuer neue Seiten

Eine Seite ist erst dann fertig, wenn sie:

1. ihren Zweck klar benennt
2. mindestens einen realistischen Einstieg nennt
3. intern sinnvoll verlinkt ist
4. nicht nur Features aufzaehlt, sondern deren Rolle erklaert
5. fuer Nutzer oder Entwickler eine erkennbare naechste Handlung anbietet

## Verwandte Seiten

- [README](./README.md)
- [DevelopmentGuide](./DevelopmentGuide.md)
- [ReviewsAndReadingPaths](./ReviewsAndReadingPaths.md)
