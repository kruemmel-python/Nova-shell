# Lokaler Multi-Agenten-Cluster Mit LM Studio

Diese Anleitung beschreibt, wie du auf einem einzelnen Rechner einen lokalen Multi-Agenten-Cluster mit `Nova-shell` und `LM Studio` aufsetzt.

Wichtig ist die Begriffsklaerung:

- Ein lokaler Cluster in Nova-shell ist ein logischer Cluster.
- Mehrere Agenteninstanzen teilen sich ein lokales LM-Studio-Backend, gemeinsame Tools, gemeinsames Memory und gemeinsame Planner-Logik.
- Du brauchst dafuer keinen entfernten Mesh-Worker und keinen Cloud-Provider.

Das Ziel ist nicht nur:

`LLM -> Text`

sondern:

`LM Studio -> Planner -> Tool-Graph -> Execution -> Review`

## 1. Zielbild

Ein professioneller lokaler Multi-Agenten-Cluster besteht in Nova-shell typischerweise aus diesen Bausteinen:

- `LM Studio` als lokaler OpenAI-kompatibler Modellserver
- `Nova-shell` als Orchestrator
- `memory` fuer semantische Langzeit-Erinnerung pro Namespace und Projekt
- `tool` fuer schema-basierte, reproduzierbare Aktionen
- `ai plan` fuer Tool-Orchestrierung
- `agent create`, `agent spawn`, `agent message`, `agent workflow`, `agent graph` fuer Rollen und laufende Agenteninstanzen
- `mesh start-worker`, `mesh run`, `mesh stop-worker` fuer echte lokale Worker-Prozesse

Ein sinnvolles Minimal-Setup ist:

- ein Planner
- ein Analyst
- ein Reviewer
- ein lokales Modell in LM Studio
- einige eingebaute oder registrierte Tools

## 2. Architektur

```text
+-------------------+
| LM Studio         |
| http://127.0.0.1  |
| :1234/v1          |
+---------+---------+
          |
          v
+-------------------+
| Nova-shell        |
| Coordinator       |
| ai / tool /       |
| memory / agent    |
+----+--------+-----+
     |        | 
     |        +--------------------------+
     |                                   |
     v                                   v
+------------+                   +---------------+
| Vector     |                   | Tool Catalog  |
| Memory     |                   | Builtin +     |
| memory     |                   | Registered    |
+------------+                   +---------------+
     |
     v
+-----------------------------------------------+
| Agent Runtimes                                |
| analyst_rt | reviewer_rt | operator_rt | ...  |
+-----------------------------------------------+
```

## 3. Voraussetzungen

Du brauchst:

- eine funktionierende `Nova-shell`-Installation
- `LM Studio` mit aktiviertem lokalen API-Server
- ein geladenes lokales Modell in LM Studio
- Schreibrechte in deinem Arbeitsverzeichnis

Pruefe Nova-shell:

```text
doctor
```

Wichtige Felder:

- `ai_provider`
- `ai_model`
- `registered_tools`
- `agent_instances`

## 4. LM Studio Konfigurieren

Nova-shell nutzt fuer `lmstudio` den lokalen OpenAI-kompatiblen Endpoint:

```text
http://127.0.0.1:1234/v1
```

Empfohlener Ablauf in LM Studio:

1. Modell laden
2. Local Server aktivieren
3. Port `1234` bestaetigen oder bewusst aendern
4. Modellnamen merken

Wenn dein Modell langsam startet, setze ein hoeheres Timeout.

## 5. `.env` Fuer Den Cluster

Lege im Arbeitsverzeichnis eine `.env` an:

```env
NOVA_AI_PROVIDER=lmstudio
LM_STUDIO_BASE_URL=http://127.0.0.1:1234/v1
LM_STUDIO_MODEL=local-model
LM_STUDIO_TIMEOUT=300
NOVA_AI_TIMEOUT=300
```

Dann in Nova-shell:

