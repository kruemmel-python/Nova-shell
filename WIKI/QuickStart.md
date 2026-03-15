# Quick Start

## Ziel

Innerhalb weniger Minuten sollst du:

- die Shell starten
- die Installation pruefen
- einen ersten lokalen Befehl ausfuehren
- einen Graph inspizieren
- ein erstes `.ns`-Programm laufen lassen
- den Plattformstatus ansehen

## Voraussetzungen

- Python `3.12+` oder eine installierte Nova-shell-Distribution
- Projektroot oder installierter `nova-shell`-Befehl

## 1. Installation pruefen

```powershell
doctor
```

Wenn `doctor` erfolgreich laeuft, sind Shell, Laufzeitfaehigkeiten und optionale Module sichtbar.

## 2. Shell starten

Aus dem Quellbaum:

```powershell
python -m nova_shell
```

Nach Installation:

```powershell
nova-shell
```

## 3. Ersten lokalen Befehl ausfuehren

```text
nova> py 1 + 1
2
```

Damit pruefst du den interaktiven Compute-Pfad.

## 4. Ein erstes `.ns`-Programm anlegen

Datei `hello.ns`:

```ns
agent helper {
  model: local
}

dataset notes {
  items: [{text: "hello nova"}]
}

flow boot {
  helper summarize notes -> result
}
```

## 5. Zuerst den Graph ansehen

```text
nova> ns.graph hello.ns
```

Das ist der schnellste Weg, Syntax und Struktur zu pruefen, bevor du ausfuehrst.

## 6. Danach ausfuehren

```text
nova> ns.run hello.ns
```

## 7. Plattformstatus ansehen

```text
nova> ns.status
```

## 8. Optional die HTML-Wiki bauen

```text
nova> wiki build
```

Damit pruefst du zusaetzlich den Dokumentations- und Toolchain-Pfad.

## Was du danach tun solltest

- [Installation](./Installation.md) fuer saubere Setups und MSI-Pfade
- [NovaCLI](./NovaCLI.md) fuer die gesamte Befehlsoberflaeche
- [NovaLanguage](./NovaLanguage.md) fuer die Sprache selbst
- [ExamplesAndRecipes](./ExamplesAndRecipes.md) fuer mehr konkrete Ablaufe

## Typische Fehler

### `nova-shell` wird nicht gefunden

Dann entweder `python -m nova_shell` nutzen oder die Installation pruefen.

### `ns.run` scheitert, aber `ns.graph` geht

Dann ist die Syntax meist korrekt und das Problem liegt eher in Runtime, Provider, Datenpfad oder Tool-Ausfuehrung.

### `doctor` zeigt fehlende Faehigkeiten

Dann zuerst [Installation](./Installation.md) und [Troubleshooting](./Troubleshooting.md) lesen.

## Verwandte Seiten

- [Installation](./Installation.md)
- [NovaCLI](./NovaCLI.md)
- [NovaLanguage](./NovaLanguage.md)
- [Troubleshooting](./Troubleshooting.md)
