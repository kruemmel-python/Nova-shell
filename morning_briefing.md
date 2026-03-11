# Morning Briefing

`morning_briefing.ns` ist die kompakte Tagesroutine fuer den RSS-/Guardian-/TrendRadar-Pfad.

Ein einziger Befehl:

```text
ns.run morning_briefing.ns
```

Der Ablauf macht automatisch:

1. initialisiert Atheria und setzt einen dedizierten `memory namespace` / `project`
2. legt `Whitepaper.md` und `Dokumentation.md` idempotent im Vector Memory ab
3. scannt die konfigurierten RSS-Feeds mit `BigPlayerWatcher`
4. fuehrt `TrendRadar` aus und erzeugt bei Bedarf einen zweiten Lauf fuer die erste Baseline
5. ruft `atheria guardian recommend` auf dem Trend-Signal auf
6. schreibt drei Textdateien und drei HTML-Dateien
7. gibt eine kompakte Zusammenfassung in der Nova-shell-REPL aus

Erzeugte Dateien standardmaessig unter `reports/`:

- `rss_resonance_report.txt`
- `rss_resonance_report.html`
- `rss_trend_report.txt`
- `rss_trend_report.html`
- `rss_morning_briefing.txt`
- `rss_morning_briefing.html`

Die HTML-Dateien enthalten den Guardian-Output zusaetzlich als HTML-Kommentar.

## Typischer Start

In Nova-shell:

```text
cd D:\Nova-shell
py os.environ["INDUSTRY_FEEDS"] = "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml,https://feeds.feedburner.com/TechCrunch/,https://news.google.com/rss/search?q=AI+infrastructure+agent+runtime"
ns.run morning_briefing.ns
```

## Wichtige Umgebungsvariablen

- `INDUSTRY_FEEDS`: kommaseparierte RSS-/Atom-Feeds
- `INDUSTRY_SCAN_FILE`: alternative lokale JSON-/RSS-/XML-Datei
- `NEWSAPI_KEY`: optionaler Fallback fuer NewsAPI
- `INDUSTRY_NEWS_QUERY`: Suchanfrage fuer NewsAPI
- `INDUSTRY_TREND_STATE`: Pfad fuer den persistierten TrendRadar-Zustand
- `NOVA_BRIEFING_REPORT_DIR`: Zielordner fuer alle Briefing-Reports
- `NOVA_RESONANCE_THRESHOLD`: Schwellwert fuer Resonanzsignale

## Beispiel fuer eine typische Ausgabe

```text
Heute empfehle ich 2 neue Sensoren im Bereich edge_ai, local_inference, da die Trend-Acceleration bei +0.05 liegt und der Forecast 'emerging_uptrend' mit Score 0.83 meldet.
```

## Hinweise

- Wenn `INDUSTRY_FEEDS` nicht gesetzt ist, verwendet das Skript denselben technischen Feed-Mix wie die bestehende RSS-Demo.
- `TrendRadar` wird so gestartet, dass ein frischer Zustand beim allerersten Lauf automatisch eine Baseline und danach einen echten Forecast erzeugen kann.
- Der tägliche Lauf ist idempotent genug fuer den operativen Gebrauch: die Memory-Eintraege fuer Whitepaper und Dokumentation werden mit festen IDs geschrieben und ueberschrieben.
