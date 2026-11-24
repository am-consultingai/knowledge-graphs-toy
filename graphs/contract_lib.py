"""Contract (L4) graph in two halves.

extract(repo_dir, repo, org) -> dict   each repo's CI: reads only that repo
link(extracts, org, db_path)            the store (central) or a query (federated): walks every client
                                        GraphQL document against the backend schema; joins events
"""
import re
import sqlite3
from pathlib import Path

SKIP = {"node_modules", ".git", "dist", "__pycache__"}


def _files(root, exts):
    for p in Path(root).rglob("*"):
        if p.is_file() and p.suffix in exts and not (set(p.relative_to(root).parts) & SKIP):
            yield p


def extract(repo_dir, repo, org) -> dict:
    root = Path(repo_dir)
    cfg = org["repos"][repo]
    if cfg.get("role") == "backend":
        events = []
        for p in _files(root, {".py"}):
            for i, line in enumerate(p.read_text().splitlines(), 1):
                for m in re.finditer(org["event_source_regex"], line):
                    events.append([str(p.relative_to(root)), i, m.group(1), line.strip()])
        return {"repo": repo, "kind": "backend", "schema_file": cfg["schema"],
                "schema_sdl": (root / cfg["schema"]).read_text(), "event_sources": events}
    docs = [[str(p.relative_to(root)), 1, p.read_text()] for p in _files(root, {".graphql", ".gql"})]
    hooks = []
    for p in _files(root, {".ts", ".tsx"}):
        for i, line in enumerate(p.read_text().splitlines(), 1):
            for m in re.finditer(org["webhook_regex"], line):
                hooks.append([str(p.relative_to(root)), i, m.group(1), m.group(2)])
    return {"repo": repo, "kind": "client", "documents": docs, "webhooks": hooks}


def link(extracts: dict, org, db_path) -> dict:
    from graphql import TypeInfo, TypeInfoVisitor, Visitor, build_schema, get_named_type, parse, visit
    from graphql.language import FragmentDefinitionNode, OperationDefinitionNode
    db_path = Path(db_path)
    if db_path.exists():
        db_path.unlink()
    db = sqlite3.connect(db_path)
    db.executescript("""
      CREATE TABLE definition(repo TEXT, file TEXT, line INT, kind TEXT, name TEXT);
      CREATE TABLE field_use(repo TEXT, file TEXT, line INT, def_kind TEXT, def_name TEXT, type TEXT, field TEXT, in_schema INT);
      CREATE TABLE schema_field(repo TEXT, file TEXT, type TEXT, field TEXT, line INT);
      CREATE TABLE webhook_sub(repo TEXT, file TEXT, line INT, event TEXT, handler TEXT);
      CREATE TABLE event_source(repo TEXT, file TEXT, line INT, event TEXT, text TEXT);
    """)
    backend = next(e for e in extracts.values() if e.get("kind") == "backend")
    schema = build_schema(backend["schema_sdl"])
    cur = None
    for i, line in enumerate(backend["schema_sdl"].splitlines(), 1):
        m = re.match(r"^(?:type|interface|input)\s+(\w+)", line)
        if m:
            cur = m.group(1); continue
        if line.startswith("}"):
            cur = None; continue
        m = re.match(r"^\s+(\w+)\s*[(:]", line)
        if cur and m:
            db.execute("INSERT INTO schema_field VALUES (?,?,?,?,?)", (backend["repo"], backend["schema_file"], cur, m.group(1), i))
    db.executemany("INSERT INTO event_source VALUES (?,?,?,?,?)", [(backend["repo"], *e) for e in backend["event_sources"]])
    for repo, ex in extracts.items():
        if ex.get("kind") != "client":
            continue
        db.executemany("INSERT INTO webhook_sub VALUES (?,?,?,?,?)", [(repo, *h) for h in ex["webhooks"]])
        for rel, first, src in ex["documents"]:
            try:
                doc = parse(src)
            except Exception:
                continue
            for d in doc.definitions:
                if not isinstance(d, (OperationDefinitionNode, FragmentDefinitionNode)) or not d.name:
                    continue
                kind = d.operation.value if isinstance(d, OperationDefinitionNode) else "fragment"
                db.execute("INSERT INTO definition VALUES (?,?,?,?,?)", (repo, rel, first + d.loc.start_token.line - 1, kind, d.name.value))
                ti, rows = TypeInfo(schema), []

                class V(Visitor):
                    def enter_field(self, node, *_):
                        parent = ti.get_parent_type()
                        rows.append((repo, rel, first + node.loc.start_token.line - 1, kind, d.name.value,
                                     get_named_type(parent).name if parent else "?", node.name.value,
                                     1 if ti.get_field_def() is not None else 0))
                visit(d, TypeInfoVisitor(ti, V()))
                db.executemany("INSERT INTO field_use VALUES (?,?,?,?,?,?,?,?)", rows)
    db.commit(); db.close()
    return {"clients": [r for r, e in extracts.items() if e.get("kind") == "client"]}
