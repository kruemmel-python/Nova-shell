# Beispiel: RSS-Feeds mit zwei Sensoren ueberwachen und Ergebnisse nach TXT + HTML exportieren

Diese Anleitung beschreibt den aktuellen produktiven Ablauf fuer Nova-shell `0.8.5`.

Sie zeigt einen vollstaendig kopierbaren Ablauf mit dem vorhandenen Nova-shell-Setup:

- RSS-Feeds ueber `py os.environ["INDUSTRY_FEEDS"] = "..."` setzen
- Sensor 1: den vorhandenen Watcher [watch_the_big_players.ns](/d:/Nova-shell/watch_the_big_players.ns) starten
- Sensor 2: den lernenden Trend-Sensor [trend_rss_sensor.py](/d:/Nova-shell/trend_rss_sensor.py) direkt laden und mehrfach ausfuehren
- die Ergebnisse aus `flow.state` oder direkt aus dem Sensor-Output lesen
- alles direkt als Textdatei und HTML-Datei speichern
- danach die neuen Guardian-/Evolve-Pfade nutzen, um aus dem Trendbericht konkrete Sensor-Empfehlungen und Evolutionssignale abzuleiten

Die Beispiele basieren auf:

- [watch_the_big_players.ns](/d:/Nova-shell/watch_the_big_players.ns)
- [industry_scanner.py](/d:/Nova-shell/industry_scanner.py)
- [trend_rss_sensor.py](/d:/Nova-shell/trend_rss_sensor.py)
- [Whitepaper.md](/d:/Nova-shell/Whitepaper.md)
- [Dokumentation.md](/d:/Nova-shell/Dokumentation.md)

## Zielbild

Am Ende hast du lokal zum Beispiel diese Dateien:

- `reports/rss_resonance_report.txt`
- `reports/rss_resonance_report.html`
- `reports/rss_trend_report.txt`
- `reports/rss_trend_report.html`

Die Dateien enthalten:

- beim ersten Sensor den letzten erkannten Resonanz-Treffer
- beim zweiten Sensor den gelernten Trend-Forecast
- Score, Zusammenfassung und Richtung
- Titel, Quelle und URL der gefundenen RSS-Meldungen

## Voraussetzungen

Der Ablauf geht davon aus, dass du Nova-shell bereits gestartet hast und dich im Projektordner befindest:

```text
cd D:\Nova-shell
```

Wichtig:

- `py os.environ[...] = ...` funktioniert innerhalb von Nova-shell.
- PowerShell-Syntax wie `$env:INDUSTRY_FEEDS=...` funktioniert nur ausserhalb der Nova-shell-REPL.

## 1. RSS-Feeds in Nova-shell setzen

Setze zuerst die gewuenschten Feeds direkt im Python-Kontext von Nova-shell:

```text
py os.environ["INDUSTRY_FEEDS"] = "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml,https://feeds.feedburner.com/TechCrunch/,https://news.google.com/rss/search?q=AI+infrastructure+agent+runtime"
```

Optional kannst du den Watcher fuer einen sichtbaren Testlauf aggressiver einstellen:

```text
py os.environ["NOVA_RESONANCE_THRESHOLD"] = "0.20"
py os.environ["NOVA_SCAN_INTERVAL_SECONDS"] = "1"
py os.environ["NOVA_SCAN_ITERATIONS"] = "1"
```

Erklaerung:

- `INDUSTRY_FEEDS` uebergibt dem Sensor mehrere RSS-/Atom-Quellen.
- `NOVA_RESONANCE_THRESHOLD` bestimmt, ab welchem `score` ein Treffer als Resonanz gilt.
- `NOVA_SCAN_INTERVAL_SECONDS` ist die Wartezeit zwischen zwei Schleifen.
- `NOVA_SCAN_ITERATIONS` begrenzt die Anzahl der Schleifen.

Fuer Live-Betrieb kannst du spaeter wieder konservativere Werte verwenden, zum Beispiel:

