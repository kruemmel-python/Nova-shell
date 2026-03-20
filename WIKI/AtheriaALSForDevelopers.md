# Atheria ALS For Developers

## Zweck

Diese Seite erklaert ALS aus Entwicklersicht:

- Dateilayout
- Lebenszyklus
- Shell-Anbindung
- Chronik- und Lens-Integration
- Erweiterungspunkte

## Kernklassen

| Klasse | Datei | Rolle |
| --- | --- | --- |
| `AtheriaALSRuntime` | `nova/runtime/atheria_als.py` | residenter Live-Stream-Kern |
| `AtheriaVoiceRuntime` | `nova/runtime/atheria_als.py` | Speech Acts und lokale Audioausgabe |
| `NovaAtheriaRuntime` | `nova_shell.py` | lokales Training und Suche |
| `NovaAIProviderRuntime` | `nova_shell.py` | Provider-Aufrufe fuer Dialoge |
| `NovaLensStore` | `nova_shell.py` | replaybare Lineage |

## Dateilayout

```text
~/.nova_shell_memory/atheria_als/
  config.json
  state.json
  status.json
  events.jsonl
  dialog.jsonl
  voice.jsonl
  interpretations.jsonl
  als.pid
  stop.request
  aion_chronik.html
  voice_runtime/
    latest_speech_act.json
    latest_utterance.txt
    latest_utterance.ssml
  daemon_runtime/
    atheria_daemon_audit.jsonl
    core_audit/
      nova-shell-als_audit.key
      nova-shell-als_inter_core_resonance.jsonl
```

## Lebenszyklus

```text
configure()
  ->
serve_forever()
  ->
run_cycle()
  ->
train_rows()
  ->
lens.record()
  ->
interpretation append
  ->
audit append
  ->
chronik refresh
  ->
speech act append
```

## Shell-Anbindung

Der Einstieg liegt in `nova_shell.py` unter:

- Instanziierung in `NovaShell.__init__`
- Dispatch in `atheria als ...`
- Daemon-Start in `main(... --serve-atheria-als)`

## Dialogpfad

`ask(...)` arbeitet aktuell so:

1. aus der Benutzerfrage ein frisches Dialog-Probe-Ereignis erzeugen
2. dazu aktuelle RSS- und optionale `web_search`-Treffer sammeln
3. frische Signale gegen letzte ALS-Ereignisse, Lens-Referenzen und Atheria-Memory gewichten
4. bevorzugt ueber Provider `atheria` antworten
5. bei Ausfall kontrolliert heuristisch antworten
6. optional zweite Einordnung ueber `lmstudio` oder einen anderen Provider erzeugen
7. Speech Act, Dialog, Analyse und Chronikdaten persistent schreiben

Wichtig:
`ask(...)` soll fuer aktuelle Fragen nicht nur alte Restresonanz wiederholen.
Deshalb bevorzugt der aktuelle Pfad frische, fragerelevante Signale gegenueber historischen ALS-Ereignissen.

## Triggerlogik

ALS loest aktuell einen Trigger aus, wenn bereits eine Baseline existiert und mindestens einer dieser Werte anspringt:

- `trend_acceleration >= trigger_threshold`
- `anomaly_score >= anomaly_threshold`

Ohne Baseline baut der erste Lauf nur den Zustand auf.

## Aion-Chronik-Format

ALS schreibt kompatible Audit-Eintraege mit:

- `previous`
- `journal_key_fingerprint`
- `journal_signature`
- `reason`
- `market`
- `extra`

Damit kann `aion_chronik.py` dieselbe Spur direkt rendern.

Im `extra`-Block liegen fuer ALS inzwischen typischerweise:

- `dialog_question`
- `probe`
- `speech_act`
- `interpretation`
- `interpretation_label`
- `source_titles`
- `dominant_topics`
- `sensor_counts`
- `metrics`

## Lens-Integration

ALS nutzt Lens bewusst nur an entscheidenden Knoten:

- Zyklus
- Dialogfrage
- Feedback

Damit bleibt die Kausalspur dicht genug fuer Replay, ohne jeden Hilfsschritt zu verrauschen.

## Erweiterungspunkte

Sinnvolle naechste Ausbaustufen:

- echte Push-Transportquellen statt nur residentem Pull-Loop
- weitere Voice-Backends
- differenziertere Triggerprofile pro Thema
- feinere Mesh-Offload-Strategien fuer Streamvorverarbeitung

## Tests

Die aktuelle ALS-Abdeckung prueft:

- Zyklus mit Trigger, Lens, Voice und Chronik
- Zyklus mit LM-Studio-Einordnung und Chronik-Render
- Dialog ueber `atheria als ask`
- Feedback ueber `atheria als feedback`
- CLI-Startpfad `--serve-atheria-als --als-once`
- Frage-Erdung mit frischen RSS- und Web-Signalen
- Chronik-Render mit Frage, Atheria-Text und LM-Studio-Einordnung
- Systemdynamik:
  - Lernen veraendert spaetere Antworten
  - Drift bleibt unter Kontrolle
  - Fokus bleibt bei stabilem Signal hinreichend konsistent
  - Memory beeinflusst spaetere Antworten

## Verwandte Seiten

- [AtheriaContinuousEvolutionAndLiveStream](./AtheriaContinuousEvolutionAndLiveStream.md)
- [AtheriaVoice](./AtheriaVoice.md)
- [NovaRuntime](./NovaRuntime.md)
- [NovaCLI](./NovaCLI.md)
- [NovaLens](./NovaLens.md)
