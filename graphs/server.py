#!/usr/bin/env python3
"""The toy organisation's shared code services, as one MCP server (stdio).

Environment:
  WORLD         path of the world folder (worlds/<name>): repos/, registry/, central/
  STORE_LAYERS  comma-separated: search, read, l2 (syntax graph), l3 (SCIP), l4 (contract graph)
  STORE_MODE    central (default: linked snapshot) | federated (latest per-repo artefacts, joined per call)
  STORE_LOG     optional: JSON-lines log of every call
Reads only the world folder and tools/. Writes only to its own temp folder (and the log).
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from mcp.server.fastmcp import FastMCP

P = Path(__file__).resolve().parents[1]
ORG = json.loads((P / "org.json").read_text())
REPOS = list(ORG["repos"])
W = Path(os.environ["WORLD"])
R, REG, CEN = W / "repos", W / "registry", W / "central"
LAYERS = {x.strip() for x in os.environ.get("STORE_LAYERS", "").split(",") if x.strip()}
MODE = os.environ.get("STORE_MODE", "central")
LOG = os.environ.get("STORE_LOG")
READ_LIMIT = int(os.environ.get("READ_LIMIT", "0"))   # 0 = unlimited; >0 = max read_file calls per session
_reads = [0]
TMP = Path(tempfile.mkdtemp(prefix="store-", dir=os.environ.get("TMPDIR")))
sys.path.insert(0, str(P / "graphs"))
mcp = FastMCP("org")
_tracked = {}
_seen = []            # every tool output this session: read_file may only open paths found here


def _remember(text: str) -> str:
    _seen.append(text)
    return text


def _log(tool, **kw):
    if LOG:
        with open(LOG, "a") as f:
            f.write(json.dumps({"tool": tool, "mode": MODE, **kw}) + "\n")


def _repo_ok(repo):
    if repo not in REPOS:
        raise ValueError(f"unknown repo '{repo}'. Repos: {', '.join(REPOS)}")


def _tracked_files(repo):
    if repo not in _tracked:
        out = subprocess.run(["git", "-C", str(R / repo), "ls-files", "-z"], stdout=subprocess.PIPE,
                             env={"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0", "PATH": "/usr/bin:/bin"})
        _tracked[repo] = set(out.stdout.decode().split("\0")) - {""}
    return _tracked[repo]


def _artefacts():
    """repo -> folder holding that repo's graph.json / l3.db / contract.json, per the store mode."""
    if MODE == "federated":
        out = {}
        for r in REPOS:
            latest = REG / r / "LATEST"
            if latest.exists():
                out[r] = REG / r / latest.read_text().strip()
        return out
    snap = CEN / (CEN / "CURRENT").read_text().strip()
    return {r: REG / r / v for r, v in json.loads((snap / "manifest.json").read_text())["artefacts"].items()} | {"_snap": snap}


