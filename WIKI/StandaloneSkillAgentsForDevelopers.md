# Standalone Skill Agents For Developers

## Zweck

Diese Seite beschreibt die interne Architektur der standalone Skill-Agenten in Nova-shell.
Sie richtet sich an Entwickler, die den Generator verstehen, erweitern oder absichern wollen.

## Was der Generator wirklich tut

Nova-shell uebernimmt keine fremden Skill-Runtimes.
Der Generator liest nur:

- `agent-skills-main/skills/<skill>/SKILL.md`
- optional `agent-skills-main/skills/<skill>/rules/*.md`

und erzeugt daraus deklarative `.ns`-Programme mit lokalen `agent { ... }`-Bloecken.

Wichtig:

- keine fremden `scripts/` werden eingebunden
- keine fremden `resources/` werden ausgefuehrt
- keine Laufzeitabhaengigkeit auf den Quellordner bleibt in der erzeugten `.ns`

## Hauptdateien

### Generatorlogik

- `nova/agents/skill_examples.py`
- `scripts/generate_agent_skills_examples.py`

### Shell-Einstieg

- `nova_shell.py`

### Laufzeitartefakte

- `examples/react_best_practices_agents.ns`
- `examples/react_native_skills_agents.ns`
- `examples/composition_patterns_agents.ns`

## Interne Stufen

### 1. Skill lesen

`read_skill_summary()` liest `SKILL.md`, parst Front Matter und verdichtet den Text.

### 2. Portabilitaet pruefen

`inspect_skills()` bewertet, ob ein Skill als eigenstaendiger Nova-shell-Agent vertretbar ist.

Standardmaessig ausgeschlossen werden Skills, die:

- externe Vendor-CLI-Flows voraussetzen
- Tokens oder servicegebundene Projektzustandsordner benoetigen
- zur Laufzeit Inhalte aus fremden Repositories nachladen

Aktuell als nicht portable markiert:

- `deploy-to-vercel`
- `vercel-cli-with-tokens`
- `web-design-guidelines`

### 3. Agenten erzeugen

`build_skill_program()` erzeugt aus jedem portablen Skill ein `.ns`-Programm.

Dabei gilt:

- Skills mit `rules/*.md` erzeugen viele Spezialagenten
- zusaetzlich entsteht ein Router-Agent
- Skills ohne lokale Regeln erzeugen einen Generalisten

### 4. `.ns` in Shell-Agenten exportieren

Nach:

```powershell
ns.run .\examples\react_best_practices_agents.ns
```

exportiert Nova-shell die deklarativen Agenten direkt in die Shell-Agentenwelt.

Dann funktionieren:

```powershell
agent list
agent run react_best_practices_async_parallel "const user = await fetchUser(); const posts = await fetchPosts();"
```

## Struktur der erzeugten Programme

Jede Datei enthaelt mindestens:

- einen `state`-Block fuer den Skill-Memory-Scope
- einen Router-Agenten bei regelbasierten Skills
- mehrere Spezialagenten mit verdichtetem Regelwissen

Beispielhaftes Muster:

```ns
state react_best_practices_memory {
  backend: atheria
  namespace: react_best_practices
}

agent react_best_practices_router {
  provider: atheria
  model: atheria-core
  memory: react_best_practices_memory
}
```

## Warum der Generator konservativ ist

Der Generator soll keine irrefuehrenden Agenten erzeugen.

Ein Skill wird deshalb nur dann als `.ns`-Agent uebernommen, wenn sein Wissen:

- lokal vorhanden ist
- promptbasiert verdichtet werden kann
- nicht auf externe Tool- oder Serviceketten angewiesen ist

Das ist eine Architekturentscheidung, keine Einschraenkung aus Bequemlichkeit.

## Manifest und Debugging

`ns.skills build` liefert ein JSON-Manifest mit:

- `skills_root`
- `output_dir`
- `generated`
- `skipped`
- `count`

Das ist wichtig fuer Debugging und Governance:

- welche Skills wurden generiert
- welche wurden bewusst ausgelassen
- warum wurden sie ausgelassen

## Erweiterungspunkte

Wenn du neue Skill-Quellen zulaesst, solltest du zuerst entscheiden:

1. Ist das Wissen lokal und selbsterklaerend?
2. Ist es promptbasiert nutzbar?
3. Entsteht ein ehrlicher Nova-shell-Agent oder nur eine Attrappe auf fremde Infrastruktur?

Erst danach sollte ein Skill in die portable Standardgenerierung aufgenommen werden.

## Entwickler-Checkliste

- `SKILL.md` enthaelt genug lokale Information
- `rules/*.md` beschreiben Regeln statt externe Betriebsablaeufe
- keine Abhaengigkeit auf `resources/`, externe Fetches oder Vendor-Logik
- generierte `.ns` enthaelt keinen Pfadverweis auf `agent-skills-main`
- `ns.run` und `agent run` funktionieren danach lokal

## Verwandte Seiten

- [StandaloneSkillAgents](./StandaloneSkillAgents.md)
- [TutorialStandaloneSkillAgents](./TutorialStandaloneSkillAgents.md)
- [NovaAgents](./NovaAgents.md)
- [NovaCLI](./NovaCLI.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)
