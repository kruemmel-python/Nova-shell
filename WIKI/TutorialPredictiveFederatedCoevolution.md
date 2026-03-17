# Tutorial Predictive, Federated and Co-Evolution

## Ziel

Dieses Tutorial fuehrt drei neue Nova-shell-Faehigkeiten als zusammenhaengenden Plattformpfad vor:

1. Forecast-basierte Engine-Wahl
2. Federated Invariant Sharing im Mesh
3. Mycelia-Atheria Co-Evolution

Am Ende hast du:

- einen warmen Predictive-Telemetriezustand
- ein publiziertes Federated-Update
- eine Population, die auf Atheria-Signale mit Co-Evolution reagiert

## Voraussetzungen

- Nova-shell laeuft lokal
- `doctor` sollte fuer die Kernkomponenten `ok` anzeigen
- optional: laufender Mesh-Worker fuer Broadcast-Tests

Pruefen:

```powershell
doctor
```

## Schritt 1: Predictive-Telemetrie aufbauen

Erzeuge zuerst einige echte Laufzeitereignisse:

```powershell
py 1 + 1
py 2 + 1
py 3 + 1
py 4 + 1
py 5 + 1
```

Wenn du moechtest, fuehre noch einige weitere `py`- oder `cpp`-Kommandos aus, damit der Forecast nicht nur Minimalhistorie sieht.

## Schritt 2: Forecast ansehen

```powershell
synth forecast
```

Pruefe in der Ausgabe:

- `status`
- `engine_pressure`
- `projection`
- `sample_count`

## Schritt 3: Predictive Shift testen

```powershell
synth shift suggest "for item in rows: total += item"
```

Wichtig sind:

- `engine`
- `reasons`
- `delegated_command`

Danach den delegierten Pfad wirklich ausfuehren:

```powershell
synth shift run "for item in rows: total += item"
```

## Schritt 4: Federated Update publizieren

Ohne Broadcast:

```powershell
mesh federated publish --statement "New invariant for edge anomaly detection" --namespace lab --project deco
```

Mit Broadcast:

```powershell
mesh federated publish --statement "New invariant for edge anomaly detection" --namespace lab --project deco --broadcast
```

Status und Historie pruefen:

```powershell
mesh federated status
mesh federated history 5
```

## Schritt 5: Chronik-Invariante ins Mesh heben

```powershell
mesh federated chronik-latest --namespace atheria --project deco --broadcast
```

Damit entsteht ein direkter Pfad von Atherias Resonanz-/Chronikzustand in den Federated-Mesh-Layer.

## Schritt 6: Co-Evolution laufen lassen

```powershell
mycelia coevolve run research-pop --cycles 3 --input "edge inference pressure rises"
```

Danach:

```powershell
mycelia coevolve status research-pop
```

Wenn du die Co-Evolution in einen normalen Population-Tick integrieren willst:

```powershell
mycelia population tick research-pop --cycles 3 --coevolve
```

## Schritt 7: Alles zusammen als Plattformmuster denken

Das Zusammenspiel sieht dann so aus:

```text
telemetry
  -> predictive forecast
  -> engine shift
  -> new invariant or report
  -> federated publish
  -> shared swarm memory
  -> coevolved agents and populations
```

## Typische Beobachtungen

### Predictive Forecast bleibt konservativ

Dann fehlt meist noch Telemetriehistorie oder die Vorhersagequalitaet ist bewusst niedrig.

### Federated Broadcast zeigt keine Anwendungen

Dann ist kein passender Worker erreichbar oder der Broadcast wurde ohne aktive Gegenstelle ausgefuehrt.

### Co-Evolution liefert wenig aussagekraeftige Scores

Dann ist das Eingangssignal zu schwach oder es fehlen verwertbare Forecast-/Tool-/Invariantdaten.

## Verwandte Seiten

- [NovaSynthPredictiveEngineShifting](./NovaSynthPredictiveEngineShifting.md)
- [ZeroCopyFederatedLearningMesh](./ZeroCopyFederatedLearningMesh.md)
- [MyceliaAtheriaCoEvolution](./MyceliaAtheriaCoEvolution.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)