# ----------------------------------------------------------------------------- search / read
if "search" in LAYERS:
    @mcp.tool()
    def search_code(pattern: str, repo: str = "", files_only: bool = False) -> str:
        """Code search over the committed files of every repository in the organisation (regular
        expression, like GitHub code search). Optional: one repo; files_only=True lists matching files."""
        if repo:
            _repo_ok(repo)
        cmd = ["rg", "--no-config", "-n", "--no-heading", "-S", "-e", pattern, "--"] + ([repo] if repo else REPOS)
        out = subprocess.run(cmd, cwd=R, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
        hits = [l for l in out.stdout.splitlines() if l.partition("/")[2].split(":", 1)[0] in _tracked_files(l.partition("/")[0])]
        if files_only:
            hits = sorted({h.split(":", 1)[0] for h in hits})
        _log("search_code", pattern=pattern, repo=repo, total=len(hits))
        return _remember((f"{len(hits)} results\n" + "\n".join(hits[:100])) if hits else "no matches")

if "read" in LAYERS:
    @mcp.tool()
    def read_file(repo: str, path: str) -> str:
        """Open a committed file of any repository in the organisation (like viewing it on the code host).
        Only files that an earlier tool result mentioned can be opened."""
        _repo_ok(repo)
        if READ_LIMIT and _reads[0] >= READ_LIMIT:
            _log("read_file", repo=repo, path=path, refused="read limit reached")
            return f"refused: the limit of {READ_LIMIT} opened file(s) per session is reached"
        if not any(path.lstrip("./") in t for t in _seen):
            _log("read_file", repo=repo, path=path, refused="path not found in any earlier tool result")
            return f"refused: {path} was not returned by any earlier tool call; find it with the other tools first"
        root = (R / repo).resolve(); f = (root / path).resolve()
        rel = str(f.relative_to(root)) if str(f).startswith(str(root) + "/") else None
        _log("read_file", repo=repo, path=path, resolved=rel)
        if rel is None or rel not in _tracked_files(repo) or not f.is_file():
            return f"no such committed file: {repo}/{path}"
        _reads[0] += 1
        return f"{repo}/{rel}\n" + "\n".join(f"{i}\t{l}" for i, l in enumerate(f.read_text().splitlines(), 1))


# ----------------------------------------------------------------------------- l2 syntax graph
if "l2" in LAYERS:
    def _graphify(*args):
        arts = _artefacts()
        graphs = [(r, arts[r] / "graph.json") for r in REPOS if r in arts and (arts[r] / "graph.json").exists()] \
            if MODE == "federated" else [("all", arts["_snap"] / "l2/graph.json")]
        outs = []
        for label, g in graphs:
            d = TMP / f"g-{label}"; d.mkdir(exist_ok=True)
            if not (d / "graph.json").exists():
                shutil.copy(g, d / "graph.json")
            out = subprocess.run([str(P / "tools/.venv/bin/graphify"), *args, "--graph", str(d / "graph.json")], cwd=R,
                                 env=dict(os.environ, GRAPHIFY_OUT=str(d), GRAPHIFY_NO_TIPS="1"),
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)
            outs.append(out.stdout.strip() if label == "all" else f"[{label}]\n{out.stdout.strip()}")
        _log("graphify", args=list(args))
        return _remember("\n\n".join(outs)[:20000] or "no graph")

    @mcp.tool()
    def graph_explain(symbol: str) -> str:
        """Syntax code graph of every repository (tree-sitter): one symbol and all its connections
        (callers, callees, imports, containment) with file:line. Ambiguous names list the candidates."""
        return _graphify("explain", symbol, "--all")

    @mcp.tool()
    def graph_callers(symbol: str) -> str:
        """Syntax code graph of every repository (tree-sitter): only who calls one symbol, with file:line."""
        txt = _graphify("explain", symbol, "--all")
        keep = [l for l in txt.splitlines() if ("[calls]" in l and "<--" in l) or not l.startswith("  ")]
        return _remember("\n".join(keep))

    @mcp.tool()
    def graph_path(source: str, target: str) -> str:
        """Syntax code graph of every repository (tree-sitter): the shortest chain of connections between two symbols."""
        return _graphify("path", source, target)


# ----------------------------------------------------------------------------- l3 compiler index
if "l3" in LAYERS:
    import scip_lib

    def _l3_dbs():
        arts = _artefacts()
        if MODE == "federated":
            return {r: arts[r] / "l3.db" for r in REPOS if r in arts and (arts[r] / "l3.db").exists()}
        return {"all": arts["_snap"] / "l3/scip.db"}

    def _q(db, sql, args=()):
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            return c.execute(sql, args).fetchall()
        finally:
            c.close()

    @mcp.tool()
    def scip_symbols(name: str) -> str:
        """Compiler index of every repository (SCIP): symbols with a given name, each with its unique id,
        and its definition file:line. Pass an id to scip_references."""
        _log("scip_symbols", name=name)
        rows = []
        for db in _l3_dbs().values():
            rows += _q(db, "SELECT symbol, def_repo, def_file, def_line FROM symbols WHERE display = ? AND def_repo IS NOT NULL", (name,))
        return _remember("\n".join(f"{s}\n    defined at {r}/{f}:{l}" for s, r, f, l in rows) or "no symbols")

    @mcp.tool()
    def scip_references(symbol: str) -> str:
        """Compiler index of every repository (SCIP): every reference to one symbol id, across repositories,
        with file:line and the enclosing function."""
        _log("scip_references", symbol=symbol)
        dbs = _l3_dbs()
        if MODE == "federated":
            group = scip_lib.linked_group(dbs, symbol)
        else:
            db = dbs["all"]; group = {symbol}
            group |= {c for (c,) in _q(db, "SELECT consumer_symbol FROM links WHERE provider_symbol = ?", (symbol,))}
            for (pv,) in _q(db, "SELECT provider_symbol FROM links WHERE consumer_symbol = ?", (symbol,)):
                group.add(pv); group |= {c for (c,) in _q(db, "SELECT consumer_symbol FROM links WHERE provider_symbol = ?", (pv,))}
        marks = ",".join("?" * len(group)); rows = []
        for db in dbs.values():
            rows += _q(db, f"SELECT repo, file, line, role, enclosing FROM refs WHERE symbol IN ({marks})", tuple(group))
        return _remember("\n".join(f"{r}/{f}:{l}  {role}  in {e or '<module>'}" for r, f, l, role, e in sorted(rows)) or "no references")


# ----------------------------------------------------------------------------- l4 contract graph
if "l4" in LAYERS:
    import contract_lib
    _cache = {}

    def _l4db():
        arts = _artefacts()
        if MODE == "central":
            return arts["_snap"] / "l4/contract.db"
        key = tuple(sorted((r, str(a)) for r, a in arts.items()))
        if key not in _cache:
            db = TMP / f"contract-{len(_cache)}.db"
            contract_lib.link({r: json.loads((a / "contract.json").read_text()) for r, a in arts.items()
                               if (a / "contract.json").exists()}, ORG, db)
            _cache[key] = db
        return _cache[key]

    def _l4(sql, args=()):
        c = sqlite3.connect(f"file:{_l4db()}?mode=ro", uri=True)
        try:
            return c.execute(sql, args).fetchall()
        finally:
            c.close()

    @mcp.tool()
    def contract_field_consumers(type: str, field: str) -> str:
        """API contract graph of every repository: the GraphQL operations that select one backend schema
        field (type, field), with file:line, and where the schema defines it."""
        _log("contract_field_consumers", type=type, field=field)
        d = _l4("SELECT repo, file, line FROM schema_field WHERE type=? AND field=?", (type, field))
        out = [f"schema: {d[0][0]}/{d[0][1]}:{d[0][2]}" if d else f"schema: {type}.{field} not found"]
        rows = _l4("SELECT repo, file, line, def_kind, def_name FROM field_use WHERE type=? AND field=? ORDER BY repo, file, line", (type, field))
        out += [f"{r}/{f}:{l}  selected in {k} {n}" for r, f, l, k, n in rows]
        users = {r for r, *_ in rows}
        out.append("no usage in: " + (", ".join(x for x in REPOS if x not in users and ORG["repos"][x].get("role") != "backend") or "—"))
        return _remember("\n".join(out))

    @mcp.tool()
    def contract_operation(name: str) -> str:
        """API contract graph of every repository: one GraphQL operation by name, with file:line and the
        backend schema fields it selects."""
        _log("contract_operation", name=name)
        out = []
        for r, f, l, k in _l4("SELECT repo, file, line, kind FROM definition WHERE name=?", (name,)):
            out.append(f"{r}/{f}:{l}  {k} {name}")
            out += [f"    {t}.{fl} (line {ln})" for t, fl, ln in _l4("SELECT type, field, line FROM field_use WHERE repo=? AND def_name=?", (r, name))]
        return _remember("\n".join(out) or f"no operation named {name}")

    @mcp.tool()
    def contract_event_subscribers(event: str) -> str:
        """API contract graph of every repository: which repositories register a handler for one backend
        webhook event, with file:line and the handler."""
        _log("contract_event_subscribers", event=event)
        rows = _l4("SELECT repo, file, line, handler FROM webhook_sub WHERE event=? ORDER BY repo", (event,))
        return _remember("\n".join(f"{r}/{f}:{l}  handler {h}" for r, f, l, h in rows) or f"no repository handles {event}")

    @mcp.tool()
    def contract_event_sources(event: str) -> str:
        """API contract graph of every repository: where the backend emits one webhook event, with file:line."""
        _log("contract_event_sources", event=event)
        rows = _l4("SELECT repo, file, line, text FROM event_source WHERE event=? ORDER BY file, line", (event,))
        return _remember("\n".join(f"{r}/{f}:{l}  {t}" for r, f, l, t in rows) or f"the backend never emits {event}")


if __name__ == "__main__":
    mcp.run()
