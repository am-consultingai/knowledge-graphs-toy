#!/usr/bin/env python3
"""Grade one run's answer against its scenario's answer key.

  harness/grade.py <run-checks.json>   -> prints {"verdict": correct|partial|wrong, "summary": ...}

The grader is Claude Opus 5.5 on the subscription, run through bin/sandbox with NO tools and a fresh
config: it sees only the question, the answer key and the answer.
"""
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

P = Path(__file__).resolve().parent.parent
PROMPT = """Grade an AI agent's answer against an answer key. The key is authoritative: judge only against it,
not against your own knowledge. Follow the key's scoring rule exactly.

<question>
{q}
</question>

<answer_key>
{k}
</answer_key>

<agent_answer>
{a}
</agent_answer>

Reply with ONLY a JSON object: {{"verdict": "correct" | "partial" | "wrong", "summary": "one sentence"}}"""


def grade(checks: dict) -> dict:
    sc = json.loads((P / "scenarios" / f"{checks['scenario']}.json").read_text())
    gid = "grade-" + hashlib.sha1((checks["run_id"] + str(time.time())).encode()).hexdigest()[:12]
    gd = P / ".sandbox/grader" / gid
    rt = P / ".sandbox/r" / gid[-8:]
    for d in (gd / "config", gd / "home", gd / "tmp", rt):
        d.mkdir(parents=True, exist_ok=True)
    cmd = [str(P / "bin/sandbox"), "--secrets", "-e", f"CLAUDE_CONFIG_DIR={gd/'config'}", "-e", f"HOME={gd/'home'}",
           "-e", f"TMPDIR={gd/'tmp'}", "-e", f"CLAUDE_CODE_TMPDIR={gd/'tmp'}", "-e", f"XDG_RUNTIME_DIR={rt}",
           "-e", "ENABLE_CLAUDEAI_MCP_SERVERS=false", "-e", "CLAUDE_CODE_SYNC_SKILLS=0", "--",
           str(P / "tools/bin/claude"), "-p", PROMPT.format(q=sc["question"], k=sc["answer_key"], a=checks["answer"] or "(no answer)"),
           "--model", "claude-opus-5-5", "--effort", "high", "--tools", "", "--max-turns", "1", "--strict-mcp-config",
           "--setting-sources", "user", "--no-session-persistence", "--output-format", "json"]
    out = subprocess.run(cmd, cwd=gd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=600)
    try:
        text = json.loads(out.stdout).get("result", "")
        g = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
        g["verdict"] = g.get("verdict", "wrong").lower()
        return g
    except Exception as e:
        return {"verdict": "error", "summary": f"grader failed: {e}; {out.stderr[-200:]}"}


if __name__ == "__main__":
    print(json.dumps(grade(json.loads(Path(sys.argv[1]).read_text())), indent=1))
