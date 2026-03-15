# Tutorial: Technology Radar

## Ziel

Ein einfacher Radar-Workflow sammelt Signale aus einem Dataset und laesst sie durch einen Agenten verdichten.
Dieses Tutorial ist der beste erste Lauf fuer die deklarative Sprache.

## Voraussetzungen

- funktionierende Installation, geprueft mit `doctor`
- Zugriff auf die Beispielprogramme im Ordner `examples`
- eine Runtime, die `ns.graph` und `ns.run` ausfuehren kann

## Beispielprogramm

Das Tutorial basiert auf der Datei `examples/market_radar.ns` im Repository.
Die dortige Struktur kombiniert:

- `system` fuer lokale Runtime-Konfiguration
- `state` fuer Memory/Knowledge-Namespace
- `agent researcher`
- `dataset tech_rss`
- `flow radar`
- `event new_information`

## Schritte

### 1. Graph anzeigen

```powershell
ns.graph examples\market_radar.ns
```

Erwartung: Die Runtime zeigt dir die kompilierten Knoten und deren Reihenfolge.

### 2. Programm ausfuehren

```powershell
ns.run examples\market_radar.ns
```

Erwartung: Dataset, Embedding-Pfad und Agent-Schritt werden durchlaufen.

### 3. Ergebnis interpretieren

Achte auf diese inhaltlichen Rollen:

- `rss.fetch tech_rss -> fresh_news`
- `atheria.embed tech_rss -> embedded_news`
- `researcher summarize tech_rss -> briefing`

Damit siehst du die drei Grundachsen des Systems:

1. Daten laden
2. Wissen oder Embeddings aufbauen
3. Agentenaktion auf den Daten ausfuehren

## Ergebnispruefung

Wenn `ns.graph` funktioniert, aber `ns.run` nicht, liegt das Problem meist nicht in der Syntax, sondern in Runtime, Datenpfad oder Provider-Konfiguration.

## Was dieses Tutorial lehrt

- Grundsyntax von `.ns`
- Datenfluss in einem einfachen Graph
- Zusammenspiel von Dataset, Agent, Memory und Atheria

## Verwandte Seiten

- [NovaLanguage](./NovaLanguage.md)
- [NovaGraphEngine](./NovaGraphEngine.md)
- [DataFlow](./DataFlow.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)
