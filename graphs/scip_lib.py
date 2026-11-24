"""Compiler index (L3) in two halves.

to_db(scip, repo, db)       run by each repo's CI: one repo's SCIP index -> a small per-repo database
combine(repo_dbs, out_db)   central store: all per-repo databases -> one, with cross-repo links
linked_group(dbs, symbol)   federated: the same cross-repo link, computed at query time

Linking: SCIP symbols are `<indexer> <manager> <package> <version> <descriptors>`. A repo that uses
another repo's npm package sees it through the *published* files (dist/*.d.mts), while the package's own
repo is indexed from *source* (src/...), so exact symbols never match across that build step. We link a
consumer symbol to the package's home-repo definition with the same package+version, exported name,
module name and kind (link_kind 'by-export-name'); exact matches are measured separately.
"""
import json
import re
import sqlite3
import subprocess
from pathlib import Path

P = Path(__file__).resolve().parents[1]
DEFINITION = 1
SCHEMA = """
  CREATE TABLE IF NOT EXISTS symbols(symbol TEXT PRIMARY KEY, display TEXT, kind TEXT, def_repo TEXT, def_file TEXT, def_line INT);
  CREATE TABLE IF NOT EXISTS refs(symbol TEXT, repo TEXT, file TEXT, line INT, role TEXT, enclosing TEXT);
"""


def parse_range(r):
    return (r[0], r[1], r[0], r[2]) if len(r) == 3 else (r[0], r[1], r[2], r[3])


def short_name(symbol: str) -> str:
    desc = symbol.split(" ", 4)[-1] if symbol.count(" ") >= 4 else symbol
    names = [a or b for a, b in re.findall(r"`([^`]+)`|([\w$]+)[#.():/\[\]!]", desc) if (a or b)]
    return names[-1] if names else desc


def package_of(symbol: str):
    p = symbol.split(" ")
    return (p[1], p[2], p[3]) if len(p) >= 5 else None


def sig(symbol: str):
    desc = symbol.split(" ", 4)[-1]
    mods = re.findall(r"`([^`]+\.(?:d\.mts|d\.ts|mts|ts|tsx|js|py))`", desc)
    stem = re.sub(r"\.(d\.mts|d\.ts|mts|ts|tsx|js|py)$", "", mods[-1]) if mods else ""
    tail = desc.rstrip()
    return stem, ("method" if tail.endswith(").") else ("type" if tail.endswith("#") else "term"))


def to_db(scip_path: Path, repo: str, db_path: Path) -> dict:
    db_path = Path(db_path)
    if db_path.exists():
        db_path.unlink()
    out = subprocess.run([str(P / "tools/bin/scip"), "print", "--json", str(scip_path)], stdout=subprocess.PIPE, timeout=1800, check=True)
    idx = json.loads(out.stdout)
    db = sqlite3.connect(db_path); db.executescript(SCHEMA)
    n = 0
    for doc in idx.get("documents", []):
        rel = doc.get("relative_path")
        infos = {s["symbol"]: s for s in doc.get("symbols", [])}
        spans = []
        for o in doc.get("occurrences", []):
            s0 = o.get("symbol", "")
            if not (o.get("symbol_roles", 0) & DEFINITION) or s0.startswith("local ") or not o.get("enclosing_range"):
                continue
            sl, _, el, _ = parse_range(o["enclosing_range"])
            if s0.endswith(").") or (s0.endswith(".") and el > sl):
                spans.append((sl, el, s0))
        for o in doc.get("occurrences", []):
            sym = o.get("symbol", "")
            if not sym or sym.startswith("local "):
                continue
            sl = parse_range(o["range"])[0]
            role = "definition" if o.get("symbol_roles", 0) & DEFINITION else "reference"
            inner = [s for s in spans if s[0] <= sl <= s[1] and s[2] != sym]
            enc = short_name(min(inner, key=lambda s: s[1] - s[0])[2]) if inner else None
            db.execute("INSERT INTO refs VALUES (?,?,?,?,?,?)", (sym, repo, rel, sl + 1, role, enc))
            if role == "definition":
                info = infos.get(sym, {})
                db.execute("INSERT OR REPLACE INTO symbols VALUES (?,?,?,?,?,?)",
                           (sym, info.get("display_name") or short_name(sym), str(info.get("kind", "")), repo, rel, sl + 1))
            else:
                db.execute("INSERT OR IGNORE INTO symbols VALUES (?,?,?,?,?,?)", (sym, short_name(sym), "", None, None, None))
            n += 1
    db.execute("CREATE INDEX IF NOT EXISTS r1 ON refs(symbol)"); db.execute("CREATE INDEX IF NOT EXISTS s1 ON symbols(display)")
    db.commit(); db.close()
    return {"documents": len(idx.get("documents", [])), "occurrences": n}


