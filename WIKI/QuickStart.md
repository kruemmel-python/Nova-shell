# Quick Start

## Ziel

Innerhalb weniger Minuten:

- Shell starten
- ersten Befehl ausfuehren
- erstes `.ns`-Programm laufen lassen
- Plattformstatus abrufen

## 1. Shell starten

```bash
python -m nova_shell
```

oder nach Installation:

```bash
nova-shell
```

## 2. Erster Befehl

```text
nova> py 1 + 1
2
```

## 3. Erste Nova-Datei

```text
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

Ausfuehrung:

```text
nova> ns.run hello.ns
```

## 4. Status

```text
nova> ns.status
```

## Nächste Schritte

- [Installation](./Installation.md)
- [NovaCLI](./NovaCLI.md)
- [NovaLanguage](./NovaLanguage.md)
