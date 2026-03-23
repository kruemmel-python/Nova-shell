# Nova Semantics

## Zweck

Diese Seite beschreibt die formale Semantik des deklarativen `.ns`-Kerns von
Nova-shell.

Sie beantwortet drei Fragen:

- Was ist ein Nova-Programm auf AST-Ebene?
- Wie wird daraus ein gerichteter Ausfuehrungsgraph?
- Was bedeutet die Ausfuehrung eines Flows zur Laufzeit?

Die Seite beschreibt den aktuell implementierten Kern, nicht ein
Wunschmodell. Grundlage sind vor allem:

- `nova/parser/ast.py`
- `nova/parser/parser.py`
- `nova/graph/model.py`
- `nova/graph/compiler.py`
- `nova/runtime/runtime.py`

## Geltungsbereich

Die Semantik dieser Seite gilt fuer den deklarativen Runtime-Pfad in `nova/`.

Sie beschreibt insbesondere:

- `import`
- `agent`
- `dataset`
- `tool`
- `service`
- `package`
- `state`
- `system`
- `event`
- `flow`

Nicht alles davon wird gleich stark in den Ausfuehrungsgraphen ueberfuehrt.
`state` und `system` sind zum Beispiel wichtige Laufzeitbausteine, aber keine
eigenen `GraphNode`-Typen.

## 1. Abstract Syntax

Ein geparstes Nova-Programm ist ein `NovaAST`:

```text
NovaAST = [Declaration_1, Declaration_2, ..., Declaration_n]
```

mit folgenden Top-Level-Deklarationen:

```text
Declaration ::=
    ImportDeclaration
  | AgentDeclaration
  | DatasetDeclaration
  | ToolDeclaration
  | ServiceDeclaration
  | PackageDeclaration
  | StateDeclaration
  | SystemDeclaration
  | EventDeclaration
  | FlowDeclaration
```

Ein `flow` enthaelt wiederum eine geordnete Liste von `FlowStep`-Eintraegen:

```text
FlowStep = (operation, arguments, alias?)
```

Praktisch heisst das:

- `operation` ist der erste Token einer Flow-Zeile
- `arguments` sind die restlichen Tokens
- `alias` entsteht ueber `-> alias`

Beispiel:

```ns
flow radar {
  rss.fetch tech_rss -> fresh_news
  researcher summarize tech_rss -> briefing
}
```

wird auf Schritt-Ebene konzeptionell zu:

```text
("rss.fetch", ["tech_rss"], "fresh_news")
("researcher", ["summarize", "tech_rss"], "briefing")
```

## 2. Statische Wohlgeformtheit

Ein `.ns`-Programm ist semantisch sinnvoll, wenn mindestens die folgenden
Bedingungen erfuellt sind.

### 2.1 Referenzen muessen aufloesbar sein

Fuer die Graph-Kompilation gilt:

- ein `event` muss auf existierende `flow`-Namen zeigen
- ein Flow-Schritt, dessen `operation` kein deklarierter `agent` ist, wird als
  `tool` interpretiert
- Argumente, die Dataset-, State- oder Alias-Namen sind, werden als
  referenzierbare Eingaben behandelt

Wenn ein `event` einen unbekannten Flow referenziert, bricht die
Graph-Kompilation mit `GraphCompileError` ab.

### 2.2 Flows muessen azyklisch kompiliert werden koennen

Der Compiler erzeugt einen `ExecutionGraph` und prueft anschliessend dessen
topologische Ordnung.

Formal:

```text
valid(program) => topological_order(compile(program)) exists
```

Wenn die Ordnung nicht existiert, meldet der Compiler einen
`GraphCycleError`.

### 2.3 Flow-Schritte haben eine disambiguierte Rolle

Ein Schritt

```text
op a1 a2 ... ak
```

wird wie folgt interpretiert:

- falls `op` ein deklarierter Agent ist:
  - wenn `a1` ein Dataset- oder State-Name ist, dann ist `action = None` und
    alle Argumente sind Inputs
  - sonst ist `action = a1` und die restlichen Argumente sind Inputs
- andernfalls wird `op` als Tool-Aufruf behandelt

Beispiele:

```ns
researcher tech_rss
```

```text
agent = researcher
action = None
inputs = [tech_rss]
```

```ns
researcher summarize tech_rss
```

```text
agent = researcher
action = summarize
inputs = [tech_rss]
```

## 3. Graph-Semantik

Die Kompilierung bildet ein `NovaAST` auf einen `ExecutionGraph` ab:

```text
compile : NovaAST -> ExecutionGraph
```

### 3.1 Knoten

Der aktuelle Graph kennt diese Knotentypen:

```text
GraphNode ::=
    DatasetNode
  | ToolNode
  | AgentNode
  | ServiceNode
  | PackageNode
  | FlowNode
  | EventNode
```

Top-Level-Ressourcen werden mit `resource = true` angelegt.
Flow-Schritte erzeugen zusaetzliche nicht-top-level Knoten mit
`resource = false`.

### 3.2 Kanten

Eine Kante ist formal:

```text
ExecutionEdge = (source, target, edge_type, label)
```

Der Compiler verwendet vor allem diese Kantentypen:

- `control`
  - fuer die sequentielle Schrittfolge eines Flows
- `data`
  - fuer Dataset- und Alias-Eingaben
- `definition`
  - fuer die Bindung eines Schrittknotens an seine `agent`- oder
    `tool`-Definition
- `trigger`
  - fuer die Bindung eines `event` an einen `flow`

### 3.3 Form eines kompilierten Flows

Ein Flow

```ns
flow lifecycle {
  rss.fetch signals -> snapshot
  strategist assess signals -> proposal
  event.emit verdict_ready proposal
}
```

wird konzeptionell zu einem Teilgraphen:

```text
flow::lifecycle
  -> flow::lifecycle::step::1
  -> flow::lifecycle::step::2
  -> flow::lifecycle::step::3
```

zusaetzlich mit:

- `dataset::signals -> step::1` als `data`
- `agent::strategist -> step::2` als `definition`
- `step::2 -> step::3` indirekt ueber Alias/Data-Nutzung, falls `proposal`
  referenziert wird

Wichtig:

- Autoren schreiben Flow-Schritte linear
- die Runtime arbeitet aber auf einem expliziten DAG-basierten
  `ExecutionGraph`

## 4. Operationale Semantik

Die Laufzeit arbeitet auf einem geladenen `CompiledNovaProgram` und einem
`RuntimeContext`.

Formal:

```text
run(program, flow?) -> (executed_flows, events, context_snapshot)
```

### 4.1 Laden

`load` fuehrt diese Schritte aus:

1. Parse Quelltext zu `NovaAST`
2. Kompiliere `NovaAST` zu `ExecutionGraph`
3. Initialisiere `RuntimeContext`
4. Registriere Ressourcen, Events, Policies, State- und Service-Kontext

### 4.2 Auswahl der Entry-Flows

Wenn `run(..., flow=None)` aufgerufen wird, bestimmt die Runtime die
Start-Flows so:

- zuerst werden alle Flows gesammelt
- dann werden alle Flows entfernt, die an `event`-Deklarationen gebunden sind
- wenn danach noch ungebundene Flows bleiben, werden genau diese gestartet
- sonst werden alle Flows verwendet

Formal:

```text
entry_flows(ast) =
  unbound_flows(ast), falls diese nicht leer sind
  sonst all_flows(ast)
```

### 4.3 Ausfuehrung eines Flows

Die Ausfuehrung eines Flows `f` ist:

```text
execute_flow(f):
  order := topological_order(closure_for_flow(f))
  fuer jeden node in order:
    execute(node)
```

Dabei gilt:

- `closure_for_flow(f)` enthaelt den Flow-Wurzelknoten und alle davon
  erreichbaren Knoten plus benoetigte Vorgaenger
- die resultierende Reihenfolge ist topologisch, also zyklenfrei

### 4.4 Knotenbedeutung

Semantisch verhalten sich die wichtigsten Knoten so:

- `FlowNode(resource=true)`
  - beschreibt die Flow-Definition
  - erzeugt einen `NodeExecutionRecord`, aber keine externe Aktion
- `EventNode(resource=true)`
  - beschreibt einen Triggerpunkt
  - erzeugt einen `NodeExecutionRecord`, fuehrt aber keinen Flow-Schritt aus
- `DatasetNode(resource=true)`
  - repraesentiert eine deklarierte Datenquelle
  - konkrete Datenbeschaffung erfolgt typischerweise erst ueber Tools wie
    `rss.fetch`
- `ToolNode`
  - fuehrt ein Tool lokal oder ueber den Backend-/Mesh-Pfad aus
- `AgentNode`
  - erstellt einen `AgentTask` und uebergibt Inputs aus dem
    `RuntimeContext`

### 4.5 Alias- und Output-Semantik