```text
py os.environ["NOVA_RESONANCE_THRESHOLD"] = "0.85"
py os.environ["NOVA_SCAN_INTERVAL_SECONDS"] = "3600"
py os.environ["NOVA_SCAN_ITERATIONS"] = "100"
```

## 2. Watcher starten

Starte jetzt den vorhandenen Watcher:

```text
ns.run watch_the_big_players.ns
```

Was intern passiert:

1. Atheria wird initialisiert.
2. `Whitepaper.md` und `Dokumentation.md` werden als Architekturwissen trainiert.
3. Der Sensor `BigPlayerWatcher` wird aus [industry_scanner.py](/d:/Nova-shell/industry_scanner.py) geladen.
4. Die RSS-Feeds werden abgerufen.
5. Aus den Meldungen wird ein `score` berechnet.
6. Wenn der `score` ueber dem Schwellwert liegt, wird der Treffer nach `flow state set "last_match"` geschrieben.
7. Danach wird der Watch-Hook `resonance_detected` ausgeloest.

Wenn du zuerst nur pruefen willst, was der Sensor ohne die komplette Watch-Schleife sieht, kannst du vorher auch direkt testen:

```text
atheria sensor load "industry_scanner.py" --name "BigPlayerWatcher"
atheria sensor run "BigPlayerWatcher"
```

Die Rueckgabe enthaelt typischerweise:

- `summary`
- `score`
- `metadata.items`

## 3. Letzten Treffer aus `flow.state` lesen

Sobald der Watcher einen Treffer geschrieben hat, kannst du ihn direkt in Nova-shell inspizieren:

```text
py match = flow.state.get("last_match")
py match
```

Typisch relevante Felder:

- `match["score"]`
- `match["summary"]`
- `match["metadata"]["items"]`

Nur die Titel ausgeben:

```text
py for item in flow.state.get("last_match")["metadata"]["items"]: print(f"--- FOUND: {item['title']} ---")
```

## 4. Ergebnis direkt als TXT-Datei schreiben

Jetzt wird aus dem gespeicherten Treffer ein Textreport gebaut:

```text
py import pathlib
py match = flow.state.get("last_match") or {}
py items = match.get("metadata", {}).get("items", [])
py pathlib.Path("reports").mkdir(parents=True, exist_ok=True)
py text_lines = ["Nova-shell RSS Resonance Report", "", f"Score: {match.get('score', '')}", f"Summary: {match.get('summary', '')}", ""]
py text_lines.extend([f"- {item.get('title', '')} | {item.get('source', '')} | {item.get('url', '')}" for item in items])
py pathlib.Path("reports/rss_resonance_report.txt").write_text("\n".join(text_lines), encoding="utf-8")
```

Danach liegt die Datei hier:

```text
reports/rss_resonance_report.txt
```

## 5. Ergebnis direkt als HTML-Datei schreiben

Jetzt erzeugst du aus demselben Treffer eine einfache HTML-Uebersicht:

```text
py import html
py match = flow.state.get("last_match") or {}
py items = match.get("metadata", {}).get("items", [])
py html_rows = "".join([f"<li><a href='{html.escape(item.get('url', ''))}'>{html.escape(item.get('title', ''))}</a><br><small>{html.escape(item.get('source', ''))}</small></li>" for item in items])
py html_doc = f"<html><head><meta charset='utf-8'><title>Nova-shell RSS Resonance Report</title></head><body><h1>Nova-shell RSS Resonance Report</h1><p><strong>Score:</strong> {html.escape(str(match.get('score', '')))}</p><p><strong>Summary:</strong> {html.escape(str(match.get('summary', '')))}</p><h2>Items</h2><ul>{html_rows}</ul></body></html>"
py pathlib.Path("reports/rss_resonance_report.html").write_text(html_doc, encoding="utf-8")
```

Danach liegt die HTML-Datei hier:

```text
reports/rss_resonance_report.html
```

## 6. Vollstaendiger copy-paste Ablauf

