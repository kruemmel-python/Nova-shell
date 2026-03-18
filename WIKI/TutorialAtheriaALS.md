# Tutorial Atheria ALS

## Ziel

Dieses Tutorial zeigt, wie Atheria ALS als residenter Live-Pfad gestartet, befragt und mit Voice betrieben wird.

## Voraussetzungen

- Nova-shell ist installiert
- `atheria status` funktioniert
- optional: lokales Windows-Audio fuer Voice

## Schritt 1: Status pruefen

```powershell
atheria status
atheria als status
```

Erwartung:

- Atheria ist verfuegbar
- ALS zeigt sein Basisverzeichnis und die aktuelle Konfiguration

## Schritt 2: ALS konfigurieren

```powershell
atheria als configure --topic "AI infrastructure agent runtime" --interval 90 --trigger 0.80 --anomaly-threshold 0.72
```

Optional mit Audio:

```powershell
atheria als configure --audio on --voice "Microsoft Hedda Desktop"
```

## Schritt 3: Einen einzelnen Zyklus fahren

```powershell
atheria als cycle
atheria als stream tail --limit 3
```

Erwartung:

- `events.jsonl` erhaelt neue Eintraege
- `state.json` aktualisiert sich
- `aion_chronik.html` wird erzeugt oder aktualisiert

## Schritt 4: Residenten Loop starten

```powershell
atheria als start
atheria als status
```

Erwartung:

- `running: true`
- `als.pid` ist vorhanden
- der Hintergrundprozess arbeitet weiter

## Schritt 5: Dialog fuehren

```powershell
atheria als ask "Was ist im Informationsfeld gerade dominant?"
atheria als feedback "Achte staerker auf strukturelle Spannung als auf Funding-News."
```

Erwartung:

- `dialog.jsonl` waechst
- `voice.jsonl` waechst
- die Antworten enthalten Speech-Act-Daten

## Schritt 6: Voice pruefen

```powershell
atheria als voice status
atheria als voice last
atheria als voice speak "Manueller Test der Atheria-Stimme."
```

## Schritt 7: Artefakte lesen

Typische Dateien:

```text
~/.nova_shell_memory/atheria_als/events.jsonl
~/.nova_shell_memory/atheria_als/dialog.jsonl
~/.nova_shell_memory/atheria_als/voice.jsonl
~/.nova_shell_memory/atheria_als/aion_chronik.html
```

## Schritt 8: ALS stoppen

```powershell
atheria als stop
atheria als status
```

Erwartung:

- der resident laufende Prozess wird beendet
- der Zustand bleibt erhalten

## Typische Kontrolle

Wenn du sehen willst, ob ALS wirklich gearbeitet hat:

- `atheria als status`
- `atheria als stream tail --limit 5`
- `atheria als voice last`
- `lens list 10`

## Verwandte Seiten

- [AtheriaContinuousEvolutionAndLiveStream](./AtheriaContinuousEvolutionAndLiveStream.md)
- [AtheriaVoice](./AtheriaVoice.md)
- [AtheriaALSForDevelopers](./AtheriaALSForDevelopers.md)
- [NovaCLI](./NovaCLI.md)
