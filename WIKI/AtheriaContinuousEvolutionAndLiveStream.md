# Atheria Continuous Evolution & Live Stream

## Zweck

`Atheria Continuous Evolution & Live Stream`, kurz `ALS`, ist die resident laufende Betriebsform von Atheria in Nova-shell.
Sie verschiebt Atheria von einem punktuellen `run`- oder Report-Modell zu einem dauerhaften Erkenntnispfad mit:

- kontinuierlicher Feed-Ingestion
- laufender Resonanzbewertung
- automatischer Wissensintegration
- lokaler, replaybarer Kausalspur
- direkter Dialog- und Voice-Schnittstelle

Wichtig ist die Einordnung:
Das aktuelle ALS arbeitet als residenter, wiederkehrender Stream-Loop ueber RSS- und API-Quellen.
Es ist damit kein einmaliger Morning-Briefing-Lauf mehr, aber auch noch kein globaler Push-Bus mit Websocket-Zwang.
Neu dazu kommt ein optionaler `web_search`-Pfad, der Suchergebnisse parallel zu den Feed-Quellen einsammelt und in denselben Resonanzzyklus einspeist.

## Kernobjekte

| Objekt | Rolle |
| --- | --- |
| `AtheriaALSRuntime` | residenter ALS-Kern fuer Stream, Training, Dialog und Persistenz |
| `AtheriaVoiceRuntime` | Speech-Act-Erzeugung, Prosodie-Profil und optionale lokale Audioausgabe |
| `NovaAtheriaRuntime` | Training, Suche und lokaler Atheria-Kern |
| `NovaLensStore` | replaybare Lineage ueber `lineage.db` und `cas/` |
| `FederatedLearningMesh` | optionale Verteilung signifikanter Resonanz-Trigger |
| `aion_chronik.py` | lesbare Chronik- und Audit-Darstellung fuer die ALS-Spur |

## Architektur

```text
Feeds / API-Quellen
  ->
ALS Cycle
  ->
Resonanzbewertung
  ->
Trigger / Nicht-Trigger
  ->
Atheria-Training
  ->
Lens-Snapshot
  ->
Aion-Chronik-Audit
  ->
Speech Act / Voice
  ->
Dialog / Mesh / Events
```

## Was ALS im aktuellen Projektstand wirklich tut

Jeder Zyklus verarbeitet eingehende Signale und berechnet unter anderem:

- `signal_strength`
- `system_temperature`
- `resource_pressure`
- `structural_tension`
- `entropic_index`
- `anomaly_score`
- `trend_pressure`
- `trend_acceleration`
- `forecast_score`
- `confidence`

Darauf baut ALS drei Dinge auf:

1. laufende Wissensintegration in Atheria
2. lokale Kausalspur in Lens und Aion-Chronik
3. sprechbare kognitive Ausgabe als Speech Act

## Warum ALS nicht nur ein weiterer Sensor ist

Ein normaler Sensor liefert ein Ereignis.
ALS fuehrt einen laufenden Erkenntniszustand.

Der Unterschied:

- es gibt einen residenten Zustand mit Historie und Vokabularwachstum
- neue Signale werden gegen eine bereits gelernte Baseline bewertet
- Trigger und Nicht-Trigger werden beide persistiert
- Dialoge greifen auf die aktuelle Resonanzspur und vergangene Ereignisse zurueck
- Voice ist nicht nur Ausgabe, sondern Teil des Erkenntniskanals

## Persistenz und lokale Souveraenitaet

ALS speichert unter:

```text
~/.nova_shell_memory/atheria_als/
```

Wichtige Dateien:

| Datei | Inhalt |
| --- | --- |
| `config.json` | ALS-Konfiguration |
| `state.json` | laufender Zustand, Baseline, Vokabular, letzte Zyklen |
| `status.json` | aktueller Daemon-Status |
| `events.jsonl` | Stream-Ereignisse und Resonanzzyklen |
| `dialog.jsonl` | Fragen, Antworten und Feedback |
| `voice.jsonl` | Speech Acts und Voice-Metadaten |
| `daemon_runtime/atheria_daemon_audit.jsonl` | signierte Audit-Kette |
| `daemon_runtime/core_audit/` | lokale Audit-Schluessel und Invariant-Dateien |
| `aion_chronik.html` | lesbare HTML-Chronik aus der ALS-Spur |