def _homes(dbs: dict) -> dict:
    """npm package -> repo that defines it."""
    home = {}
    for repo, path in dbs.items():
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        for (sym,) in c.execute("SELECT symbol FROM symbols WHERE def_repo IS NOT NULL LIMIT 50"):
            pk = package_of(sym)
            if pk and pk[0] == "npm":
                home.setdefault(pk, repo)
        c.close()
    return home


def _match(consumer: str, cands):
    exact = [x for x in cands if sig(x) == sig(consumer)]
    kind = [x for x in cands if sig(x)[1] == sig(consumer)[1]]
    return exact or kind or list(cands)


def combine(dbs: dict, out_db: Path) -> dict:
    out_db = Path(out_db)
    if out_db.exists():
        out_db.unlink()
    db = sqlite3.connect(out_db); db.executescript(SCHEMA)
    db.execute("CREATE TABLE links(consumer_symbol TEXT, provider_symbol TEXT, link_kind TEXT)")
    for repo, path in dbs.items():
        db.execute("ATTACH DATABASE ? AS src", (str(path),))
        db.execute("INSERT INTO refs SELECT * FROM src.refs")
        db.execute("INSERT OR REPLACE INTO symbols SELECT * FROM src.symbols WHERE def_repo IS NOT NULL")
        db.execute("INSERT OR IGNORE INTO symbols SELECT * FROM src.symbols")
        db.commit(); db.execute("DETACH DATABASE src")
    db.execute("CREATE INDEX r1 ON refs(symbol)"); db.execute("CREATE INDEX s1 ON symbols(display)")
    home = _homes(dbs)
    providers = {}
    for sym, disp, rp in db.execute("SELECT symbol, display, def_repo FROM symbols WHERE def_repo IS NOT NULL"):
        pk = package_of(sym)
        if pk and home.get(pk) == rp:
            providers.setdefault((pk, disp), []).append(sym)
    n = 0
    for sym, disp in db.execute("SELECT symbol, display FROM symbols WHERE def_repo IS NULL").fetchall():
        pk = package_of(sym)
        if not pk or pk not in home or (pk, disp) not in providers:
            continue
        users = {r for (r,) in db.execute("SELECT DISTINCT repo FROM refs WHERE symbol = ?", (sym,))}
        if not (users - {home[pk]}):
            continue
        for prov in _match(sym, providers[(pk, disp)]):
            db.execute("INSERT INTO links VALUES (?,?,'by-export-name')", (sym, prov)); n += 1
    exact = db.execute("SELECT COUNT(DISTINCT r.symbol) FROM refs r JOIN symbols s ON s.symbol = r.symbol "
                       "WHERE s.def_repo IS NOT NULL AND r.repo != s.def_repo").fetchone()[0]
    db.execute("CREATE INDEX l1 ON links(provider_symbol)"); db.execute("CREATE INDEX l2 ON links(consumer_symbol)")
    db.commit(); db.close()
    return {"links_by_export_name": n, "exact_cross_repo_symbols": exact}


def linked_group(dbs: dict, symbol: str) -> set:
    """Federated: the symbol plus its cross-repo counterparts, computed now from the per-repo databases."""
    group = {symbol}
    pk = package_of(symbol)
    if not pk or pk[0] != "npm":
        return group
    home = _homes(dbs)
    disp = short_name(symbol)
    conns = {r: sqlite3.connect(f"file:{p}?mode=ro", uri=True) for r, p in dbs.items()}
    try:
        h = home.get(pk)
        provs = [s for (s,) in conns[h].execute("SELECT symbol FROM symbols WHERE def_repo IS NOT NULL AND display = ?", (disp,))
                 if package_of(s) == pk] if h else []
        is_provider = symbol in provs
        for r, c in conns.items():
            if r == h:
                continue
            for (s,) in c.execute("SELECT symbol FROM symbols WHERE def_repo IS NULL AND display = ? AND symbol LIKE ?",
                                  (disp, f"% {pk[1]} {pk[2]} %")):
                matched = _match(s, provs)
                if (is_provider and symbol in matched) or (not is_provider and s == symbol):
                    group.add(s); group.update(matched)
    finally:
        for c in conns.values():
            c.close()
    return group
