# Data And Execution Engines

## Zweck

Nova-shell fuehrt nicht nur Python aus. Die Daten- und Execution-Schicht fasst mehrere Backends zusammen, die je nach Aufgabe unterschiedlich geeignet sind.

## Kernpunkte

- `py` deckt schnellen Ausdrucks- und Skriptbetrieb ab.
- `cpp` und `cpp.sandbox` adressieren nativen bzw. sandboxed C++-Code.
- `gpu` adressiert OpenCL-basierte GPU-Ausfuehrung, wenn `pyopencl` und `numpy` verfuegbar sind.
- `wasm` und `jit_wasm` adressieren portable bzw. Emscripten-basierte Ausfuehrungspfade.
- `data` und `data.load` liefern strukturierte Datenverarbeitung und Dateieinbindung.

## Praktische Nutzung

- Nutze `py` fuer den Standardfall.
- Nutze `cpp.sandbox`, wenn du isolierten nativen Code in einer kontrollierten Laufzeit ausprobieren willst.
- Nutze `gpu`, wenn OpenCL-Gerate und passende Laufzeitmodule vorhanden sind.
- Nutze `data.load` und anschliessend `py`, wenn du tabellarische oder JSON-Daten in Pipelines brauchst.

## Testbare Einstiege

### Ein einfacher Compute-Check

```powershell
py 1 + 1
cpp.sandbox int main(){ return 0; }
doctor
```

Erwartung:

- `py` liefert direkt ein Ergebnis.
- `cpp.sandbox` meldet im Erfolgsfall `sandbox executed`.
- `doctor` zeigt, welche Runtime-Module wirklich verfuegbar sind.

## Typische Fragen und Fehler

### GPU oder WASM laufen nicht

- `doctor` zeigt die benoetigten Module als `missing`.
- Toolchain oder Runtime fehlen im aktuellen Profil.
- Nutze zuerst den Minimaltest ueber `doctor` und `cpp.sandbox`.

## Verwandte Seiten

- [ProgrammingWithNovaShell](./ProgrammingWithNovaShell.md)
- [NovaCLI](./NovaCLI.md)
- [ExecutionModel](./ExecutionModel.md)
- [PerformanceAndScaling](./PerformanceAndScaling.md)
