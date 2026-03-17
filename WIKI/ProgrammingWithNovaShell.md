# Programming With Nova-shell

## Zweck

Diese Seite ist der eigentliche Programmierleitfaden fuer Nova-shell.
Sie beantwortet nicht nur, welche Befehle es gibt, sondern wie man mit Nova-shell arbeitet, wie Programme aufgebaut werden und wie sich CLI, `.ns`-Sprache und Python-API zueinander verhalten.

Wenn jemand nach dem Lesen der Wiki wirklich mit Nova-shell programmieren koennen soll, dann muss diese Seite zusammen mit [NovaCLI](./NovaCLI.md), [NovaLanguage](./NovaLanguage.md), [ShellCommandReference](./ShellCommandReference.md) und [CodeReferenceIndex](./CodeReferenceIndex.md) gelesen werden.

## Die vier Programmierstile

Nova-shell hat vier echte Programmierstile:

- Shell-Kommandos wie `py`, `memory`, `tool`, `mesh`
- Pipelines wie `data load sample.csv | py len(_)`
- deklarative `.ns`-Programme
- Python-Einstiegspunkte ueber `nova/` und `nova_shell.py`

Die wichtigste Regel ist:

- benutze Shell-Kommandos fuer schnelle Arbeit, Admin-Aufgaben und lokale Experimente
- benutze Pipelines fuer kleine Datenfluesse zwischen Kommandos
- benutze `.ns`, wenn du reproduzierbare Flows, Events, Agent-Orchestrierung und Runtime-Zustand brauchst
- benutze Python, wenn du Nova-shell erweitern oder intern integrieren willst

## Mentales Modell

Nova-shell besteht aus zwei Laufzeitpfaden:

```text
CLI/Shell Path
  nova_shell.py
  ->
Kommandorouter
  ->
Engines
  ->
Atheria / Memory / Mesh / Vision / Guard

Declarative Path
  .ns source
  ->
NovaParser
  ->
NovaAST
  ->
NovaGraphCompiler
  ->
NovaRuntime
```

Das ist wichtig fuer die Praxis:

- `memory embed "text"` geht ueber den Shell-Pfad
- `ns.run example.ns` geht ueber Parser, Compiler und Runtime
- beide Pfade teilen sich inhaltlich Konzepte wie Agenten, Events, State und Tool-Ausfuehrung

## Programmieren mit der CLI

### 1. Kleine Ausdruecke

```powershell
py 1 + 1
py {"kind": "nova", "value": 3}
sys echo hello
```

Gut fuer:

- schnelle Berechnungen
- kleine Datentransformationen
- Systemkommandos im Shell-Kontext

### 2. Daten in Memory legen

```powershell
memory namespace docs
memory project intro
memory embed --id intro "Nova-shell orchestrates agents, memory, tools and distributed execution."
memory search "distributed execution"
```

Das ist der typische Weg, um semantische Inhalte nicht nur temporär im Terminal zu halten.

### 3. Ein Tool als wiederverwendbare Funktion bauen

```powershell
tool register greet --description "Greet user" --schema "{\"type\":\"object\",\"properties\":{\"name\":{\"type\":\"string\"}},\"required\":[\"name\"]}" --pipeline "py \"Hello \" + {{py:name}}"
tool call greet name=Nova
tool show greet
```

Nutze diesen Weg statt Copy-Paste, wenn ein Ausdruck mehrfach gebraucht wird.

### 4. Einen Agenten definieren

```powershell
ai providers
agent create helper "Summarize {{input}}" --provider lmstudio --model local-model --system "You are precise."
agent run helper quarterly report
agent show helper
```

Wichtig:
Das funktioniert nur mit einem konfigurierten Provider.

### 5. Lokal verteilt arbeiten

```powershell
mesh start-worker --caps cpu,py
mesh list
mesh run py py 1 + 1
```

### 6. Logik als Blob-Seed kapseln

```powershell
blob pack --text "21 * 2" --type py
blob verify .\calc.nsblob.json
blob exec .\calc.nsblob.json
```

Das ist der richtige Weg, wenn Logik:

- kompakt transportiert
- vor Ausfuehrung verifiziert
- oder ueber Mesh mobil verschoben werden soll

## Programmieren mit Pipelines

Pipelines sind ideal fuer kleine Automationen ohne `.ns`.

### Einfache Pipeline

```powershell
sys echo "nova-shell" | py _.upper()
```

### Strukturierte Daten

```powershell
data load sample.csv | py len(_)
```

Wichtig:
Der Platzhalter `_` ist im Folgeschritt der aktuelle Pipelinewert.

## Programmieren mit `.ns`

`.ns` ist der richtige Pfad fuer:

- wiederholbare Ablaufe
- Event-Trigger
- Agenten- und Tool-Orchestrierung
- Queue, Snapshot, Resume, Replay
- verteilte Ausfuehrung

### Einfaches Beispiel