```text
ai env reload
ai use lmstudio local-model
ai providers
ai models lmstudio
doctor
```

Wenn dein Modell anders heisst, ersetze `local-model` durch den echten Namen.

## 6. Arbeitsverzeichnis Vorbereiten

Ein sauberes lokales Cluster lebt in einem eigenen Verzeichnis:

```text
cd d:
md nova_cluster
cd nova_cluster
```

Beispiel-Datensatz erzeugen:

```text
py with open("items.csv","w",encoding="utf-8") as f:
    f.write("id,name,price\n1,Brot,2.50\n2,Kaese,4.20\n3,Apfel,1.10\n")
```

## 7. Builtin-Tools Verstehen

Nova-shell bringt fuer den Planner bereits eingebaute Tools mit:

- `csv_load`
- `table_mean`
- `dataset_summarize`

Das ist wichtig, weil `ai plan` damit nicht erst rohe Shell-Pipelines erfinden muss.

Beispiel:

```text
ai plan "calculate average price in items.csv"
```

Typische Antwort:

```text
tool.call csv_load file=items.csv | tool.call table_mean column=price
```

Direkt ausfuehren:

```text
ai plan --run "calculate average price in items.csv"
```

Mit Re-Planning bei Fehlern:

```text
ai plan --run --retries 2 "calculate average price in items.csv"
```

## 8. Eigene Tools Registrieren

Ein lokaler Cluster wird stark, wenn wiederkehrende Aktionen als Tools registriert werden.

CSV-Zusammenfassung:

```text
tool register summarize_csv --description "summarize a csv file" --schema '{"type":"object","properties":{"file":{"type":"string"}},"required":["file"]}' --pipeline 'ai prompt --file {{file}} "Summarize this dataset"'
```

Tool ausfuehren:

```text
tool.call summarize_csv file=items.csv
```

Ein Tool mit Python-Literal:

```text
tool register greet --description "say hello" --schema '{"type":"object","properties":{"name":{"type":"string"}},"required":["name"]}' --pipeline 'py "Hello " + {{py:name}}'
tool.call greet name=Nova
```

Hilfreiche Diagnose:

```text
tool list
tool show summarize_csv
```

## 9. Langzeit-Memory Fuer Agenten

Mehrere Agenten sollten gemeinsames Kontextwissen nicht nur im Prompt tragen, sondern auch im `memory`.

Beispiele:

```text
memory namespace pricing
memory project q1
memory embed --id pricing-rule "price column stores EUR gross values"
memory embed --id review-rule "reviewer checks missing columns, suspicious outliers and formatting"
memory embed --id audience "final answer should be concise and operational"
memory status
memory search "pricing"
memory list
```

Der Planner kann diese Treffer spaeter als Kontext nutzen.

## 10. Agentenrollen Anlegen

Ein guter lokaler Cluster nutzt klare Rollen statt eines generischen Agenten.

Planner:

```text
agent create planner "Plan the next action for {{input}}" --provider lmstudio --model local-model --system "You create short operational plans."
```

Analyst:

```text
agent create analyst "Analyze {{input}}" --provider lmstudio --model local-model --system "You extract facts, structure, numbers and risks."
```

Reviewer:

```text
agent create reviewer "Review {{input}}" --provider lmstudio --model local-model --system "You critique outputs, find errors and tighten wording."
```

Operator:

```text
agent create operator "Turn this into actionable next steps: {{input}}" --provider lmstudio --model local-model --system "You produce execution-ready instructions."
```

Kontrolle:

```text
agent list
agent show analyst
```

## 11. Laufende Agenteninstanzen Starten

`agent create` speichert die Rolle.

`agent spawn` startet eine laufende Instanz mit eigener History.

```text
agent spawn planner_rt --from planner
agent spawn analyst_rt --from analyst
agent spawn reviewer_rt --from reviewer
agent spawn operator_rt --from operator
```

Danach koennen die Instanzen ueber `agent message` fortlaufend arbeiten:

