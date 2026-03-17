# NovaSynth Predictive Engine-Shifting

## Zweck

NovaSynth Predictive Engine-Shifting erweitert Nova-shell um eine vorausschauende Engine-Wahl.
Statt Workloads nur statisch oder rein heuristisch zwischen `py`, `cpp`, `gpu` und `mesh` zu verschieben, nutzt der Shifter Telemetrie, Atheria-Signale und Prognosen aus dem Atheria-Landscape-Projector.

Das Ziel ist nicht nur Reaktion auf Last, sondern proaktive Migration:

- Python nach `cpp`, wenn Schleifen- und Interpreterkosten dominieren
- numerische Workloads nach `gpu`, bevor die lokale CPU kippt
- trainings- oder batchlastige Aufgaben nach `mesh`, wenn Druck und Latenz steigen

## Kernobjekte

| Objekt | Rolle |
| --- | --- |
| `PredictiveEngineShifter` | sammelt Telemetrie, erzeugt Forecasts und empfiehlt Engines |
| `PredictiveTelemetryEvent` | normiertes Telemetrieereignis pro Stage-Ausfuehrung |
| `NovaOptimizer` | einfache Heuristikschicht, deren Scores in den Predictive-Pfad einfliessen |
| `NovaSynth` | CLI-Einstieg fuer `synth forecast` und `synth shift` |
| `MarketLandscapeFutureProjector` | Atheria-basierter Forecast-Kern fuer Stress- und Szenarioprojektionen |

## Datenfluss

```text
Stage execution
  ->
telemetry event
  ->
PredictiveEngineShifter.record_event()
  ->
Atheria projector forecast
  ->
pressure index + scenario probabilities
  ->
engine recommendation
  ->
delegated command (py/cpp/gpu/mesh)
```

## CLI

### Forecast erzeugen

```powershell
synth forecast
```

Typischer Zweck:

- Lastentwicklung ansehen
- Prognosequalitaet pruefen
- verstehen, warum Nova-shell auf `cpp`, `gpu` oder `mesh` umschalten will

### Engine-Empfehlung fuer einen Codepfad

```powershell
synth shift suggest "for item in rows: total += item"
```

Typisches Ergebnis:

```json
{
  "engine": "cpp",
  "pressure_index": 0.83,
  "predictability_index": 0.41,
  "delegated_command": "cpp.expr ...",
  "migration_kind": "python_to_cpp_expr"
}
```

### Delegierten Pfad direkt ausfuehren

```powershell
synth shift run "for item in rows: total += item"
```

Das fuehrt nicht blind Python aus, sondern den von NovaSynth empfohlenen Zielpfad.

## Testbare Beispiele

### 1. Forecast mit kuenstlich erhitzter Telemetrie

```powershell
py 1 + 1
py 2 + 1
py 3 + 1
synth forecast
```

Wirklich aussagekraeftig wird der Forecast erst nach mehreren Events.

### 2. Loop-heavy Python nach C++ kippen lassen

```powershell
synth shift suggest "for item in rows: total += item"
```

Erwartung:

- `engine` ist eher `cpp` oder bei hoher Last `mesh`
- `reasons` enthaelt Hinweise wie `loop-heavy workload favors compiled execution`

### 3. Numerischen Pfad auf GPU oder Mesh lenken

```powershell
synth shift suggest "matrix multiply tensor embedding fft"
```

Erwartung:

- bei verfuegbarer GPU: `gpu`
- ohne lokale GPU, aber mit passenden Workern: `mesh`

## Persistierte Artefakte

Der Predictive-Pfad schreibt unter Atherias Storage-Root in:

- `.nova/predictive-engine-telemetry.jsonl`
- `.nova/predictive-engine-status.json`

Damit bleibt der Forecast ueber Shell-Lebenszyklen hinweg warm.

## Designentscheidungen

### Warum Forecast statt nur Heuristiken?

Heuristiken erkennen Muster im Code.
Forecasts erkennen zusaetzlich, ob das System in Richtung Engpass, Ueberhitzung oder Spannungsanstieg driftet.

### Warum Atheria als Forecast-Kern?

Die Atheria-Projector-Schicht ist bereits auf zeitliche Landschaftsprognosen ausgelegt.
Hier wird sie nicht fuer Maerkte, sondern fuer interne Runtime-Telemetrie genutzt.

### Warum nicht immer direkt auf `mesh`?

Mesh-Offloading ist nicht kostenlos.
Der Shifter gewichtet deshalb:

- Druck
- Vorhersagequalitaet
- Workload-Signatur
- lokale Verfuegbarkeit von GPU und Workern

## Typische Fehler und Fragen

### Warum bleibt der Forecast auf `insufficient_history`?

Dann wurden noch zu wenige Telemetrieevents gesammelt.
Fuehre zuerst einige reale `py`, `cpp` oder `gpu`-Stages aus und pruefe dann erneut mit:

```powershell
synth forecast
```

### Warum wird kein `gpu` vorgeschlagen?

Weil entweder:

- keine GPU verfuegbar ist
- die Signatur nicht numerisch genug ist
- oder der Mesh-/C++-Pfad unter den aktuellen Druckwerten sinnvoller ist

### Wo sehe ich den delegierten Zielpfad?

Im Rueckgabefeld `delegated_command`.
Das ist der Pfad, den `synth shift run` anschliessend wirklich benutzt.

## Verwandte Seiten

- [NovaRuntime](./NovaRuntime.md)
- [NovaMesh](./NovaMesh.md)
- [OperationsAndObservability](./OperationsAndObservability.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)
