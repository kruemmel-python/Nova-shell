# FAQ

## Zweck

Die FAQ ist die Kurzfassung fuer wiederkehrende Fragen.
Die eigentliche Projektdokumentation liegt in den Architektur-, Referenz- und Beispielseiten dieser Wiki.

## Schnelle Einstiege

- [Home](./Home.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)
- [ClassReference](./ClassReference.md)
- [RuntimeMethodReference](./RuntimeMethodReference.md)

## Ist Nova-shell nur eine Shell?

Nein. Es ist Shell, Sprache und Runtime-Plattform zugleich.

Mehr dazu:

- [SystemOverview](./SystemOverview.md)
- [Architecture](./Architecture.md)

## Muss ich `.ns` benutzen?

Nein. Die CLI kann auch ohne deklarative Programme genutzt werden.
Fuer reproduzierbare Flows, Services und Agenten ist `.ns` aber der zentrale Pfad.

Mehr dazu:

- [NovaCLI](./NovaCLI.md)
- [NovaLanguage](./NovaLanguage.md)

## Gibt es verteilte Ausfuehrung?

Ja. Ueber Mesh, Worker und standardisierte Executor-Pfade.

Mehr dazu:

- [NovaMesh](./NovaMesh.md)
- [APIReference](./APIReference.md)

## Gibt es eine API?

Ja. Die Runtime kann eine HTTP-Control-Plane-API starten.

Mehr dazu:

- [APIReference](./APIReference.md)
- [RuntimeMethodReference](./RuntimeMethodReference.md)

## Gibt es Tests fuer `.ns`?

Ja. Es existiert ein dedizierter Toolchain-Testpfad.

Mehr dazu:

- [Testing](./Testing.md)
- [DevelopmentGuide](./DevelopmentGuide.md)

## Wo finde ich Klassen und Methoden?

In der Referenzschicht der Wiki:

- [ClassReference](./ClassReference.md)
- [ParserAndASTReference](./ParserAndASTReference.md)
- [RuntimeMethodReference](./RuntimeMethodReference.md)
- [CodeReferenceIndex](./CodeReferenceIndex.md)

## Wie pruefe ich schnell, ob meine Installation gesund ist?

Mit:

```powershell
doctor
```

## Wie beginne ich mit einem ersten echten Ablauf?

Mit:

```powershell
ns.graph examples\market_radar.ns
ns.run examples\market_radar.ns
```

Danach weiter mit:

- [QuickStart](./QuickStart.md)
- [Tutorials](./Tutorials.md)

## Warum funktioniert `ns.graph`, aber `ns.run` nicht?

Dann ist die Syntax meist korrekt und das Problem liegt eher in Runtime, Tool, Provider oder Datenpfad.

Mehr dazu:

- [NovaRuntime](./NovaRuntime.md)
- [Troubleshooting](./Troubleshooting.md)

## Verwandte Seiten

- [QuickStart](./QuickStart.md)
- [Troubleshooting](./Troubleshooting.md)
- [GeneralLinks](./GeneralLinks.md)
