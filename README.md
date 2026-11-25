# Knowledge graphs on a toy codebase

Four tiny repos (~60 lines of code) built so that each kind of code graph has a question it answers and
questions it fails — with two levels of automatic checks that assert exactly that.
The core demo is a **3x3**: three scenarios (T2, T3, T4), each won by exactly one graph — run `bin/verify --core`.
Scenarios, answers and the latest results: **[SCENARIOS.md](SCENARIOS.md)**. Rules for working on this
project (also for a new Claude session): **[CLAUDE.md](CLAUDE.md)**.

## Quick start

macOS or Linux (on Windows: WSL). You need git, curl and tar (macOS: `xcode-select --install`) and a Claude
Pro or Max subscription. Nothing is installed outside this folder.

    git clone https://github.com/am-consultingai/knowledge-graphs-toy.git
    cd knowledge-graphs-toy
    ./setup.sh                      # tools, Claude sign-in, build, checks (a few minutes), then opens core-3x3.html

`core-3x3.html` is the helper page: what the experiment is, how it is isolated from your own setup, and the two ways
to run it, either end to end (`bin/verify --core` for the 3x3, `bin/verify` for every combination, graded
automatically) or interactively (`bin/session X-G3 T3`: one live Claude session per cell, its command ready to copy).

`./setup.sh --check` shows what is installed or missing; re-running `./setup.sh` only redoes what is missing.
`./setup.sh --clean` removes everything the experiment created, including its Claude token; then delete the folder,
and revoke the token at <https://claude.ai/settings/claude-code> (`--clean` prints which one, by date).

## The three graphs

| Graph | Built by | Knows | Can't |
|---|---|---|---|
| **Syntax graph** | Graphify (tree-sitter), per repo, no build needed | files, functions, calls and imports inside a repo; which files import which package | which function of another repo a call uses |
| **Compiler index** | SCIP (TypeScript compiler / Pyright), per repo, needs a buildable project | exactly which symbol every name refers to — across repos once linked | code that can't be built; links across languages |
| **Contract graph** | our extractor, per repo | which client queries use which API field; who handles which event | anything that isn't a declared API |

## The toy organisation (`toy-src/`)

| Repo | Language | Contents |
|---|---|---|
| `greet-api` | Python | `schema.graphql` (fields `greeting`, `farewell`); resolvers; emits `USER_GREETED` |
| `greet-lib` | TypeScript | npm package `greet-lib` 1.0.0: `hello(name)`, `goodbye(name)` |
| `web-app` | TypeScript | `run()` calls greet-lib's `hello` and its own `render`; 3 more files import greet-lib but use only `goodbye`; `local.ts` defines its OWN `hello` (a trap); `queries.graphql` uses `greeting` |
| `mail-app` | TypeScript | `onEvent("USER_GREETED", sendWelcomeMail)` |

## Worlds (`org.json` → `worlds/`)

Fixed snapshots, each with its own repos (local git), registry of per-repo artefacts, and linked graphs.

| World | Difference |
|---|---|
| `base` | the repos as written |
| `nobuild` | web-app has no package.json / tsconfig → no compiler index |
| `stale` | graphs published first; then web-app adds a `farewell` query without republishing |

## Configurations (`conditions/`)

Each session starts in one repo; other repos are reachable only through the shared `org` tools.
`read_file` opens only files an earlier tool result pointed to; a scenario may also cap how many files can be
opened (T3: 1 — standing in for "too many candidate files to open at scale").

| Configuration | Tools |
|---|---|
| `X-A0` | own repo only |
| `X-A1` | + code search + open files (baseline) |
| `X-G2` | + open files + syntax graph |
| `X-G3` | + open files + compiler index |
| `X-G4` | + open files + contract graph |
| `X-A5` | everything |

## Commands

    ./setup.sh [--check]            fresh clone: install tools, sign in, build, check (re-run safe)
    ./setup.sh --clean              remove tools, worlds, sandbox, run logs and the Claude token
    bin/setup                       build all worlds (repos, packages, per-repo publish, central link)   ~25 s
    bin/check                       level 1: graph tools called directly, both store modes → PASS/FAIL (no model)
    bin/verify --core               level 2, the core 3x3: T2 T3 T4 x syntax / SCIP / contract (27 Haiku runs)
    bin/verify [T3 ...] --reps 3    level 2: Haiku in every configuration, graded vs expected → PASS/FAIL
    bin/session X-G3 T3             live interactive session; sends the question as the first message (--no-ask: paste it yourself)
    bin/session list                configurations and scenarios
    bin/run-question T3 X-G3        one headless run
    bin/make-docs                   regenerate SCENARIOS.md
    bin/make-templates              regenerate the configurations
    bin/deploy-deck                 publish presentation/ to the `presentation` branch (GitHub Pages)

## Presentation

`presentation/` holds a one-hour talk built on this project (`index.html`, design notes in `DESIGN.md`). It is published
with GitHub Pages from the `presentation` branch: https://am-consultingai.github.io/knowledge-graphs-toy/ — after editing
it, commit and run `bin/deploy-deck`. Arrow keys or click to move; `F` for full screen; `?static` in the URL shows every
slide in its final state.

## Setup notes

`./setup.sh` installs everything into `tools/` at the versions pinned in git: Node, uv (which installs Python into
`tools/python/`), ripgrep and scip from `tools/versions.env` (with checksums); the SCIP indexers and TypeScript from
`tools/package-lock.json`; Claude Code from `tools/claude-code/package-lock.json`; the two venvs from
`tools/requirements-*.txt`. To change a version, edit those files and re-run `./setup.sh`. Downloads, installed tools, the
generated `worlds/` and `conditions/*/settings.json` (they hold this clone's path), raw run logs and the `.sandbox/`
runtime are not in git.

Sign-in: `./setup.sh` runs `claude setup-token` (a browser sign-in), asks you to paste the token it prints, saves it
outside the project in `~/.config/claude/temp_creds/knowledge-graphs-toy.env` (a single `CLAUDE_CODE_OAUTH_TOKEN=` line,
readable only by you; override the path with `KG_SECRETS_FILE`) and tests it with one Haiku call. To sign in again,
delete that file and re-run `./setup.sh`. An `ANTHROPIC_API_KEY` in your shell is never passed on.

Everything stays in this folder and runs on the Claude subscription. Results: `results/verify-*.md`,
live sessions in `results/sessions/`, raw logs in `results/raw/`. `.github/workflows/setup.yml` runs `./setup.sh` and
`bin/check` on Linux and macOS (Apple silicon and Intel) on every push, with no token and no model calls.
