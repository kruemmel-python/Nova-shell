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
  als.pid
  stop.request
  aion_chronik.html
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

1. aktuelle Resonanz und letzte ALS-Ereignisse sammeln
2. relevante Lens-Referenzen aufnehmen
3. Atheria-Trainingstreffer suchen
4. bevorzugt ueber Provider `atheria` antworten
5. bei Ausfall kontrolliert heuristisch antworten
6. Speech Act und Dialog persistent schreiben

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
- Dialog ueber `atheria als ask`
- Feedback ueber `atheria als feedback`
- CLI-Startpfad `--serve-atheria-als --als-once`

## Verwandte Seiten

- [AtheriaContinuousEvolutionAndLiveStream](./AtheriaContinuousEvolutionAndLiveStream.md)
- [AtheriaVoice](./AtheriaVoice.md)
- [NovaRuntime](./NovaRuntime.md)
- [NovaCLI](./NovaCLI.md)
- [NovaLens](./NovaLens.md)