```text
agent message analyst_rt "prepare a first read of items.csv"
agent message reviewer_rt "review the analyst result for weak assumptions"
```

Das ist der Kern eines lokalen Multi-Agenten-Clusters:

- gleiche LM-Studio-Runtime
- getrennte Rollen
- getrennte Konversationsverlaeufe
- gemeinsames Tool- und Memory-System

## 12. Multi-Agent-Workflow Und Agent-Graph Ausfuehren

Sequentielle Workflow-Kette:

```text
agent workflow --agents analyst,reviewer,operator --input "Create a short decision memo for the product pricing dataset"
```

Was dabei passiert:

1. `analyst` erstellt die erste Fassung
2. `reviewer` prueft diese Fassung
3. `operator` verwandelt das Ergebnis in konkrete Schritte

Das ist die einfachste produktive Cluster-Form fuer lokale Automatisierung.

Wenn du eine feste gerichtete Topologie brauchst, nutze `agent graph`:

```text
agent graph create review_chain --nodes analyst,reviewer,operator
agent graph show review_chain
agent graph run review_chain --input "Create a short decision memo for the product pricing dataset"
```

Praktische Regel:

- `agent workflow` fuer die schnelle lineare Kette
- `agent graph` fuer bewusst modellierte Agent-Topologien

## 13. Planner Plus Workflow Kombinieren

Ein besonders starkes lokales Muster ist:

1. Planner erzeugt Tool-Graph
2. Tool-Graph laeuft
3. Ergebnis geht an Agentenworkflow

Beispiel:

```text
ai plan --run --retries 2 "calculate average price in items.csv"
agent workflow --agents analyst,reviewer --input "Average price result is 2.6 EUR. Write a short pricing assessment."
```

Oder datengetrieben:

```text
tool.call summarize_csv file=items.csv
agent workflow --agents analyst,reviewer,operator --input "Turn the dataset summary into a release note."
```

## 14. Empfohlene Cluster-Topologien

### A. Data Cluster

Geeignet fuer CSV, JSON, Reports.

- `planner`
- `analyst`
- `reviewer`

Empfohlene Tools:

- `csv_load`
- `table_mean`
- `dataset_summarize`
- `summarize_csv`

### B. Content Cluster

Geeignet fuer Briefe, Show Notes, Memos.

- `planner`
- `writer`
- `reviewer`
- `operator`

### C. Ops Cluster

Geeignet fuer Incident-Analyse, Log-Pruefung, To-do-Erzeugung.

- `planner`
- `analyst`
- `operator`

## 15. Beispiel: Voller Lokaler Cluster-Start

```text
cd d:
md nova_cluster
cd nova_cluster

ai env reload
ai use lmstudio local-model

py with open("items.csv","w",encoding="utf-8") as f:
    f.write("id,name,price\n1,Brot,2.50\n2,Kaese,4.20\n3,Apfel,1.10\n")

memory embed --id pricing-rule "price column stores EUR gross values"
memory embed --id review-rule "reviewer checks missing columns and suspicious outliers"

tool register summarize_csv --description "summarize a csv file" --schema '{"type":"object","properties":{"file":{"type":"string"}},"required":["file"]}' --pipeline 'ai prompt --file {{file}} "Summarize this dataset"'

agent create planner "Plan the next action for {{input}}" --provider lmstudio --model local-model
agent create analyst "Analyze {{input}}" --provider lmstudio --model local-model
agent create reviewer "Review {{input}}" --provider lmstudio --model local-model
agent create operator "Turn this into next steps: {{input}}" --provider lmstudio --model local-model

agent spawn planner_rt --from planner
agent spawn analyst_rt --from analyst
agent spawn reviewer_rt --from reviewer
agent spawn operator_rt --from operator

agent graph create review_chain --nodes analyst,reviewer,operator

ai plan "calculate average price in items.csv"
ai plan --run --retries 2 "calculate average price in items.csv"
tool.call summarize_csv file=items.csv
agent workflow --agents analyst,reviewer,operator --input "Average price is 2.6 EUR. Produce a short operational conclusion."
agent graph run review_chain --input "Average price is 2.6 EUR. Produce a short operational conclusion."
```

