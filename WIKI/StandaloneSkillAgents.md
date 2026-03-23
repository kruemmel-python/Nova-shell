# Standalone Skill Agents

## Zweck

Diese Seite beschreibt, wie man aus dem mitgefuehrten `agent-skills-main`-Ordner portable, eigenstaendige `.ns`-Agenten erzeugt.

Wichtig ist die Trennung:

- `agent-skills-main` ist die versionierte Eingabequelle im Repo
- die erzeugten `examples/*_agents.ns` sind das eigentliche Laufzeitartefakt
- zur spaeteren Nutzung wird der Rohordner nicht mehr benoetigt

Das Repo enthaelt `agent-skills-main` fuer die Generierung:

- `skills/<skill>/SKILL.md`
- optional `skills/<skill>/rules/*.md`

Lizenz und Herkunft sind im Repo explizit dokumentiert:

- `agent-skills-main/LICENSE`
- `agent-skills-main/README.md`
- `THIRD_PARTY_NOTICES.md`

## Was erzeugt wird

Nova-shell kann Skill-Buendel in standalone `.ns`-Dateien umformen.

Beispiele:

- `examples\react_best_practices_agents.ns`
- `examples\react_native_skills_agents.ns`
- `examples\composition_patterns_agents.ns`

Dabei gilt:

- jedes Regelset wird in deklarative `agent { ... }`-Bloecke umgesetzt
- bei grossen Regelbuendeln entsteht zusaetzlich ein Router-Agent
- die `.ns`-Datei enthaelt keine Laufzeitabhaengigkeit auf `agent-skills-main`
- nicht portable Upstream-Skills werden standardmaessig uebersprungen

## CLI

### Generator direkt aus der Shell

```powershell
ns.skills build agent-skills-main
```

Optional mit explizitem Zielordner:

```powershell
ns.skills build agent-skills-main .\examples
```

Du kannst auch direkt auf einen bereits geoeffneten `skills`-Ordner zeigen:

```powershell
ns.skills build .\agent-skills-main\skills .\examples
```

Rueckgabe:

- JSON-Manifest der erzeugten Dateien
- Anzahl generierter Skill-Dateien
- Liste der Agentennamen pro Skill
- Liste uebersprungener Skill-Buendel mit Begruendung

### Generator als Python-Skript

```powershell
python scripts\generate_agent_skills_examples.py
```

## Laufzeit

Nach der Erzeugung arbeitest du nur noch mit der `.ns`-Datei:

```powershell
ns.run examples\react_best_practices_agents.ns
agent list
```

Danach sind die Agenten direkt ueber die Shell nutzbar.

Beispiele:

```powershell
agent run react_best_practices_async_parallel "const user = await fetchUser(); const posts = await fetchPosts();"
agent run react_best_practices_router "Ich habe serielle Fetches, grosse Bundles und viele Re-Renders."
```

## Namensschema

Nova-shell exportiert deklarative Agenten aus der geladenen `.ns`-Datei in zwei Formen:

- Kurzname
- qualifizierter Name mit Dateistamm

Beispiel:

- `react_best_practices_async_parallel`
- `react_best_practices_agents.react_best_practices_async_parallel`

Der Kurzname ist fuer die direkte Nutzung gedacht.
Der qualifizierte Name ist hilfreich, wenn mehrere geladene `.ns`-Dateien gleich benannte Agenten enthalten.

## Vollstaendiger Ablauf

```powershell
ns.skills build agent-skills-main .\examples
ns.run .\examples\react_best_practices_agents.ns
agent list
agent run react_best_practices_router "Ich habe serielle Fetches, zu grosse Client-Bundles und unnoetige Re-Renders."
agent run react_best_practices_async_parallel "const user = await fetchUser(); const posts = await fetchPosts();"
```

Erwartung:

- `ns.skills build` schreibt eine standalone `.ns`-Datei pro Skill-Buendel
- `ns.run` laedt diese Agenten in die deklarative Runtime
- `agent list` zeigt die exportierten Agenten direkt in der Shell
- `agent run` funktioniert danach ohne jeden Bezug auf `agent-skills-main`

## Portable vs. nicht portable Skills

Nova-shell generiert standardmaessig nur Skills, die ohne fremde Deploy-Skripte,
fremde CLI-Logik, Service-Tokens oder vendor-spezifische Projektzustandsordner
als lokale Prompt-/Wissensagenten funktionieren.

Aktuell werden deshalb bewusst uebersprungen:

- `deploy-to-vercel`
- `vercel-cli-with-tokens`
- `web-design-guidelines`

Der Grund ist nicht die Lizenz, sondern die Laufzeitwahrheit:

- diese Skills beschreiben operative Vercel-Workflows
- sie verweisen auf `.vercel/`, `VERCEL_TOKEN`, externe Deploy-Skripte oder die Vercel-CLI
- daraus entstuenden sonst `.ns`-Agenten, die nach Nova-shell-Eigenfunktion aussehen, aber in Wahrheit fremde Infrastruktur voraussetzen

Die generierten Nova-shell-Agenten sollen dagegen ohne das Upstream-Projekt und
ohne dessen Vendor-Mechanik als eigenstaendige, ehrliche Laufzeitartefakte
funktionieren.

## Router und Spezialagenten

Bei umfangreichen Skill-Sammlungen erzeugt Nova-shell zwei Ebenen:

1. einen Router-Agenten
2. viele Spezialagenten pro Regel

Beispiel fuer `react-best-practices`:

- Router: `react_best_practices_router`
- Spezialagent: `react_best_practices_async_parallel`

Der Router ordnet freie Anfragen den passenden Spezialagenten zu.
Die Spezialagenten enthalten den jeweils verdichteten Regelkontext direkt im `system_prompt`.

## Empfohlener Projektpfad

Wenn du die Agenten dauerhaft nutzen willst:

1. `agent-skills-main` im Repo als Quelle pflegen
2. `ns.skills build agent-skills-main`
3. die erzeugten `examples/*_agents.ns` pruefen
4. bei Bedarf sowohl den Minimal-Quellordner als auch die erzeugten `.ns`-Dateien committen

So bleibt das Repo leichtgewichtig und die Laufzeitartefakte bleiben trotzdem klar von den Quelldaten getrennt.

## Grenzen

- die Generatorqualitaet haengt von `SKILL.md` und optionalen `rules/*.md`-Dateien ab
- Codebeispiele oder Shell-Skripte aus dem Skill werden nicht als fremde Laufzeitskripte uebernommen
- die erzeugten Agenten sind Wissens- und Prompt-Agenten, keine 1:1-Kopie aller Skill-Automation
- servicegebundene Upstream-Skills koennen bewusst aus der Generierung ausgeschlossen werden

## Verwandte Seiten

- [NovaCLI](./NovaCLI.md)
- [NovaAgents](./NovaAgents.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)
- [StandaloneSkillAgentsForDevelopers](./StandaloneSkillAgentsForDevelopers.md)
- [TutorialStandaloneSkillAgents](./TutorialStandaloneSkillAgents.md)
- [nsCreate](./nsCreate.md)