```ns
system control_plane {
  daemon_autostart: false
}

flow queued_job {
  system.log "queued" -> queue_output
  state.set queue_value queue_output
}

event ping_handler {
  on: ping
  flow: queued_job
}
```

### Praktischer Ablauf

```powershell
@'
system control_plane {
  daemon_autostart: false
}

flow queued_job {
  system.log "queued" -> queue_output
  state.set queue_value queue_output
}

event ping_handler {
  on: ping
  flow: queued_job
}
'@ | Set-Content .\control.ns

ns.graph .\control.ns
ns.run .\control.ns
ns.status
```

### Queue und Events wirklich nutzen

```powershell
ns.control queue enqueue queued_job
ns.control queue run
event emit ping now
ns.control events ping 0 10
```

### Snapshot und Resume

```powershell
ns.snapshot .\control-snapshot.json
ns.resume .\control-snapshot.json
ns.status
```

### Blob-Seeds direkt in `.ns` nutzen

```ns
flow inspect_blob {
  blob.verify "C:/project/workflow.nsblob.json" -> verified
  blob.unpack "C:/project/workflow.nsblob.json" -> unpacked
}

flow execute_blob {
  blob.exec "C:/project/workflow.nsblob.json" -> executed
}
```

## Programmieren mit Python

Die Python-API ist sinnvoll, wenn du:

- Nova-shell in eigene Programme einbetten willst
- Parser, Compiler oder Runtime direkt testen willst
- Toolchain-Funktionen automatisieren willst

### Parser und Runtime direkt benutzen

```python
from nova.parser.parser import NovaParser
from nova.graph.compiler import NovaGraphCompiler
from nova.runtime.runtime import NovaRuntime

source = """
flow hello {
  system.log "hello" -> out
}
"""

parser = NovaParser()
ast = parser.parse(source, source_name="hello.ns")
graph = NovaGraphCompiler().compile(ast)

runtime = NovaRuntime()
runtime.compile(ast)
print(graph.to_dict())
```

### Shell direkt als Objekt benutzen

```python
from nova_shell import NovaShell

shell = NovaShell()
result = shell.route("py 1 + 1")
print(result.output)
```

## Typische Programmiermuster

### Tool statt Copy-Paste

Wenn du denselben Pipelineausdruck mehrfach brauchst, registriere ein Tool statt denselben Ausdruck immer wieder als Einzeiler zu schreiben.

### Memory statt lose Zwischenablage

Wenn Texte oder semantische Ergebnisse wiederverwendet werden sollen, nutze `memory embed` und `memory search` statt nur Shell-Ausgaben.

### `.ns` fuer stabile Ablaufe

Wenn ein Ablauf:

- wiederholt wird
- auf Events reagiert
- einen Zustand braucht
- in Queue oder Scheduler laufen soll

dann gehoert er in `.ns`, nicht nur in eine Shell-Zeile.

### Erst lokal, dann Mesh

Entwickle in dieser Reihenfolge:

1. lokal als Shell-Befehl
2. lokal als Tool oder Flow
3. danach ueber `mesh run` oder `.ns` plus Worker

## Debugging

### Erste Diagnosekommandos

```powershell
doctor
help
tool list
memory status
ai config
mesh list
ns.status
```

### Wenn `cpp.sandbox` oder `wasm` Probleme machen

```powershell
doctor
cpp.sandbox int main(){ return 0; }
```

Erwartung:

- `doctor` zeigt `emcc: ok` und `wasmtime: ok`
- `cpp.sandbox int main(){ return 0; }` liefert `sandbox executed`

### Wenn `ns.graph` geht, aber `ns.run` nicht

Dann ist die Syntax oft schon korrekt und das Problem liegt spaeter in Runtime, Tool, Provider oder Datenpfad.

## Lesepfade

Wenn du mit der CLI programmieren willst:

1. [NovaCLI](./NovaCLI.md)
2. [ShellCommandReference](./ShellCommandReference.md)
3. [ExamplesAndRecipes](./ExamplesAndRecipes.md)
4. [NSBlobGenerator](./NSBlobGenerator.md)

Wenn du `.ns`-Programme schreiben willst:

1. [NovaLanguage](./NovaLanguage.md)
2. [nsCreate](./nsCreate.md)
3. [ParserAndASTReference](./ParserAndASTReference.md)
4. [NovaRuntime](./NovaRuntime.md)

Wenn du die interne API verstehen willst:

1. [ClassReference](./ClassReference.md)
2. [RuntimeMethodReference](./RuntimeMethodReference.md)
3. [NSBlobGenerator](./NSBlobGenerator.md)
3. [CodeReferenceIndex](./CodeReferenceIndex.md)

## Verwandte Seiten

- [NovaCLI](./NovaCLI.md)
- [ShellCommandReference](./ShellCommandReference.md)
- [NovaLanguage](./NovaLanguage.md)
- [nsCreate](./nsCreate.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)
- [ClassReference](./ClassReference.md)
- [CodeReferenceIndex](./CodeReferenceIndex.md)
- [PageTemplate](./PageTemplate.md)