Wenn du den gesamten Ablauf direkt in Nova-shell durchgehen willst:

```text
cd D:\Nova-shell
py os.environ["INDUSTRY_FEEDS"] = "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml,https://feeds.feedburner.com/TechCrunch/,https://news.google.com/rss/search?q=AI+infrastructure+agent+runtime"
py os.environ["NOVA_RESONANCE_THRESHOLD"] = "0.20"
py os.environ["NOVA_SCAN_INTERVAL_SECONDS"] = "1"
py os.environ["NOVA_SCAN_ITERATIONS"] = "1"
ns.run watch_the_big_players.ns
py import pathlib
py import html
py match = flow.state.get("last_match") or {}
py items = match.get("metadata", {}).get("items", [])
py pathlib.Path("reports").mkdir(parents=True, exist_ok=True)
py text_lines = ["Nova-shell RSS Resonance Report", "", f"Score: {match.get('score', '')}", f"Summary: {match.get('summary', '')}", ""]
py text_lines.extend([f"- {item.get('title', '')} | {item.get('source', '')} | {item.get('url', '')}" for item in items])
py pathlib.Path("reports/rss_resonance_report.txt").write_text("\n".join(text_lines), encoding="utf-8")
py html_rows = "".join([f"<li><a href='{html.escape(item.get('url', ''))}'>{html.escape(item.get('title', ''))}</a><br><small>{html.escape(item.get('source', ''))}</small></li>" for item in items])
py html_doc = f"<html><head><meta charset='utf-8'><title>Nova-shell RSS Resonance Report</title></head><body><h1>Nova-shell RSS Resonance Report</h1><p><strong>Score:</strong> {html.escape(str(match.get('score', '')))}</p><p><strong>Summary:</strong> {html.escape(str(match.get('summary', '')))}</p><h2>Items</h2><ul>{html_rows}</ul></body></html>"
py pathlib.Path("reports/rss_resonance_report.html").write_text(html_doc, encoding="utf-8")
```

## 7. Was tun, wenn `last_match` leer ist?

Wenn `flow.state.get("last_match")` `None` zurueckgibt, dann gab es drei typische Ursachen:

1. Der aktuelle `score` lag unter dem Schwellwert.
2. Die Feeds lieferten keine oder kaum passende Meldungen.
3. Die Schleife lief zwar, aber ohne Resonanz-Treffer.

Pragmatische Loesungen:

```text
py os.environ["NOVA_RESONANCE_THRESHOLD"] = "0.10"
ns.run watch_the_big_players.ns
```

Oder zuerst direkt den Sensor pruefen:

```text
atheria sensor load "industry_scanner.py" --name "BigPlayerWatcher"
atheria sensor run "BigPlayerWatcher"
```

Dann siehst du sofort, welcher `score` fuer die aktuellen RSS-Meldungen wirklich erzeugt wird.

## 8. Optional: Event fuer die Chronik setzen

Wenn du den gefundenen Treffer zusaetzlich manuell als Event markieren willst:

```text
event emit "MANUAL_ARCH_RESONANCE" "Initialer RSS-Resonanztreffer"
```

Oder mit Bezug auf den letzten Treffer:

```text
py match = flow.state.get("last_match") or {}
event emit "MANUAL_ARCH_RESONANCE" "RSS resonance stored in reports directory"
```

## 9. Ergebnis

Mit diesem Ablauf nutzt du Nova-shell so:

- RSS-Feeds werden ueber `INDUSTRY_FEEDS` eingebunden.
- [watch_the_big_players.ns](/d:/Nova-shell/watch_the_big_players.ns) uebernimmt Scanning, Atheria-Analyse und Resonanzentscheidung.
- Der Treffer landet in `flow.state`.
- Danach schreibst du denselben Treffer ohne Zusatztooling direkt aus Nova-shell nach TXT und HTML.

Das ist der einfachste produktive Pfad, um aus dem vorhandenen RSS-/Atheria-/NovaScript-Stack einen realen Monitoring-Report zu erzeugen.