## 16. Lokale Worker-Nodes Starten

Wenn du den Cluster auch prozessseitig trennen willst, starte lokale Mesh-Worker:

```text
mesh start-worker --caps cpu,py,ai
mesh list
mesh run py py 1 + 1
mesh stop-worker <worker_id>
```

Das ist lokal besonders sinnvoll fuer:

- getrennte Worker-Prozesse
- eigene Logs pro Worker
- dieselbe `mesh`-Steuerlogik spaeter auch ueber mehrere Hosts

## 17. Betrieb Und Beobachtung

Nutzliche Kommandos im lokalen Cluster:

```text
doctor
doctor json
events last
events stats
memory list
tool list
agent list
event history 10
```

Wenn du eine lokale Reaktionskette willst:

```text
event on dataset_ready 'py _.upper()'
event emit dataset_ready items.csv
```

Fuer agentische Event-Workflows solltest du die ausfuehrbare Logik in Tools oder klaren Workflows halten, statt lange Shell-Fragmente direkt in Events zu hinterlegen.

## 18. Performance-Empfehlungen

- Waehle fuer lokale Cluster eher ein schnelles Instruct-Modell als ein maximal grosses Modell.
- Setze `LM_STUDIO_TIMEOUT=300`, wenn erste Antworten zu langsam kommen.
- Halte Agentenrollen knapp und spezialisiert.
- Verwende `tool.call` fuer wiederholbare Operationen.
- Nutze `memory` fuer Regeln, Annahmen und Projektkontext.
- Verwende `ai plan --run --retries 2`, wenn ein Plan automatisch reparierbar sein soll.

## 19. Fehlerbilder Und Loesungen

### `provider 'lmstudio' is not configured`

Loesung:

- `ai env reload`
- `ai use lmstudio <modell>`
- pruefen, ob `.env` im aktuellen Arbeitsverzeichnis liegt

### `ai provider error (lmstudio): timed out`

Loesung:

- Modell in LM Studio vorwaermen
- `LM_STUDIO_TIMEOUT=300` setzen
- `NOVA_AI_TIMEOUT=300` setzen

### `dataset context missing`

Loesung:

- `ai prompt --file items.csv "Summarize this dataset"`
- oder `data load items.csv | ai prompt "Summarize this dataset"`

### `tool not found`

Loesung:

- `tool list`
- Builtins pruefen: `csv_load`, `table_mean`, `dataset_summarize`
- eigenes Tool neu registrieren

### `agent runtime not found`

Loesung:

- zuerst `agent spawn <name> --from <agent>`

### `managed local worker not found`

Loesung:

- `mesh list`
- `worker_id` oder URL aus der Liste uebernehmen
- Worker bei Bedarf mit `mesh start-worker --caps cpu,py,ai` neu starten

## 20. Empfohlener Betriebsstandard

Wenn du Nova-shell lokal als echten Multi-Agenten-Cluster nutzen willst, ist diese Reihenfolge robust:

1. LM Studio starten und Modell laden
2. `.env` im Arbeitsverzeichnis pflegen
3. `ai env reload`
4. `memory namespace` und `memory project` setzen
5. Agentenrollen anlegen
6. Agenteninstanzen spawnen
7. Regeln in `memory` ablegen
8. wiederkehrende Aktionen als `tool` registrieren
9. `ai plan --run --retries 2` fuer datenbezogene Aufgaben verwenden
10. `agent workflow` oder `agent graph` fuer Review- und Freigabeketten einsetzen
11. bei Bedarf lokale Worker mit `mesh start-worker` starten

Damit wird aus Nova-shell ein lokales Agent-System mit klarer Rollenverteilung, reproduzierbaren Tools und echter Ausfuehrung statt blosem Prompting.