Diese Struktur ist zentral fuer die Souveraenitaetsidee:

- Lernspur bleibt lokal
- Aussagen bleiben belegbar
- Chronik und Voice sind nicht losgeloest von der Kausalspur

## ALS und Lens

ALS schreibt nicht nur Dateien, sondern erzeugt auch Lens-Snapshots.
Dadurch wird jeder relevante Erkenntnisschritt in die bestehende Shell-Lineage eingebettet.

Typische Lens-Stages:

- `atheria.als.cycle`
- `atheria.als.dialog.ask`
- `atheria.als.dialog.feedback`

Damit lassen sich ALS-Schritte spaeter ueber `lens list`, `lens show` und `lens replay` nachvollziehen.

## ALS und Aion-Chronik

Jeder laufende ALS-Zustand schreibt signierte Audit-Eintraege.
Diese werden als HTML-Chronik unter `aion_chronik.html` aufbereitet.

Damit ist ALS nicht nur ein Streamprozess, sondern auch ein forensisch lesbarer Verlauf:

- Start des residenten Loops
- kontinuierliche Integritaetszyklen
- relevante Trend- und Anomalie-Trigger
- Shutdown des Loops

## CLI

Die operative ALS-Steuerung passiert ueber `atheria als`.

Wichtige Kommandos:

```text
atheria als status
atheria als configure
atheria als cycle
atheria als start
atheria als stop
atheria als search <query>
atheria als ask <question>
atheria als feedback <text>
atheria als voice status
atheria als voice last
atheria als voice speak <text>
atheria als analysis status
atheria als analysis last
atheria als analysis tail
atheria als stream tail
```

## Testbare Beispiele

### Status pruefen

```powershell
atheria als status
```

Erwartung:

- JSON mit `running`
- `current_resonance`
- `last_cycle`
- `voice`
- Chronik- und Basisverzeichnis

### Residenten Loop konfigurieren

```powershell
atheria als configure --topic "AI infrastructure agent runtime" --interval 90 --trigger 0.80 --anomaly-threshold 0.72
```

Erwartung:

- `config.json` wird aktualisiert
- Thema, Interval und Triggerwerte sind persistent gesetzt

### Sekundaere KI-Einordnung ueber LM Studio aktivieren

```powershell
atheria als configure --analysis on --analysis-provider lmstudio --analysis-model local-model
```

Erwartung:

- `config.json` enthaelt einen `interpretation`-Block
- jeder kuenftige `cycle` kann neben Atherias Primäraussage eine zweite lesbare Einordnung erzeugen
- die Einordnung landet in `interpretations.jsonl`
- die Chronik zeigt die Einordnung unterhalb der Atheria-Formulierung

### Websuche zusaetzlich zum Feed-Stream aktivieren

```powershell
atheria als configure --web-search on --search-query "AI infrastructure agent runtime" --search-provider duckduckgo_html --search-limit 6
```

Erwartung:

- `config.json` enthaelt einen `web_search`-Block
- kuenftige `cycle`- und `start`-Laeufe mischen RSS- und Suchergebnisse
- `status` zeigt die aktive Suchkonfiguration im Stream-Block

### Einzelausfuehrung fuer schnellen Test

```powershell
atheria als cycle
```

Erwartung:

- ein Ereignis in `events.jsonl`
- aktualisierter `state.json`
- ggf. ein `speech_act`
- ggf. eine `interpretation`
- Audit-Eintrag und Chronik-Refresh

### Direkte Websuche ohne dauerhaften Daemon-Lauf

```powershell
atheria als search "AI infrastructure agent runtime" --provider duckduckgo_html --limit 5
```

Erwartung:

- JSON mit `query`, `provider`, `result_count` und `results`
- jedes Ergebnis enthaelt `sensor: web_search`
- der Befehl aendert noch keinen ALS-Zustand