## 10. Zweiter RSS-Sensor: `TrendRadar`

Der erste Sensor ist ein Resonanz-/Fruehwarnpfad fuer "passt das strukturell zu Nova-shell?".

Der zweite Sensor [trend_rss_sensor.py](/d:/Nova-shell/trend_rss_sensor.py) ist anders:

- er speichert eine lokale Historie
- er lernt eine Baseline
- er berechnet Deltas gegen fruehere Runs
- er erzeugt einen Forecast

Wichtige Felder aus dem zweiten Sensor:

- `metadata.forecast_direction`
- `metadata.forecast_score`
- `metadata.confidence`
- `metadata.history_length`
- `metadata.baseline`
- `metadata.deltas`

## 11. Umgebungsvariablen fuer den zweiten Sensor setzen

Der zweite Sensor nutzt dieselben RSS-Feeds, bekommt aber zusaetzlich einen persistenten State:

```text
cd D:\Nova-shell
py os.environ["INDUSTRY_FEEDS"] = "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml,https://feeds.feedburner.com/TechCrunch/,https://news.google.com/rss/search?q=AI+infrastructure+agent+runtime"
py os.environ["INDUSTRY_TREND_STATE"] = r"D:\Nova-shell\trend_state.json"
```

Erklaerung:

- `INDUSTRY_FEEDS` liefert die RSS-/Atom-Quellen
- `INDUSTRY_TREND_STATE` speichert den Lernzustand des Trend-Sensors zwischen mehreren Runs

## 12. Zweiten Sensor laden

Der Trend-Sensor wird als normales Atheria-Plugin geladen:

```text
atheria sensor load "trend_rss_sensor.py" --name "TrendRadar"
```

Alternativ kannst du den Sensor jetzt auch ueber die Gallery erzeugen. Das ist der neue bevorzugte Pfad, wenn du mit Sensor-Organellen arbeiten willst:

```text
atheria sensor gallery
atheria sensor spawn trend --template TrendRadar --name "TrendRadar"
```

Danach kannst du die Registrierung pruefen:

```text
atheria sensor list
atheria sensor show "TrendRadar"
```

## 13. Ersten Lernlauf ausfuehren

Beim ersten Lauf baut der Sensor seine Ausgangsbasis auf:

```text
atheria sensor run "TrendRadar"
```

Beim ersten Lauf ist die Richtung typischerweise:

```text
warming_baseline
```

Das ist korrekt. Der Sensor kennt zu diesem Zeitpunkt noch keine Historie ausser dem ersten Snapshot.

## 14. Zweiten Lern-/Forecast-Lauf ausfuehren

Fuehre den Sensor danach noch einmal aus:

```text
atheria sensor run "TrendRadar"
```

Jetzt beginnt die echte Trendbewertung. Typische Richtungen sind:

- `emerging_uptrend`
- `stable_watch`
- `cooling`

Wenn du die Entwicklung ueber mehrere Beobachtungen sehen willst, fuehre ihn mehrmals aus:

```text
atheria sensor run "TrendRadar"
atheria sensor run "TrendRadar"
atheria sensor run "TrendRadar"
```

## 15. Forecast direkt im Python-Kontext inspizieren

Der sauberste direkte Weg in Nova-shell ist die Pipeline. `atheria sensor run` liefert ein Objekt, und `py` bekommt dieses Objekt als `_`.

Den letzten Lauf in eine Python-Variable uebernehmen:

```text
atheria sensor run "TrendRadar" | py result = _
```

Danach kannst du den Inhalt bequem lesen:

```text
py result["metadata"]["forecast_direction"]
py result["metadata"]["forecast_score"]
py result["metadata"]["confidence"]
```

Wenn du nur die Richtung schnell sehen willst:

```text
atheria sensor run "TrendRadar" | py _["metadata"]["forecast_direction"]
```

## 16. Trend-Ergebnis als TXT-Datei speichern

Mit dem zweiten Sensor erzeugst du einen Trendbericht als Text:

