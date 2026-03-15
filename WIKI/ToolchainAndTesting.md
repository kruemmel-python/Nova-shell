# Toolchain and Testing

## Zweck

Diese Seite verbindet Sprachtooling und Testpfade.
Sie beschreibt die Werkzeuge, die fuer `.ns`-Quelltext, Toolchain-Konsistenz und Entwicklerproduktivitaet wichtig sind.

## Kernpunkte

- Imports
- Lockfiles
- Formatter
- Linter
- LSP-Fassade
- `.ns`-Tests
- Runtime- und Shell-Tests

## Praktische Nutzung

### Typischer Arbeitsablauf

1. `.ns`-Quelle schreiben oder aendern
2. Graph oder Ausfuehrung pruefen
3. Tests fuer Sprache und Runtime ausfuehren
4. bei Bedarf HTML-Wiki oder Release-Helfer pruefen

### Relevante Kommandos

```powershell
ns.graph
ns.run
python -m unittest tests.test_nova_language
wiki build
```

## Typische Werkzeuge im Projekt

- Parser- und AST-Pfade fuer Sprachstruktur
- Referenzseiten fuer Klassen und Methoden
- Unittest-basierte Regressionstests
- Wiki als Langform-Dokumentation und Beispielebene

## Verwandte Seiten

- [NovaLanguage](./NovaLanguage.md)
- [Testing](./Testing.md)
- [DevelopmentGuide](./DevelopmentGuide.md)
- [ParserAndASTReference](./ParserAndASTReference.md)
