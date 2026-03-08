# Atheria Schnellstart

Diese Seite ist fuer den schnellsten Einstieg gedacht: Nova-shell starten, Atheria initialisieren, etwas trainieren und den ersten Chat fuehren.

## Ziel

In wenigen Minuten soll das hier funktionieren:

```text
nova> atheria init
nova> atheria chat "Who are you?"
nova> ai use atheria atheria-core
nova> ai prompt "Explain Nova-shell briefly"
```

## 1. Nova-shell starten

Nach Installation des Enterprise-Builds:

```text
Nova-shell
```

Oder lokal aus dem Projekt:

```text
python -m nova_shell
```

## 2. Pruefen, ob Atheria verfuegbar ist

```text
nova> doctor
nova> atheria status
```

Wichtig:

- `atheria: ok` im `doctor`
- `available: true` in `atheria status`

## 3. Atheria initialisieren

```text
nova> atheria init
```

Wenn alles passt, siehst du ein JSON mit:

- `available: true`
- `core_loaded: true`
- `core_id: ...`

## 4. Ein minimales Wissensbeispiel trainieren

```text
nova> atheria train qa --question "What is Nova-shell?" --answer "Nova-shell is a unified compute runtime." --category product
```

Danach pruefen:

```text
nova> atheria search "Nova-shell runtime"
```

## 5. Ersten Chat mit Atheria fuehren

```text
nova> atheria chat "What is Nova-shell?"
```

Typisch ist eine Antwort mit:

- deinem trainierten Inhalt
- einem kurzen Atheria-Zustand
- Resonanz-/Phaseninformationen

## 6. Atheria als aktiven AI-Provider setzen

Wenn `ai prompt` ueber Atheria laufen soll:

```text
nova> ai use atheria atheria-core
nova> ai prompt "Explain Nova-shell in one paragraph"
```

Ab hier nutzt der normale `ai`-Pfad Atheria.

## 7. Dateien schnell einlernen

Eine Textdatei:

```text
nova> atheria train file Whitepaper.md --category whitepaper
```

Ein freigegebenes Skript:

```text
nova> atheria train file podcastVideoTranscript_publish_safe.md --category script
```

Ein CSV:

```text
nova> atheria train csv faq.csv
```

## 8. Agent direkt auf Atheria setzen

```text
nova> agent create storyteller "Tell a concise story about {{input}}" --provider atheria --model atheria-core
nova> agent run storyteller "Nova-shell and Atheria"
```

## 9. Der schnellste sinnvolle Demo-Flow

Wenn du Atheria jemandem live zeigen willst:

```text
nova> atheria status
nova> atheria init
nova> atheria train qa --question "Who are you?" --answer "I am Atheria inside Nova-shell." --category identity
nova> atheria chat "Who are you?"
nova> ai use atheria atheria-core
nova> ai prompt "Describe yourself briefly"
```

## 10. Typische Fehler

`atheria status` zeigt `available: false`

- Der Ordner `Atheria/` wurde nicht gefunden.
- Im Enterprise-Installer sollte er automatisch enthalten sein.

`atheria init` scheitert

- Fuehre zuerst `doctor` aus.
- Nutze den aktuellen Enterprise-Build.

`ai prompt` antwortet noch ueber einen anderen Provider

- Setze Atheria explizit:

```text
nova> ai use atheria atheria-core
```

## 11. Nächster Schritt

Wenn der Schnellstart funktioniert, geht es hier weiter:

- Ausfuehrlich: [use_atheria.md](use_atheria.md)
- Tutorial: [Tutorial.md](Tutorial.md)
- Multi-Agenten mit LM Studio: [Multi-Agenten-Clusters.md](Multi-Agenten-Clusters.md)