```text
py import pathlib
atheria sensor run "TrendRadar" | py result = _
py items = result.get("metadata", {}).get("items", [])
py pathlib.Path("reports").mkdir(parents=True, exist_ok=True)
py lines = ["Nova-shell RSS Trend Report", "", f"Direction: {result.get('metadata', {}).get('forecast_direction', '')}", f"Forecast score: {result.get('metadata', {}).get('forecast_score', '')}", f"Confidence: {result.get('metadata', {}).get('confidence', '')}", f"Summary: {result.get('summary', '')}", ""]
py lines.extend([f"- {item.get('title', '')} | {item.get('source', '')} | {item.get('url', '')}" for item in items])
py pathlib.Path("reports/rss_trend_report.txt").write_text("\n".join(lines), encoding="utf-8")
```

Datei:

```text
reports/rss_trend_report.txt
```

## 17. Trend-Ergebnis als HTML-Datei speichern

Jetzt dieselbe Information als HTML:

```text
py import html
py html_rows = "".join([f"<li><a href='{html.escape(item.get('url', ''))}'>{html.escape(item.get('title', ''))}</a><br><small>{html.escape(item.get('source', ''))}</small></li>" for item in items])
py html_doc = f"<html><head><meta charset='utf-8'><title>Nova-shell RSS Trend Report</title></head><body><h1>Nova-shell RSS Trend Report</h1><p><strong>Direction:</strong> {html.escape(str(result.get('metadata', {}).get('forecast_direction', '')))}</p><p><strong>Forecast score:</strong> {html.escape(str(result.get('metadata', {}).get('forecast_score', '')))}</p><p><strong>Confidence:</strong> {html.escape(str(result.get('metadata', {}).get('confidence', '')))}</p><p><strong>Summary:</strong> {html.escape(str(result.get('summary', '')))}</p><h2>Items</h2><ul>{html_rows}</ul></body></html>"
py pathlib.Path("reports/rss_trend_report.html").write_text(html_doc, encoding="utf-8")
```

Datei:

```text
reports/rss_trend_report.html
```

## 18. Vollstaendiger Copy-Paste Ablauf fuer Sensor 2

Wenn du den Trend-Sensor direkt komplett durchlaufen lassen willst:

```text
cd D:\Nova-shell
py os.environ["INDUSTRY_FEEDS"] = "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml,https://feeds.feedburner.com/TechCrunch/,https://news.google.com/rss/search?q=AI+infrastructure+agent+runtime"
py os.environ["INDUSTRY_TREND_STATE"] = r"D:\Nova-shell\trend_state.json"
atheria sensor load "trend_rss_sensor.py" --name "TrendRadar"
atheria sensor run "TrendRadar"
atheria sensor run "TrendRadar" | py result = _
py import pathlib
py import html
py items = result.get("metadata", {}).get("items", [])
py pathlib.Path("reports").mkdir(parents=True, exist_ok=True)
py lines = ["Nova-shell RSS Trend Report", "", f"Direction: {result.get('metadata', {}).get('forecast_direction', '')}", f"Forecast score: {result.get('metadata', {}).get('forecast_score', '')}", f"Confidence: {result.get('metadata', {}).get('confidence', '')}", f"Summary: {result.get('summary', '')}", ""]
py lines.extend([f"- {item.get('title', '')} | {item.get('source', '')} | {item.get('url', '')}" for item in items])
py pathlib.Path("reports/rss_trend_report.txt").write_text("\n".join(lines), encoding="utf-8")
py html_rows = "".join([f"<li><a href='{html.escape(item.get('url', ''))}'>{html.escape(item.get('title', ''))}</a><br><small>{html.escape(item.get('source', ''))}</small></li>" for item in items])
py html_doc = f"<html><head><meta charset='utf-8'><title>Nova-shell RSS Trend Report</title></head><body><h1>Nova-shell RSS Trend Report</h1><p><strong>Direction:</strong> {html.escape(str(result.get('metadata', {}).get('forecast_direction', '')))}</p><p><strong>Forecast score:</strong> {html.escape(str(result.get('metadata', {}).get('forecast_score', '')))}</p><p><strong>Confidence:</strong> {html.escape(str(result.get('metadata', {}).get('confidence', '')))}</p><p><strong>Summary:</strong> {html.escape(str(result.get('summary', '')))}</p><h2>Items</h2><ul>{html_rows}</ul></body></html>"
py pathlib.Path("reports/rss_trend_report.html").write_text(html_doc, encoding="utf-8")
```

