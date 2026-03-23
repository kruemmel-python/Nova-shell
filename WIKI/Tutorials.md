# Tutorials

## Zweck

Diese Seite ist der Einstieg in die gefuehrten Anwendungsbeispiele der Nova-shell-Wiki.
Die Tutorials sollen nicht nur erklaeren, was ein Feature ist, sondern einen nachvollziehbaren Ablauf liefern, den man lokal nachbauen kann.

## Verfuegbare Tutorials

- [TutorialTechnologyRadar](./TutorialTechnologyRadar.md)
- [TutorialMultiAgentCluster](./TutorialMultiAgentCluster.md)
- [TutorialLMStudioIntegration](./TutorialLMStudioIntegration.md)
- [TutorialBlobSeeds](./TutorialBlobSeeds.md)
- [TutorialPredictiveFederatedCoevolution](./TutorialPredictiveFederatedCoevolution.md)
- [TutorialProjectWatchMonitor](./TutorialProjectWatchMonitor.md)
- [TutorialStandaloneSkillAgents](./TutorialStandaloneSkillAgents.md)

## Lernreihenfolge

1. [QuickStart](./QuickStart.md)
2. [NovaCLI](./NovaCLI.md)
3. [NovaLanguage](./NovaLanguage.md)
4. ein konkretes Tutorial

## Was ein gutes Tutorial in dieser Wiki enthaelt

- klares Ziel
- Voraussetzungen
- konkrete Schritte
- testbare Kommandos
- ein sichtbares Ergebnis
- Verweise auf weiterfuehrende Referenzseiten

## Schneller Einstieg

Wenn du nur einen Ablauf probieren willst, beginne mit:

```powershell
doctor
ns.graph examples\market_radar.ns
ns.run examples\market_radar.ns
```

Danach kannst du tiefer in die Tutorials fuer Cluster- oder lokale Modellpfade gehen.

Wenn du ein echtes Projekt live beobachten willst, ist dies der direkteste Einstieg:

```powershell
cd F:\DeCoG-TRI
ns.run nova_project_monitor.ns
```

Dazu passend:

- [TutorialProjectWatchMonitor](./TutorialProjectWatchMonitor.md)
- [WatchMonitor](./WatchMonitor.md)

Wenn du Logik kompakt kapseln, verifizieren und zwischen Nodes bewegen willst, beginne hier:

- [TutorialBlobSeeds](./TutorialBlobSeeds.md)

Wenn du die neuen Plattformfunktionen als zusammenhaengenden Forecast-, Mesh- und Evolutionspfad ausprobieren willst, nimm dieses Tutorial:

- [TutorialPredictiveFederatedCoevolution](./TutorialPredictiveFederatedCoevolution.md)

Wenn du portable `.ns`-Agenten aus dem mitgefuehrten Skill-Quellbestand erzeugen und direkt in Nova-shell nutzen willst, beginne hier:

- [TutorialStandaloneSkillAgents](./TutorialStandaloneSkillAgents.md)

## Verwandte Seiten

- [ExamplesAndRecipes](./ExamplesAndRecipes.md)
- [NovaCLI](./NovaCLI.md)
- [ProgrammingWithNovaShell](./ProgrammingWithNovaShell.md)
- [WatchMonitor](./WatchMonitor.md)
- [TutorialBlobSeeds](./TutorialBlobSeeds.md)
- [TutorialPredictiveFederatedCoevolution](./TutorialPredictiveFederatedCoevolution.md)
- [TutorialStandaloneSkillAgents](./TutorialStandaloneSkillAgents.md)
