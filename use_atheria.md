# Use Atheria In Nova-shell

`Atheria` ist in Nova-shell eine lokale, trainierbare KI-Runtime. Sie kann direkt als eigener Command genutzt werden oder als aktiver Provider fuer `ai` und `agent`.

## Voraussetzungen

- Der Ordner `Atheria/` ist im Projekt oder im installierten Enterprise-Bundle enthalten.
- Fuer die lokale Atheria-Runtime wird das Enterprise-Profil empfohlen.
- Nach Installation per MSI ist Atheria im Enterprise-Build bereits mit ausgeliefert.

## 1. Verfuegbarkeit pruefen

```text
nova> atheria status
```

Beispielausgabe:

```json
{
  "available": true,
  "source_dir": "C:\\Program Files\\Nova-shell\\Atheria",
  "core_loaded": false,
  "trained_records": 0,
  "categories": []
}
```

Wenn `available` auf `false` steht, wurde der Atheria-Ordner nicht gefunden.

## 2. Atheria initialisieren

```text
nova> atheria init
```

Damit wird `AtheriaCore` geladen und das interne Mesh gebootstrapped.

## 3. Atheria mit Q/A trainieren

Ein einzelnes Wissenspaar einlernen:

```text
nova> atheria train qa --question "What is Nova-shell?" --answer "Nova-shell is a unified compute runtime." --category product
```

Danach suchen:

```text
nova> atheria search "Nova-shell runtime"
```

## 4. Dateien in Atheria einlernen

Textdatei:

```text
nova> atheria train file podcastVideoTranscript_publish_safe.md --category video
```

CSV-Datei:

```text
nova> atheria train csv faq.csv
```

JSON-Datei mit `questions`-Liste:

```text
nova> atheria train json model_with_qa.json
```

Das ist praktisch fuer:

- Produktwissen
- Podcast-Skripte
- Support-FAQ
- projektspezifisches Domänenwissen

## 5. Nova-Memory nach Atheria uebernehmen

Wenn Inhalte bereits im Nova-Vector-Memory liegen:

```text
nova> memory namespace video_production
nova> memory project nova_shell_explainer
nova> memory embed --id final_transcript --file podcastVideoTranscript_publish_safe.md
nova> atheria train memory final_transcript --category video
```

Damit wird aus einem Nova-Memory-Eintrag echtes Atheria-Trainingswissen.

## 6. Direkt mit Atheria chatten

```text
nova> atheria chat "What is Nova-shell?"
```

Mit Dateikontext:

```text
nova> atheria chat --file items.csv "Summarize this dataset"
```

Mit Systemfokus:

```text
nova> atheria chat --system "Answer as a technical architect." "How should Nova-shell use Atheria?"
```

## 7. Atheria als AI-Provider aktivieren

Wenn Atheria der aktive Provider fuer den normalen `ai`-Pfad werden soll:

```text
nova> ai use atheria atheria-core
nova> ai prompt "Explain Nova-shell in one paragraph"
```

Danach laufen `ai prompt` und providerbasierte Agenten ueber Atheria statt ueber OpenAI, LM Studio oder andere Backends.

## 8. Agenten mit Atheria bauen

Einen Agenten direkt auf Atheria setzen:

```text
nova> agent create storyteller "Tell a concise story about {{input}}" --provider atheria --model atheria-core
nova> agent run storyteller "Nova-shell and Atheria"
```

Einen persistenten Agenten-Runtime-Handle starten:

```text
nova> agent spawn storyteller_rt --from storyteller
nova> agent message storyteller_rt "Describe the product vision."
```

## 9. Kontextgesperrte Arbeit mit Atheria-Agenten

Dateikontext direkt an einen Agenten binden:

```text
nova> agent create script_monitor "Use only the locked context. Input: {{input}}" --provider atheria --model atheria-core
nova> agent run script_monitor --file podcastVideoTranscript_publish_safe.md "Gib mir die Einleitung von Sprecher 1."
```

Oder ueber zuvor eingebettetes Memory:

```text
nova> memory embed --id final_transcript --file podcastVideoTranscript_publish_safe.md
nova> agent spawn script_monitor_rt --from script_monitor
nova> agent message script_monitor_rt --memory final_transcript "Gib mir die Einleitung von Sprecher 1."
```

## 10. Typische Workflows

Produktwissen aufbauen:

```text
nova> atheria train qa --question "What problem does Nova-shell solve?" --answer "It unifies compute, orchestration and AI workflows." --category positioning
nova> atheria chat "What problem does Nova-shell solve?"
```

Podcast- oder Video-Skripte absichern:

```text
nova> atheria train file podcastVideoTranscript_publish_safe.md --category script
nova> atheria chat "Summarize the approved explainer script."
```

Datensatz + Erklaerung kombinieren:

```text
nova> atheria train file Whitepaper.md --category whitepaper
nova> atheria chat --file items.csv "Explain this dataset in the style of the whitepaper."
```

## 11. Wichtige Hinweise

- `atheria train ...` speichert Trainingswissen persistent in Nova-shells lokalem Speicher.
- `atheria search ...` sucht in den trainierten Atheria-Daten, nicht im allgemeinen Nova-Memory.
- `memory embed ...` und `atheria train memory ...` sind zwei getrennte Schritte.
- Wenn du exakten Wortlaut brauchst, nutze fuer Agenten zusaetzlich `--file` oder `--memory`.

## 12. Minimaler Schnellstart

```text
nova> atheria status
nova> atheria init
nova> atheria train qa --question "Who are you?" --answer "I am Atheria inside Nova-shell." --category identity
nova> atheria chat "Who are you?"
nova> ai use atheria atheria-core
nova> ai prompt "Describe yourself briefly"
```