Falls die Suchtreffer sofort in ALS eingehen sollen:

```powershell
atheria als search "AI infrastructure agent runtime" --provider duckduckgo_html --limit 5 --ingest
```

Dann fuehrt ALS direkt einen Zyklus mit diesen Treffern aus.

### Residenten Loop starten

```powershell
atheria als start
atheria als status
```

Erwartung:

- Hintergrundprozess laeuft
- `status` zeigt `running: true`
- `als.pid` und Statusdateien sind vorhanden

### Laufende Atheria befragen

```powershell
atheria als ask "Was treibt gerade die Resonanz?"
```

Erwartung:

- Antworttext mit Evidenzbezug
- neuer Dialogeintrag in `dialog.jsonl`
- neuer Speech Act in `voice.jsonl`
- optional neue KI-Einordnung im Rueckgabepayload

### Feedback in die Evolution geben

```powershell
atheria als feedback "Gewichte GPU-Runtime-Anomalien hoeher als Funding-News."
```

Erwartung:

- Feedback wird als Training/Feedback-Eintrag aufgenommen
- Atheria bestaetigt die Rueckkopplung per Speech Act

### Letzte KI-Einordnung lesen

```powershell
atheria als analysis status
atheria als analysis last
atheria als analysis tail --limit 5
```

Erwartung:

- `analysis status` zeigt Aktivierung, Provider, Modell und den letzten Eintrag
- `analysis last` zeigt die neueste gespeicherte Einordnung
- `analysis tail` zeigt den Verlauf aus `interpretations.jsonl`

### Letzte Stream-Ereignisse ansehen

```powershell
atheria als stream tail --limit 5
```

## Voice als Grundschicht

Bei ALS ist Voice kein nachgeschaltetes Vorlesesystem.
Jeder relevante Output wird als `speech_act` modelliert.

Das bedeutet:

- Sprachakte sind persistente Artefakte
- sie enthalten Resonanzwerte, Evidenz-Referenzen und Prosodie
- Audio ist optional, Voice-Objekte aber nicht

Die vertiefte Doku steht in [AtheriaVoice.md](./AtheriaVoice.md).

## Menschliche Einordnungsschicht

ALS kann Atherias Primäraussage durch ein zweites Modell, typischerweise `lmstudio`, interpretieren lassen.

Diese Schicht dient nicht dazu, Atheria zu ersetzen, sondern ihre Aussage fuer Menschen zu verdichten:

- `statement`: Was sagt Atheria inhaltlich?
- `meaning`: Warum ist das relevant?
- `recommendation`: Was sollte als naechstes geprueft werden?
- `risk_level`: niedrig, mittel oder hoch

Die Einordnung wird:

- als JSON in `interpretations.jsonl` gespeichert
- im `status` unter `interpretation.last_analysis` sichtbar
- in der Chronik direkt unter der Voice-Zeile gerendert

## Typische Fragen

### Muss ALS manuell gestartet werden?

Fuer den residenten Prozess ja.
Danach existiert ALS als laufender Hintergrundpfad und reagiert zyklisch ohne weiteren `run`-Befehl.

### Ist ALS schon ein echter Push-Stream?

Aktuell ist es ein residenter Continuous-Loop ueber konfigurierte Feeds und APIs.
Das ist deutlich mehr als ein Einmal-Report, aber noch nicht der Endzustand eines globalen Push-Busses.

### Wo sehe ich die Kausalspur?

In drei Ebenen:

- `events.jsonl`
- `voice.jsonl` / `dialog.jsonl`
- `aion_chronik.html`

Fuer Shell-Replay zusaetzlich in Lens.

## Verwandte Seiten

- [AtheriaVoice](./AtheriaVoice.md)
- [AtheriaALSForDevelopers](./AtheriaALSForDevelopers.md)
- [TutorialAtheriaALS](./TutorialAtheriaALS.md)
- [NovaRuntime](./NovaRuntime.md)
- [NovaAgents](./NovaAgents.md)
- [NovaLens](./NovaLens.md)
- [LensForDevelopers](./LensForDevelopers.md)
