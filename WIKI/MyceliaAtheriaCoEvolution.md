# Mycelia-Atheria Co-Evolution

## Zweck

Mycelia-Atheria Co-Evolution verbindet die ALife-Schicht `mycelia` mit Atherias Prognose- und Invariantensystem.
Populationen optimieren nicht mehr nur einen simplen Fitnesswert, sondern werden an mehreren Signalen gemessen:

- Forecast-Qualitaet
- Invariant-Ausrichtung
- Tool-Integritaet und Erfolgsrate
- geometrische Komplexitaet ueber Atherias Kruemmungsproxy

Damit wird aus Agentenmutation keine Spielerei, sondern ein kontrollierter, messbarer Optimierungsprozess.

## Kernobjekte

| Objekt | Rolle |
| --- | --- |
| `MyceliaAtheriaCoEvolutionLab` | Co-Evolution-Schicht und Persistenz |
| `MyceliaRuntime` | Population, Reproduktion und Zyklussteuerung |
| `ToolExecutionRecord` | Erfolg, Ausfall und Nutzwert einzelner Toolpfade |
| `MarketLandscapeFutureProjector` | prognostischer Anteil der Fitness |
| `InformationEinsteinLikeSimulator` | Rekonstruktion und Kruemmungsproxy als Strafterm |

## Fitness-Modell

```text
base fitness
  +
forecast quality
  +
invariant alignment
  +
tool integrity
  -
curvature penalty
  =
coevolution score
```

Dieses Modell verhindert, dass Populationen nur auf vergangene Beispiele ueberfitten oder unkontrolliert komplexer werden.

## CLI

### Dedizierten Co-Evolution-Lauf starten

```powershell
mycelia coevolve run research-pop --cycles 5 --input "edge inference pressure rises"
```

### Status der Population ansehen

```powershell
mycelia coevolve status research-pop
```

### Bestehenden Population-Tick um Co-Evolution erweitern

```powershell
mycelia population tick research-pop --cycles 5 --coevolve
```

## Testbare Beispiele

### 1. Population mit Co-Evolution laufen lassen

```powershell
mycelia coevolve run trend-rss --cycles 3 --input "news feeds with predictive relevance"
```

Erwartung:

- Rueckgabe mit `population`, `cycles`, `best_individual` und `coevolution`

### 2. Reportdatei in die Bewertung einbeziehen

```powershell
mycelia coevolve run project-review --cycles 2 --report-file .nova_project_monitor\\project_monitor_analysis.json
```

Damit kann eine Population direkt auf bestehende Analyseberichte oder Projektzustandsdaten reagieren.

### 3. Populationstakt mit Schwarmmodus

```powershell
mycelia coevolve run swarm-lab --cycles 5 --swarm --input "distributed anomaly detection"
```

## Persistenz

Die Co-Evolution speichert unter Atherias Storage-Root:

- Verlauf vergangener Runs
- Scores
- Forecast- und Kruemmungsanteile
- Population-/Best-Individual-Metadaten

Das macht Fitnessverlaeufe ueber mehrere Shell-Sessions hinweg nachvollziehbar.

## Designentscheidungen

### Warum Kruemmung als Strafterm?

Weil komplexe, stark gekruemmte Modelle oft eindrucksvoll wirken, aber auf historischen Daten ueberpassen.
Die Kruemmungsstrafe zwingt Populationen zu stabileren, glatteren Strategien.

### Warum Forecast-Qualitaet mit Tool-Erfolg kombinieren?

Eine Population soll nicht nur gute Geschichten erzaehlen, sondern auch mit realen Toolpfaden tragfaehige Ergebnisse erzeugen.

## Typische Fehler und Fragen

### Warum verbessert sich die Population kaum?

Typische Gruende:

- zu wenig Variabilitaet
- schlechtes Eingangssignal
- starke Kruemmungsstrafe
- kaum verwertbare Tool- oder Forecast-Daten

### Woran erkenne ich, dass Co-Evolution aktiv war?

In der Rueckgabe stehen:

- `coevolution`
- Forecast-Metriken
- curvature- oder penalty-bezogene Werte

### Kann ich Co-Evolution in den normalen Population-Tick integrieren?

Ja. Genau dafuer gibt es `--coevolve`.
Der klassische Mycelia-Pfad bleibt aber auch ohne diesen Zusatz nutzbar.

## Verwandte Seiten

- [NovaAgents](./NovaAgents.md)
- [Research](./Research.md)
- [AIOSConcept](./AIOSConcept.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)
