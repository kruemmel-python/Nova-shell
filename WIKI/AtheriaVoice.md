# Atheria Voice

## Zweck

`Atheria Voice` ist die Sprachschicht von ALS.
Sie ist nicht als spaeteres Zusatzfeature gedacht, sondern als direkter kognitiver Ausgangskanal.

Der Kernpunkt ist:

- Atheria spricht nicht nur Ergebnisse aus
- Atheria spricht aus ihrer aktuellen Resonanzlage heraus

## Speech Acts

Die kleinste Einheit ist nicht eine Audiodatei, sondern ein `speech_act`.

Ein Speech Act enthaelt:

- `mode`
- `utterance_text`
- `evidence_refs`
- `resonance`
- `prosody`
- `provider`
- `model`
- `spoken`
- `backend`
- `error`

Diese Eintraege werden in `voice.jsonl` persistiert.

## Prosodie aus Resonanz

Die Prosodie wird aus Laufzeitwerten abgeleitet, nicht zufaellig gewaehlt.

Wichtige Eingangssignale:

- `system_temperature`
- `anomaly_score`
- `confidence`
- `trend_acceleration`
- `structural_tension`

Abgeleitete Merkmale:

- `style`
- `urgency`
- `rate`
- `pitch_percent`
- `volume`

Beispiele:

| Zustand | Wirkung |
| --- | --- |
| hohe Anomalie oder hohe Beschleunigung | warnender oder dringlicher Stil |
| hohe Konfidenz bei mittlerer Temperatur | fokussierter Stil |
| niedrige Spannung und geringe Anomalie | analytischer Stil |

## Audio und Text

Voice besteht in ALS immer aus Speech Acts.
Audio ist optional.

Das bedeutet:

- ohne Audio entsteht trotzdem ein vollwertiger Voice-Eintrag
- mit Audio versucht ALS lokal zu sprechen
- auf Windows nutzt die aktuelle Implementierung SAPI ueber PowerShell und `System.Speech`

## CLI

```powershell
atheria als voice status
atheria als voice last
atheria als voice speak "Manuelle Ausgabe"
```

## Konfiguration

### Audio aktivieren

```powershell
atheria als configure --audio on
```

### Windows-Stimme setzen

```powershell
atheria als configure --voice "Microsoft Hedda Desktop"
```

### Ueber Umgebungsvariablen

```powershell
$env:NOVA_ALS_VOICE_AUDIO = "1"
$env:NOVA_ALS_VOICE_NAME = "Microsoft Hedda Desktop"
atheria als start
```

## Testbare Beispiele

### Letzten Speech Act ansehen

```powershell
atheria als voice last
```

### Einen manuellen Speech Act erzeugen

```powershell
atheria als voice speak "Atheria meldet stabile Resonanz."
```

### Dialog mit Voice-Spur erzeugen

```powershell
atheria als ask "Wie hoch ist die aktuelle strukturelle Spannung?"
```

Erwartung:

- Antwort in JSON
- neuer Eintrag in `voice.jsonl`
- neuer Eintrag in `dialog.jsonl`

## Forensische Bedeutung

Voice ist in ALS nicht nur UX.
Speech Acts sind Teil der auditierbaren Erkenntnisspur.

Dadurch kann man spaeter nachvollziehen:

- was Atheria gesagt hat
- auf welcher Resonanzlage das beruhte
- auf welche Evidenzen sich die Aussage stützte

## Typische Fragen

### Was passiert, wenn Audio fehlschlaegt?

Der Speech Act wird trotzdem gespeichert.
`spoken` bleibt dann `false`, und `error` beschreibt das Audio-Problem.

### Ist Voice auf Windows beschraenkt?

Die persistente Voice-Schicht nein.
Die aktuelle lokale Audioausgabe ja.

## Verwandte Seiten

- [AtheriaContinuousEvolutionAndLiveStream](./AtheriaContinuousEvolutionAndLiveStream.md)
- [AtheriaALSForDevelopers](./AtheriaALSForDevelopers.md)
- [TutorialAtheriaALS](./TutorialAtheriaALS.md)
