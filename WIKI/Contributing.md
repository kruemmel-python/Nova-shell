# Contributing

## Zweck

Diese Seite beschreibt den bevorzugten Beitragsfluss fuer Nova-shell.
Sie gilt fuer Code, Tests, Wiki, Release-Helfer und Beispiele.

## Standardablauf

1. Thema eingrenzen
2. passende Wiki- und Referenzseiten lesen
3. Aenderung in einem eigenen Branch umsetzen
4. lokale Tests ausfuehren
5. Dokumentation aktualisieren
6. Commit und Push vorbereiten

## Grundsaetze

- kleine, klar begrenzte Aenderungen
- Tests fuer neues Verhalten
- Architekturgrenzen respektieren
- Dokumentation mitziehen, wenn Bedienung oder Semantik sich aendert

## Typische Beitragstypen

### Code

- neue Commands
- Parser- oder AST-Erweiterungen
- Graph-, Runtime- oder Mesh-Aenderungen

### Dokumentation

- neue Beispielseiten
- tiefere Referenzen fuer Klassen und Methoden
- Ueberarbeitung unklarer Seiten

### Betrieb und Release

- Build-Skripte
- MSI- oder Wheel-Pipeline
- Smoke- und Integrationstests

## Vor dem Push

Mindestens dieser Testlauf sollte erfolgreich sein:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

Wenn die Aenderung vor allem die Wiki betrifft, ist zusaetzlich sinnvoll:

```powershell
wiki build
```

## Verwandte Seiten

- [Community](./Community.md)
- [DevelopmentGuide](./DevelopmentGuide.md)
- [Testing](./Testing.md)
- [BuildAndRelease](./BuildAndRelease.md)