## 19. Unterschied zwischen Sensor 1 und Sensor 2

`BigPlayerWatcher` aus [industry_scanner.py](/d:/Nova-shell/industry_scanner.py):

- gut fuer Resonanz- und Architektur-Treffer
- gut fuer den NovaScript-Watch-Pfad
- schreibt relevante Treffer nach `flow.state`

`TrendRadar` aus [trend_rss_sensor.py](/d:/Nova-shell/trend_rss_sensor.py):

- gut fuer wiederholte Beobachtung
- lernt ueber mehrere Runs
- liefert Richtung, Forecast und Confidence
- ist besser fuer Technologie-Radar und Trendbeobachtung

## 20. Praktische Empfehlung

Wenn du beide Sensoren zusammen einsetzen willst:

1. Nutze `watch_the_big_players.ns`, um starke Resonanz-Treffer sofort zu erkennen.
2. Nutze `TrendRadar`, um ueber mehrere Runs einen aufbauenden Trend zu erkennen.
3. Speichere beide Reports:
   - `rss_resonance_report.txt/html`
   - `rss_trend_report.txt/html`

So bekommst du gleichzeitig:

- ein strukturelles Resonanzsignal
- und ein lernendes Trend-/Forecast-Signal

## 21. Neuer Schritt: Guardian auf den Trendbericht anwenden

Mit den aktuellen Implementierungen endet der Ablauf nicht mehr beim Report. Du kannst den Trendbericht jetzt direkt an den Guardian geben.

Zuerst den aktuellen Bestand pruefen:

```text
atheria guardian status
```

Dann Spawn-Empfehlungen aus dem Trendbericht ableiten:

```text
atheria guardian recommend --file reports/rss_trend_report.txt
```

Wenn du zunaechst nur simulieren willst, welche Sensoren empfohlen werden:

```text
atheria guardian spawn-recommended --file reports/rss_trend_report.txt --limit 2 --dry-run
```

Wenn du die empfohlenen Sensor-Organellen wirklich erzeugen willst:

```text
atheria guardian spawn-recommended --file reports/rss_trend_report.txt --limit 2
atheria sensor list
atheria guardian status
```

Typischer Nutzen:

- `TrendRadar` erkennt Verschiebungen
- `guardian recommend` uebersetzt das in konkrete Sensor-Empfehlungen
- `guardian spawn-recommended` erzeugt daraus neue Beobachter im Mesh-/Sensor-Modell

## 22. Neuer Schritt: Evolutionsplan aus dem Trendbericht ableiten

Der zweite neue Pfad ist `atheria evolve`. Damit wird aus dem RSS-Trendbericht nicht nur ein Monitoring-Signal, sondern ein strategischer Eingabekanal fuer Atheria.

Plan erzeugen:

```text
atheria evolve plan --file reports/rss_trend_report.txt
```

Simulation vor der Uebernahme:

```text
atheria evolve simulate --file reports/rss_trend_report.txt
```

Aktuellen Evolutionszustand ansehen:

```text
atheria evolve status
```

Wenn du den letzten Plan bewusst uebernehmen willst:

```text
atheria evolve apply --reason "align to rss technology trend"
atheria evolve status
```

Das ist absichtlich kontrolliert:

- `plan` erzeugt nur eine begrenzte Policy
- `simulate` zeigt die Auswirkung vorab
- `apply` uebernimmt den Plan explizit

## 23. Empfohlener Gesamtablauf nach aktuellem Stand

