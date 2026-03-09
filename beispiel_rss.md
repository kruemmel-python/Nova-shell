# Beispiel: RSS-Feeds mit `watch_the_big_players.ns` ueberwachen und Ergebnisse nach TXT + HTML exportieren

Diese Anleitung zeigt einen vollstaendig kopierbaren Ablauf mit dem vorhandenen Nova-shell-Setup:

- RSS-Feeds ueber `py os.environ["INDUSTRY_FEEDS"] = "..."` setzen
- den vorhandenen Watcher [watch_the_big_players.ns](/d:/Nova-shell/watch_the_big_players.ns) starten
- den letzten Resonanz-Treffer aus `flow.state`
- direkt als Textdatei und HTML-Datei speichern

Die Beispiele basieren auf:

- [watch_the_big_players.ns](/d:/Nova-shell/watch_the_big_players.ns)
- [industry_scanner.py](/d:/Nova-shell/industry_scanner.py)
- [Whitepaper.md](/d:/Nova-shell/Whitepaper.md)
- [Dokumentation.md](/d:/Nova-shell/Dokumentation.md)

## Zielbild

Am Ende hast du lokal zum Beispiel diese Dateien:

- `reports/rss_resonance_report.txt`
- `reports/rss_resonance_report.html`

Die Dateien enthalten:

- den letzten erkannten Treffer
- Score und Zusammenfassung
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
