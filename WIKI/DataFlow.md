# Data Flow

## Zweck

Diese Seite beschreibt, wie Daten, Steuerfluss und Ereignisse durch Nova-shell laufen. Wichtig ist die Trennung zwischen Datenkanten und Kontrollkanten.

## Kernpunkte

- Datasets bringen Daten in den Graphen ein.
- Flows transformieren Daten ueber Tools, Backends und Agenten.
- State speichert Ergebnisse oder Zwischenschritte persistent.
- Events aktivieren Flows, ohne selbst Nutzdaten verarbeiten zu muessen.

## Praktische Nutzung

- Lies einen Flow immer als Kette von Ein- und Ausgabewerten.
- Pruefe bei Fehlern zuerst, ob Datenwerte oder Event-Ausloeser fehlen.
- Nutze `ns.graph`, wenn unklar ist, in welcher Reihenfolge Knoten verbunden wurden.

## Testbare Einstiege

### Einfache Event-zu-Flow-Kette

Lege zuerst ein minimales Programm als Datei an und fuehre es danach aus.

```powershell
@"
system control_plane {
  daemon_autostart: false
}

flow queued_job {
  system.log "queued" -> queue_output
  state.set queue_value queue_output
}

event ping_handler {
  on: ping
  flow: queued_job
}
"@ | Set-Content .\control.ns
ns.run .\control.ns
event emit ping now
ns.control events ping 0 10
```

Erwartung:

- Das Event wird geloggt.
- Der zugeordnete Flow wird danach ausgeloest.

## Typische Fragen und Fehler

### Ein Flow bekommt keine Eingabe

- Ein vorheriger Knoten hat nichts geliefert.
- Der Event-Pfad wurde nicht ausgelost.
- Der State-Eintrag wurde unter einem anderen Schluessel geschrieben.

## Verwandte Seiten

- [ExecutionModel](./ExecutionModel.md)
- [ComponentModel](./ComponentModel.md)
- [NovaRuntime](./NovaRuntime.md)
- [NovaGraphEngine](./NovaGraphEngine.md)