Fuer `0.8.5` ist dieser Ablauf der praktischste:

```text
cd D:\Nova-shell
py os.environ["INDUSTRY_FEEDS"] = "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml,https://feeds.feedburner.com/TechCrunch/,https://news.google.com/rss/search?q=AI+infrastructure+agent+runtime"
py os.environ["INDUSTRY_TREND_STATE"] = r"D:\Nova-shell\trend_state.json"
py os.environ["NOVA_RESONANCE_THRESHOLD"] = "0.20"
py os.environ["NOVA_SCAN_INTERVAL_SECONDS"] = "1"
py os.environ["NOVA_SCAN_ITERATIONS"] = "1"
ns.run watch_the_big_players.ns
atheria sensor spawn trend --template TrendRadar --name "TrendRadar"
atheria sensor run "TrendRadar"
atheria sensor run "TrendRadar" | py result = _
py import pathlib
py import html
py items = result.get("metadata", {}).get("items", [])
py pathlib.Path("reports").mkdir(parents=True, exist_ok=True)
py lines = ["Nova-shell RSS Trend Report", "", f"Direction: {result.get('metadata', {}).get('forecast_direction', '')}", f"Forecast score: {result.get('metadata', {}).get('forecast_score', '')}", f"Confidence: {result.get('metadata', {}).get('confidence', '')}", f"Summary: {result.get('summary', '')}", ""]
py lines.extend([f"- {item.get('title', '')} | {item.get('source', '')} | {item.get('url', '')}" for item in items])
py pathlib.Path("reports/rss_trend_report.txt").write_text("\\n".join(lines), encoding="utf-8")
atheria guardian recommend --file reports/rss_trend_report.txt
atheria evolve simulate --file reports/rss_trend_report.txt
```

Damit bekommst du in einem einzigen Arbeitsgang:

- Resonanzreport
- Trendreport
- Guardian-Empfehlungen fuer neue Sensoren
- einen simulierten Evolutionsplan fuer Atheria

## 24. Morning Briefing als Ein-Befehl-Workflow

Wenn du den gesamten RSS-/Trend-/Guardian-Pfad nicht mehr manuell zusammensetzen willst, kannst du direkt [morning_briefing.ns](/d:/Nova-shell/morning_briefing.ns) verwenden.

Der produktive Minimalablauf in Nova-shell ist:

```text
cd D:\Nova-shell
py os.environ["INDUSTRY_FEEDS"] = "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml,https://feeds.feedburner.com/TechCrunch/,https://news.google.com/rss/search?q=AI+infrastructure+agent+runtime"
py os.environ["NOVA_BRIEFING_REPORT_DIR"] = r"D:\Nova-shell\reports\morning"
ns.run morning_briefing.ns
```

Dieser Weg erzeugt automatisch:

- `D:\Nova-shell\reports\morning\rss_resonance_report.txt`
- `D:\Nova-shell\reports\morning\rss_resonance_report.html`
- `D:\Nova-shell\reports\morning\rss_trend_report.txt`
- `D:\Nova-shell\reports\morning\rss_trend_report.html`
- `D:\Nova-shell\reports\morning\rss_morning_briefing.txt`
- `D:\Nova-shell\reports\morning\rss_morning_briefing.html`

### 24.1 Morning Briefing per Web-UI

Wenn du den Ablauf nicht per `ns.run`, sondern ueber eine lokale Web-Oberflaeche steuern willst, nutzt du den integrierten `vision`-Server.

Start in Nova-shell:

```text
vision start 8765
```

Dann im Browser:

```text
http://127.0.0.1:8765/briefing
```

Der praktische Ablauf ist jetzt:

1. Thema eingeben
2. optional `Empfohlene Sensoren nach dem Briefing direkt erzeugen` aktivieren
3. optional `Ergebnisse direkt in Atheria und das Vector Memory uebernehmen` aktivieren
4. `Morning Briefing ausfuehren`
5. Reports direkt im Browser lesen oder herunterladen
6. wenn `Auto-Spawn` nicht aktiv war: per Button `Empfohlene Sensoren jetzt erzeugen` nachtraeglich spawnen

