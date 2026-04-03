# Code Improvement Lifecycle

Dieses Beispiel zeigt, wie Nova-shell Quellcode ueber mehrere Agenten prueft, verbessert und die beste Variante als neue Datei schreibt.
Der gleiche Lifecycle kann auch ein kleines Projektverzeichnis statt nur einer einzelnen Datei verbessern.

## Dateien

- `Code_Improve_Lifecycle.ns`
- `code_improve_runtime_helper.py`
- `code_improvement_request.json`
- `code_improvement_project_request.json`
- `sample_target.py`
- `demo_project/`

## Ablauf

1. `code_improvement_request.json` beschreibt Quelle, Ziel und Randbedingungen.
   Fuer Projektmodus kannst du stattdessen den Inhalt aus `code_improvement_project_request.json` verwenden.
2. `CodeReviewAgent` verdichtet Risiken und Hebel.
3. Drei Spezialisierungen erzeugen komplette neue Dateivarianten oder geaenderte Projektdateien:
   - `RefactorAgent`
   - `ReliabilityAgent`
   - `SimplifyAgent`
4. `SelectorAgent` waehlt die beste Variante.
5. Der Helper schreibt:
   - die neue Projektdatei unter `output_path`
   - einen JSON-Bericht unter `.nova_code_improve/`

## Nutzung

Aktiven AI-Provider setzen, dann den Lifecycle starten:

```powershell
ai use lmstudio <modellname>
ns.run .\examples\code_improvement_ns\Code_Improve_Lifecycle.ns
```

Danach findest du die erzeugte Datei oder das erzeugte Projektverzeichnis unter dem im Request gesetzten `output_path`.

## Projektmodus

Fuer ein Projektverzeichnis kannst du den Request z. B. so auf Projektmodus umstellen:

```json
{
  "source_dir": "demo_project",
  "goal": "Verbessere das kleine Python-Projekt in Bezug auf Robustheit und Wartbarkeit, ohne die beabsichtigten Rueckgabewerte zu brechen.",
  "include": ["**/*.py"],
  "output_path": "generated/demo_project.improved"
}
```

Der Lifecycle schreibt dann ein neues Ausgabeverzeichnis mit der besten Variante der betroffenen Dateien und legt den Bericht weiter unter `.nova_code_improve/` ab.