Wenn ein Agent- oder Tool-Schritt ausgefuehrt wurde, speichert die Runtime:

- das Ergebnis unter `context.outputs[node.node_id]`
- zusaetzlich unter `context.outputs[alias]`, falls der Schritt ein Alias hat

Damit ist ein Alias semantisch eine benannte Referenz auf den Output eines
vorherigen Knotens.

### 4.6 Event-Semantik

`emit(event_name, payload)` erzeugt ein externes Event im Event-Bus.
Gebundene Flows werden dadurch ausgefuehrt.

Formal:

```text
emit(e, p):
  publish_event(e, p)
  fuer jeden an e gebundenen flow f:
    execute_flow(f, trigger_event=e)
```

Die Runtime schuetzt sich dabei gegen direkte Rekursion:
ein Flow, der bereits auf dem Stack liegt, wird nicht erneut durch dasselbe
Event gestartet.

### 4.7 State-Semantik

`state` hat zwei Ebenen:

- deklarativ als `state { ... }`-Ressource
- operational ueber `state.set` und `state.get`

`state.set key value` bedeutet:

- resolve `value` ueber den aktuellen Kontext
- persistiere den Wert im `PersistentStateStore`
- aktualisiere `context.states[key]`
- repliziere den State-Eintrag in den Replikationslog

`state.get key` bedeutet:

- lade den Wert aus dem `PersistentStateStore`, falls vorhanden
- sonst aus dem aktuellen `context.states`
- liefere ihn als Tool-Resultat zurueck

## 5. Effektmodell

Die deklarative Struktur von Nova ist staerker formalisiert als die
Seiteneffekte einzelner Knoten.

Deshalb ist die korrekte Semantik zweistufig:

- **Strukturelle Semantik**: Parser, AST, Graph, topologische Ordnung,
  Event-Bindung, Alias-Aufloesung
- **Effekt-Semantik**: konkrete Wirkung von Agenten, Tools, Backends, Shell,
  externen Diensten und Providern

### 5.1 Deterministische Teile

Bei gleichem Quelltext sind deterministisch:

- Parsing in `NovaAST`
- Graph-Kompilation
- Knotentypisierung
- topologische Ordnung
- Event-zu-Flow-Bindung
- lokale State-Persistenzlogik

### 5.2 Partiell nichtdeterministische Teile

Nicht voll deterministisch sind:

- Agent-Ausgaben ueber externe oder generative Provider
- Tool-Aufrufe mit externen Datenquellen
- Mesh-Dispatch und Remote-Backends
- Zeit, Netzwerk und Umgebungszustand

Formal ist Nova deshalb kein voll rein funktionales System, sondern:

> ein formal beschreibbarer Ausfuehrungsgraph mit expliziten Effektknoten

## 6. Mathematische Sicht auf Flows

Ein Flow kann als partielle Zustandsueberfuehrung aufgefasst werden:

```text
F : RuntimeContext -> RuntimeContext'
```

genauer:

```text
F(ctx) = execute(topological_order(closure(flow)), ctx)
```

Jeder Knoten transformiert dabei lokal einen Kontext:

```text
step_i : ctx_i -> ctx_{i+1}
```

Der gesamte Flow ist die Komposition dieser Uebergaenge:

```text
F = step_n o ... o step_2 o step_1
```

mit der Einschraenkung, dass einzelne `step_i` Effektknoten sein koennen und
damit nicht rein deterministisch sein muessen.

## 7. Konsequenzen fuer Design und Papers

Diese Semantik ist stark genug fuer:

- Architektur-Wiki
- Whitepaper-Argumentation
- Linter- und Validator-Regeln
- kuenftige Graph-Optimierungen
- saubere Trennung von Struktur und Effekt

Die korrekte starke Aussage fuer Nova-shell ist deshalb:

> Nova-shell besitzt eine formal beschreibbare Struktur- und
> Ausfuehrungssemantik fuer deklarative Programme und markiert
> nichtdeterministische Wirkung ueber explizite Effektknoten.

Nicht korrekt waere die staerkere Behauptung:

> alle Nova-Programme sind voll deterministisch

## Verwandte Seiten

- [NovaDecisionSystem](./NovaDecisionSystem.md)
- [DecisionPatterns](./DecisionPatterns.md)
- [nsPatterns](./nsPatterns.md)
- [NovaLanguage](./NovaLanguage.md)
- [NovaRuntime](./NovaRuntime.md)
- [ParserAndASTReference](./ParserAndASTReference.md)
- [ExecutionModel](./ExecutionModel.md)