### 24.2 Erweiterte Feed-Konfiguration in der Web-UI

Im Bereich `Erweiterte Feed-Konfiguration` findest du das Feld `Eigene Feed-Liste`.

Das Feld ist optional:

- leer: Nova-shell erzeugt automatisch die Standard-Kombination aus NYT Technology, TechCrunch und Google-News-RSS passend zum Thema
- befuellt: Nova-shell nutzt genau die von dir eingetragenen Feeds

Wichtig:

- mehrere Quellen werden kommasepariert eingetragen
- RSS- und Atom-Feeds koennen gemischt werden
- das Feld ueberschreibt die Standard-Feed-Kombination fuer genau diesen Briefing-Run

Beispiel fuer `Eigene Feed-Liste`:

```text
https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml,https://feeds.feedburner.com/TechCrunch/,https://news.google.com/rss/search?q=edge+ai+inference
```

Beispiel fuer einen spezialisierten Infrastruktur-Run:

```text
https://news.google.com/rss/search?q=ai+infrastructure+agent+runtime,https://news.google.com/rss/search?q=edge+ai+deployment,https://feeds.feedburner.com/TechCrunch/
```

Praktisch bedeutet das:

- im Feld `Thema der Trendanalyse` kannst du z. B. `Edge AI` eintragen
- in `Eigene Feed-Liste` kannst du parallel eine sehr gezielte Feed-Auswahl fuer genau dieses Thema setzen
- dadurch steuerst du, wie breit oder wie fokussiert das Morning Briefing scannt

Die Web-UI erzeugt denselben Report-Satz wie `ns.run morning_briefing.ns`:

- `rss_resonance_report.txt`
- `rss_resonance_report.html`
- `rss_trend_report.txt`
- `rss_trend_report.html`
- `rss_morning_briefing.txt`
- `rss_morning_briefing.html`

Zusaetzlich zeigt sie direkt:

- die Morning-Briefing-Zusammenfassung
- Guardian-Empfehlungen fuer neue Sensoren
- erzeugte Sensoren nach Auto-Spawn oder nach manuellem Spawn
- den Trainingsstatus inklusive trainierter Records und erzeugter Memory-Eintraege
- Download-Links fuer alle TXT- und HTML-Dateien

Wenn du statt Live-RSS zuerst lokal mit Beispieldaten testen willst:

```text
cd D:\Nova-shell
py os.environ["INDUSTRY_SCAN_FILE"] = r"D:\Nova-shell\sample_news.json"
py os.environ["NOVA_BRIEFING_REPORT_DIR"] = r"D:\Nova-shell\reports\morning"
py os.environ["INDUSTRY_TREND_STATE"] = r"D:\Nova-shell\reports\morning\trend_state.json"
py os.environ["NOVA_RESONANCE_THRESHOLD"] = "0.35"
ns.run morning_briefing.ns
```

Hinweise:

- `morning_briefing.ns` initialisiert `Atheria`, schreibt Whitepaper und Dokumentation ins Memory und fuehrt `BigPlayerWatcher`, `TrendRadar` und `atheria guardian recommend` in einem Lauf aus.
- Die HTML-Dateien enthalten den Guardian-Output zusaetzlich als HTML-Kommentar.
- In der Briefing-Web-UI kannst du empfohlene Sensoren jetzt entweder direkt per Auto-Spawn erzeugen oder nach dem Run ueber den Button `Empfohlene Sensoren jetzt erzeugen` anlegen.
- Wenn `Ergebnisse direkt in Atheria und das Vector Memory uebernehmen` aktiv ist, trainiert Nova-shell die drei erzeugten TXT-Reports direkt in Atheria und legt sie gleichzeitig als Memory-Eintraege ab.
- Fuer `0.8.13` ist das der schnellste produktive Weg, um morgens direkt HTML- und TXT-Berichte zu erzeugen.
