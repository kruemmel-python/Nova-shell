# Tutorial Standalone Skill Agents

## Ziel

Dieses Tutorial zeigt, wie aus `agent-skills-main` lokale, eigenstaendige `.ns`-Agenten entstehen und wie man sie direkt in Nova-shell nutzt.

## Voraussetzungen

- Nova-shell ist installiert oder lokal aus dem Repo startbar
- der Ordner `agent-skills-main` liegt im Repo
- `agent list` funktioniert

## Schritt 1: Quellbestand verstehen

Der Skill-Quellordner ist nur Eingabe.

Relevant sind:

- `agent-skills-main/skills/react-best-practices`
- `agent-skills-main/skills/react-native-skills`
- `agent-skills-main/skills/composition-patterns`

Nicht portable Skills werden standardmaessig uebersprungen.

## Schritt 2: Agenten erzeugen

```powershell
ns.skills build agent-skills-main .\examples
```

Erwartung:

- ein JSON-Manifest wird ausgegeben
- `generated` enthaelt die erzeugten Skill-Agenten
- `skipped` enthaelt bewusst ausgeschlossene Skills mit Grund

Typischer portabler Satz:

- `react_best_practices_agents.ns`
- `react_native_skills_agents.ns`
- `composition_patterns_agents.ns`

## Schritt 3: Erzeugte Dateien pruefen

```powershell
dir .\examples\*_agents.ns
```

Erwartung:

- nur portable Bundles liegen dort
- keine Vercel-Deploy-Agenten werden erzeugt

## Schritt 4: Ein Skill-Buendel laden

```powershell
ns.run .\examples\react_best_practices_agents.ns
```

Danach:

```powershell
agent list
```

Erwartung:

- `react_best_practices_router`
- viele Spezialagenten wie `react_best_practices_async_parallel`

## Schritt 5: Router-Agent verwenden

```powershell
agent run react_best_practices_router "Ich habe serielle Fetches, zu grosse Client-Bundles und zu viele Re-Renders."
```

Erwartung:

- der Router nennt die passendsten Spezialagenten
- die Antwort bleibt im Skill-Kontext

## Schritt 6: Spezialagent direkt verwenden

```powershell
agent run react_best_practices_async_parallel "const user = await fetchUser(); const posts = await fetchPosts();"
```

Erwartung:

- der Agent bewertet genau die Regel `async_parallel`
- die Antwort bleibt konkret und code-nah

## Schritt 7: Zweites Bundle laden

```powershell
ns.run .\examples\react_native_skills_agents.ns
agent list
```

Dann zum Beispiel:

```powershell
agent run react_native_skills_ui_pressable "Mein Button reagiert in React Native schlecht auf Touch-Eingaben."
agent run react_native_skills_router "Meine Liste ruckelt, Bilder sind langsam und State-Updates fuehlen sich zu schwer an."
```

## Schritt 8: Composition-Patterns nutzen

```powershell
ns.run .\examples\composition_patterns_agents.ns
agent run composition_patterns_router "Meine React-Komponente hat zu viele Boolean-Props und wird unwartbar."
```

Erwartung:

- der Router verweist auf Compound-Components, State-Lifting oder explicit variants

## Schritt 9: Python-Generator direkt nutzen

Wenn du ausserhalb der Shell pruefen willst:

```powershell
python scripts\generate_agent_skills_examples.py --skills-root .\agent-skills-main\skills --output-dir .\examples
```

Erwartung:

- dieselben portablen Bundles werden erzeugt
- `skipped` ist im JSON sichtbar

## Schritt 10: Ergebnis einordnen

Die erzeugten Agenten sind:

- lokale Prompt-/Wissensagenten
- deklarative `.ns`-Programme
- ohne Laufzeitabhaengigkeit auf `agent-skills-main`

Sie sind bewusst **keine** 1:1-Kopie fremder Vendor-Automation.

## Typische Fehler

### Warum wurde ein Skill nicht erzeugt?

Dann taucht er unter `skipped` auf.
Meist liegt der Grund in:

- externer Vendor-CLI
- Token-/Projektzustand
- Live-Fetch fremder Inhalte

### Warum sehe ich Agenten erst nach `ns.run`?

Weil die `.ns`-Datei zuerst in die deklarative Runtime geladen und dann in die Shell-Agentenwelt exportiert wird.

### Muss `agent-skills-main` spaeter mit ausgeliefert werden?

Nein.
Zur Laufzeit genuegt die erzeugte `.ns`-Datei.

## Verwandte Seiten

- [StandaloneSkillAgents](./StandaloneSkillAgents.md)
- [StandaloneSkillAgentsForDevelopers](./StandaloneSkillAgentsForDevelopers.md)
- [NovaAgents](./NovaAgents.md)
- [Tutorials](./Tutorials.md)
