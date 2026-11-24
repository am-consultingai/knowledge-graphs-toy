# Presentation design: Which code graph answers which question?

About 60 minutes, 14 content slides plus cover, agenda and wrap-up. Each slide's header answers the question that
ends the slide before it; that question is shown at the bottom of every slide.

Recurring visual motifs:

- **Three graphs, three colours, three icons** — syntax graph = parse tree (indigo), compiler index = target (cyan),
  contract graph = plug (green). Used on every slide that mentions a graph.
- **The toy-org map** — the same four repos and their links (import, API, event), first plain, then with the traps
  pinned on it.
- **The question bridge** — every slide ends in the question the next slide's header answers.
- **The 3x3 with a glowing diagonal** — the experiment's expected result: one winner per question.

| # | Section | Header (answers the previous question) | Summary | Next question | Min |
|---|---|---|---|---|---|
| 0 | Cover | Which code graph answers which question? | Knowledge graphs for agents working across repos; toy organisation; live experiment | What will we cover? | 1 |
| A | Agenda | From "why graphs" to a live experiment, in five steps | Why → graph types → toy code → three graphs → experiment | Why do we need knowledge graphs? | 1 |
| 1 | Why | An agent only knows the code it can see; across repos it sees almost nothing | Real questions cross repos; search floods with matches; reading everything doesn't fit in context | What must be prepared in advance? | 3 |
| 2 | Why | A knowledge graph computes relationships ahead of time, so the agent can ask instead of read | Nodes (files, functions, symbols, fields) and edges (calls, imports, references, uses), built per repo and linked | Is this new with AI? | 3 |
| 3 | Why | No: knowledge graphs long predate AI; agents are a new kind of user | Google Knowledge Graph (2012), Wikidata; in code: ctags, IDE indexes, code search; new is who asks | Are all code graphs the same? | 3 |
| 4 | Types | No: three kinds, each from a different source of truth | Syntax (parser), compiler index (type checker / SCIP), contract (declared APIs and events) | What does each one know? | 3 |
| 5 | Types | Each knows one layer: structure, identity or interface | Syntax = shape inside a repo; compiler = exact symbol of each name; contract = who uses which API field or event | Haven't we met these before? | 3 |
| 6 | Types | Yes: you use all three every day | Syntax: outline, ctags, symbol search · Compiler: Go to definition, Find references · Contract: schema registry field usage, Pact, AsyncAPI | Where does each go blind? | 3 |
| 7 | Types | Each graph's blind spot is another's strength | Syntax can't resolve cross-repo calls; compiler needs a build and one language; contract knows no code; all go stale | How can we see this concretely? | 3 |
| 8 | Code | A toy organisation: 4 repos, ~60 lines | greet-api (Python, GraphQL, event) · greet-lib (`hello`, `goodbye`) · web-app (`run()`, query) · mail-app (handler) | Why is it a fair test? | 3 |
| 9 | Code | It contains the traps real codebases have | Name collision, look-alike importers, unbuildable code, cross-language API, stale graph | How do graphs reach the agent? | 3 |
| 10 | Graphs | Through tools: published per repo, linked centrally, served over MCP | One `org` MCP server, tools per graph; text results with `repo/file:line`; agent picks the tools; `read_file` only opens files a tool pointed to | What does each graph contain here? | 4 |
| 11 | Graphs | Syntax: `run() → render()` exists; the `hello` call stops at the package name | 81 nodes, 79 edges; 4 importers point to a dead-end "greet-lib" node; no build needed | Who knows which `hello` is meant? | 4 |
| 12 | Graphs | SCIP: every name resolves to one exact symbol, if the code builds | `main.ts:1` and `:5` → greet-lib `hello`; local `hello` has 0 references; nobuild: web-app has 0 entries | Who links a Python field to a TS query? | 4 |
| 13 | Graphs | Contract: fields and events linked by name across languages, nothing else | Schema field, operation, field use, event source, subscriber; `greeting` ← `queries.graphql:2` | Can an agent show who wins where? | 4 |
| 14 | Experiment | The core 3x3: three questions, three graphs, one winner each | T2 → syntax · T3 → SCIP · T4 → contract; ✓ on the diagonal, ✗ elsewhere | Is the result fair and repeatable? | 5 |
| 15 | Experiment | Each cell is a fresh, isolated Haiku session graded against an answer key | Same question, only the tools differ; 3 runs per cell; Opus grader with no tools; majority verdict | What should you take away? | 5 |
| W | Wrap-up | Choose the graph by the question: structure → syntax, identity → compiler, interface → contract | No single graph is enough; freshness matters as much as type; next: run it live | Let's run it (Q&A) | 3 |
