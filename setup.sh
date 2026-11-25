#!/usr/bin/env bash
# One-step setup for a fresh clone (macOS or Linux, incl. WSL). Safe to re-run: finished steps are skipped.
#
#   ./setup.sh               install tools into tools/, sign in to Claude, build the worlds, run the checks
#   ./setup.sh --check       only report what is installed / missing (changes nothing)
#   ./setup.sh --no-login    skip the Claude sign-in (e.g. CI; bin/check needs no model)
#   ./setup.sh --no-build    skip bin/setup + bin/check at the end
#   ./setup.sh --no-open     don't open core-3x3.html (the helper page) at the end
#   ./setup.sh --clean       remove everything the experiment created, including the Claude token (asks first;
#                            add --yes to skip the question). Afterwards you can delete the folder itself.
#
# Everything is installed inside this folder (tools/, .sandbox/). The only file written outside it is the
# Claude subscription token: ~/.config/claude/temp_creds/knowledge-graphs-toy.env (override: KG_SECRETS_FILE).
# Needs only git, curl and tar (macOS: the Xcode Command Line Tools). Written for bash 3.2 (macOS's /bin/bash).
set -euo pipefail

P="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$P/tools"
DL="$T/.downloads"
SB="$P/bin/sandbox"

CHECK=false; LOGIN=true; BUILD=true; OPEN=true; CLEAN=false; YES=false
for a in "$@"; do
  case "$a" in
    --check) CHECK=true ;;
    --no-login) LOGIN=false ;;
    --no-build) BUILD=false ;;
    --no-open) OPEN=false ;;
    --clean) CLEAN=true ;;
    --yes|-y) YES=true ;;
    -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $a (see ./setup.sh --help)" >&2; exit 2 ;;
  esac
done

if [ -t 1 ]; then B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; N=$'\033[0m'; else B=; G=; Y=; R=; N=; fi
step() { printf '\n%s== %s%s\n' "$B" "$*" "$N"; }
ok()   { printf '  %sok%s    %s\n' "$G" "$N" "$*"; }
todo() { printf '  %stodo%s  %s\n' "$Y" "$N" "$*"; MISSING=$((MISSING + 1)); }
die()  { printf '\n%sERROR:%s %s\n' "$R" "$N" "$*" >&2; exit 1; }
MISSING=0

# ---------------------------------------------------------------- platform
case "$(uname -s)" in
  Darwin) OS=darwin ;;
  Linux)  OS=linux ;;
  *) die "unsupported system $(uname -s): this project runs on macOS or Linux (on Windows, use WSL)" ;;
esac
ARCH="$(uname -m)"
# A Mac with Apple silicon reports x86_64 inside a Rosetta terminal: still install the native arm64 tools.
if [ "$OS" = darwin ] && [ "$(sysctl -n hw.optional.arm64 2>/dev/null || echo 0)" = 1 ]; then ARCH=arm64; fi
case "$ARCH" in
  arm64|aarch64) ARCH=arm64 ;;
  x86_64|amd64)  ARCH=x64 ;;
  *) die "unsupported CPU $ARCH (supported: arm64, x86_64)" ;;
esac
PLAT="${OS}_${ARCH}"
case "$PLAT" in
  darwin_arm64) NODE_P=darwin-arm64; UV_P=aarch64-apple-darwin;      RG_P=aarch64-apple-darwin;      SCIP_P=darwin-arm64 ;;
  darwin_x64)   NODE_P=darwin-x64;   UV_P=x86_64-apple-darwin;       RG_P=x86_64-apple-darwin;       SCIP_P=darwin-amd64 ;;
  linux_arm64)  NODE_P=linux-arm64;  UV_P=aarch64-unknown-linux-gnu; RG_P=aarch64-unknown-linux-gnu; SCIP_P=linux-arm64 ;;
  linux_x64)    NODE_P=linux-x64;    UV_P=x86_64-unknown-linux-gnu;  RG_P=x86_64-unknown-linux-musl;  SCIP_P=linux-amd64 ;;
esac

# shellcheck source=tools/versions.env
. "$T/versions.env"
sha_var() { eval "printf '%s' \"\${${1}_SHA256_${PLAT}:-}\""; }

REAL_HOME="$(eval echo "~$(id -un)")"
SECRETS="${KG_SECRETS_FILE:-$REAL_HOME/.config/claude/temp_creds/knowledge-graphs-toy.env}"
pretty() { case "$1" in "$REAL_HOME"/*) printf '~/%s' "${1#"$REAL_HOME"/}" ;; *) printf '%s' "$1" ;; esac; }

# ---------------------------------------------------------------- --clean
if $CLEAN; then
  # Everything the experiment created. Kept: the files in git (sources, pins, results/verify-*.md|json summaries).
  targets=()
  for rel in tools/bin tools/node tools/python tools/.pkg tools/.downloads tools/node_modules tools/claude-code/node_modules \
             tools/.venv tools/.venv-store worlds .sandbox results/raw results/sessions \
             bin/__pycache__ graphs/__pycache__ harness/__pycache__ \
             conditions/X-A0/settings.json conditions/X-A1/settings.json conditions/X-A5/settings.json \
             conditions/X-G2/settings.json conditions/X-G3/settings.json conditions/X-G4/settings.json; do
    if [ -e "$P/$rel" ] || [ -L "$P/$rel" ]; then targets+=("$P/$rel"); fi
  done
  step "clean: remove the experiment's tools, worlds, sandbox, run logs and Claude token"
  if [ ${#targets[@]} -eq 0 ] && [ ! -f "$SECRETS" ]; then echo "  nothing to remove"; exit 0; fi
  for t in ${targets[@]+"${targets[@]}"}; do printf '  %-44s %s\n' "${t#$P/}" "$(du -sh "$t" 2>/dev/null | cut -f1)"; done
  if [ -f "$SECRETS" ]; then printf '  %-44s %s\n' "$(pretty "$SECRETS")" "(the Claude token for this experiment)"; fi
  echo "  kept: everything in git, incl. results/verify-*.md|json"
  if ! $YES; then
    [ -t 0 ] || die "--clean needs a terminal to confirm, or add --yes"
    read -r -p "  Remove all of the above? [y/N] " ans
    case "$ans" in y|Y|yes|YES) ;; *) echo "  nothing removed"; exit 0 ;; esac
  fi
  for t in ${targets[@]+"${targets[@]}"}; do chmod -R u+w "$t" 2>/dev/null || true; rm -rf "$t"; done
  had_token=false; token_date=""
  if [ -f "$SECRETS" ]; then
    had_token=true
    token_date="$(date -r "$SECRETS" '+%Y-%m-%d %H:%M' 2>/dev/null || true)"   # when setup.sh saved it (GNU and BSD date)
    rm -f "$SECRETS"
    rmdir "$(dirname "$SECRETS")" 2>/dev/null || true   # temp_creds/, only if now empty
  fi
  ok "removed. Nothing of the experiment is left outside this folder; you can now delete the folder too."
  if $had_token; then
    cat <<EOF

  ${Y}${B}One more step: revoke the token.${N} Deleting the file removes it from this machine, but the token
  itself stays valid on your Claude account (for up to a year) until you revoke it:

    1. Open  https://claude.ai/settings/claude-code  (signed in to the same account)
    2. Under the Claude Code authorization tokens, revoke the one created ${token_date:-when you ran ./setup.sh}
       (tokens from 'claude setup-token' have no name; match them by date).
EOF
  fi
  exit 0
fi

# ---------------------------------------------------------------- helpers
sha256() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }
file_sha() { [ -f "$1" ] && sha256 "$1" || echo none; }
stamp_ok() { [ -f "$1/.kg-stamp" ] && [ "$(cat "$1/.kg-stamp")" = "$2" ]; }   # dir, expected content
stamp()    { printf '%s' "$2" > "$1/.kg-stamp"; }

# fetch <url> <sha256> → path of the verified download (cached in tools/.downloads)
fetch() {
  local url="$1" want="$2" f
  f="$DL/$(basename "$url")"
  mkdir -p "$DL"
  if [ ! -f "$f" ] || [ "$(sha256 "$f")" != "$want" ]; then
    echo "  downloading $(basename "$url")" >&2
    curl -fSL --retry 3 --progress-bar -o "$f.part" "$url" || die "download failed: $url"
    mv "$f.part" "$f"
  fi
  [ "$(sha256 "$f")" = "$want" ] || { rm -f "$f"; die "checksum mismatch for $(basename "$url") (see tools/versions.env)"; }
  printf '%s' "$f"
}

# unpack <archive> <dest dir> <strip components>
unpack() { rm -rf "$2"; mkdir -p "$2"; tar -xzf "$1" -C "$2" --strip-components="$3"; }

# ---------------------------------------------------------------- 1. prerequisites
step "1/6 prerequisites ($OS $ARCH)"
if [ "$OS" = darwin ] && ! xcode-select -p >/dev/null 2>&1; then
  die "the Xcode Command Line Tools are missing (they provide git). Run:  xcode-select --install  then re-run ./setup.sh"
fi
for c in git curl tar; do
  command -v "$c" >/dev/null 2>&1 || die "'$c' is missing. Install it (Debian/Ubuntu: sudo apt install $c) and re-run."
done
command -v sha256sum >/dev/null 2>&1 || command -v shasum >/dev/null 2>&1 || die "need sha256sum or shasum"
ok "git, curl, tar"
if [ -n "${ANTHROPIC_API_KEY:-}${ANTHROPIC_AUTH_TOKEN:-}" ]; then
  printf '  %snote%s  an Anthropic API key is set in your shell; it is ignored here (bin/sandbox never passes it on: subscription only)\n' "$Y" "$N"
fi

# ---------------------------------------------------------------- 2. tools
step "2/6 tools (into tools/)"
mkdir -p "$T/bin"

# Node.js
want="node $NODE_VERSION $NODE_P"
if stamp_ok "$T/node" "$want" && [ -x "$T/node/bin/node" ]; then ok "$want"
elif $CHECK; then todo "$want"
else
  f="$(fetch "https://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-$NODE_P.tar.gz" "$(sha_var NODE)")"
  unpack "$f" "$T/node" 1; stamp "$T/node" "$want"; ok "$want"
fi
if ! $CHECK; then for b in node npm npx; do ln -sfn "../node/bin/$b" "$T/bin/$b"; done; fi

# uv (installs Python), ripgrep, scip: single binaries
install_bin() {  # name version url sha strip binary-path-in-archive...
  local name="$1" ver="$2" url="$3" sha="$4" strip="$5"; shift 5
  local d="$T/.pkg/$name" want="$name $ver $PLAT"
  if stamp_ok "$d" "$want" && [ -x "$T/bin/$name" ]; then ok "$want"; return; fi
  if $CHECK; then todo "$want"; return; fi
  local f; f="$(fetch "$url" "$sha")"
  unpack "$f" "$d" "$strip"
  for x in "$@"; do cp "$d/$x" "$T/bin/$x"; chmod +x "$T/bin/$x"; done
  stamp "$d" "$want"; ok "$want"
}
install_bin uv "$UV_VERSION" "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-$UV_P.tar.gz" "$(sha_var UV)" 1 uv
install_bin rg "$RG_VERSION" "https://github.com/BurntSushi/ripgrep/releases/download/$RG_VERSION/ripgrep-$RG_VERSION-$RG_P.tar.gz" "$(sha_var RG)" 1 rg
install_bin scip "$SCIP_VERSION" "https://github.com/scip-code/scip/releases/download/v$SCIP_VERSION/scip-$SCIP_P.tar.gz" "$(sha_var SCIP)" 0 scip

# npm packages: scip-typescript, scip-python, typescript (tools/) and Claude Code (tools/claude-code/), from the lockfiles
npm_ci() {  # dir label
  local want="lock $(file_sha "$1/package-lock.json") $PLAT"
  if [ -d "$1/node_modules" ] && stamp_ok "$1/node_modules" "$want"; then ok "$2"; return; fi
  if $CHECK; then todo "$2"; return; fi
  echo "  npm ci in ${1#$P/}" >&2
  (cd "$1" && "$SB" -- npm ci --no-audit --no-fund --loglevel=error) || die "npm ci failed in $1"
  stamp "$1/node_modules" "$want"; ok "$2"
}
npm_ci "$T" "scip-typescript, scip-python, typescript"
npm_ci "$T/claude-code" "Claude Code $(sed -n 's/.*"@anthropic-ai\/claude-code": "\([^"]*\)".*/\1/p' "$T/claude-code/package.json" | head -1)"
if ! $CHECK; then
  rm -rf "$T/bin/.claude-code"   # the old, unpinned location
  ln -sfn ../claude-code/node_modules/.bin/claude "$T/bin/claude"
fi

# ---------------------------------------------------------------- 3. python
step "3/6 Python $PYTHON_VERSION and the two venvs"
UVENV=(-e "UV_PYTHON_INSTALL_DIR=$T/python" -e UV_PYTHON_PREFERENCE=only-managed -e UV_PYTHON_DOWNLOADS=automatic)
PYBIN=""
if [ -x "$T/bin/uv" ]; then
  PYBIN="$("$SB" "${UVENV[@]}" -- uv python find "$PYTHON_VERSION" 2>/dev/null || true)"
fi
if [ -n "$PYBIN" ]; then ok "Python $("$PYBIN" -c 'import platform; print(platform.python_version())')"
elif $CHECK; then todo "Python $PYTHON_VERSION"
else
  "$SB" "${UVENV[@]}" -- uv python install --quiet "$PYTHON_VERSION" || die "uv could not install Python $PYTHON_VERSION"
  PYBIN="$("$SB" "${UVENV[@]}" -- uv python find "$PYTHON_VERSION")"
  ok "Python $("$PYBIN" -c 'import platform; print(platform.python_version())') (tools/python)"
fi

make_venv() {  # dir requirements label
  local want="$PYBIN $(file_sha "$2")"
  if [ -n "$PYBIN" ] && [ -x "$1/bin/python" ] && stamp_ok "$1" "$want"; then ok "$3"; return; fi
  if $CHECK; then todo "$3"; return; fi
  rm -rf "$1"
  "$SB" "${UVENV[@]}" -- uv venv --quiet --python "$PYBIN" "$1" || die "could not create $1"
  "$SB" "${UVENV[@]}" -- uv pip install --quiet --python "$1/bin/python" -r "$2" || die "could not install $2"
  stamp "$1" "$want"; ok "$3"
}
make_venv "$T/.venv" "$T/requirements-graph.txt" "tools/.venv (graphify)"
make_venv "$T/.venv-store" "$T/requirements-store.txt" "tools/.venv-store (org MCP server, scripts)"

# ---------------------------------------------------------------- 4. configurations
step "4/6 configurations (conditions/, written for this folder)"
if [ -f "$P/conditions/X-A1/settings.json" ] && grep -qF "\"$P/worlds/**\"" "$P/conditions/X-A1/settings.json"; then ok "conditions/*/settings.json"
elif $CHECK; then todo "conditions/*/settings.json (run bin/make-templates)"
else "$T/.venv-store/bin/python" "$P/bin/make-templates" >/dev/null && ok "conditions/*/settings.json"
fi

# ---------------------------------------------------------------- 5. Claude sign-in
step "5/6 Claude sign-in (subscription token)"
token_ok() { [ -f "$SECRETS" ] && grep -qE '^CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-[A-Za-z0-9_-]+$' "$SECRETS"; }
if token_ok; then ok "token in $(pretty "$SECRETS")"
elif $CHECK || ! $LOGIN; then todo "no token yet in $(pretty "$SECRETS") (run ./setup.sh without --no-login)"
elif [ ! -t 0 ]; then todo "no token, and no terminal to sign in from: run ./setup.sh in a terminal"
else
  cat <<EOF

  The experiment runs Claude Code on your Claude subscription (Pro or Max), never on an API key.
  Next: Claude Code's 'setup-token' opens a sign-in page in your browser. Sign in, approve, and
  it prints a long-lived token (sk-ant-oat01-...). Copy it, then paste it here when asked.

EOF
  read -r -p "  Press Enter to open the sign-in page (Ctrl-C to stop) " _
  "$SB" -e "BROWSER=$P/bin/open-url" -- "$T/bin/claude" setup-token || true
  echo
  tok=""
  for _try in 1 2 3; do
    read -r -s -p "  Paste the token (input hidden), then Enter: " tok; echo
    tok="$(printf '%s' "$tok" | tr -d '[:space:]')"
    case "$tok" in
      sk-ant-oat01-*) break ;;
      sk-ant-api*) echo "  that is an API key; this project uses the subscription token from setup-token (sk-ant-oat01-...)"; tok="" ;;
      *) echo "  that does not look like a subscription token (it starts with sk-ant-oat01-)"; tok="" ;;
    esac
  done
  [ -n "$tok" ] || die "no token saved. Re-run ./setup.sh to try again."
  ( umask 077; mkdir -p "$(dirname "$SECRETS")"; printf 'CLAUDE_CODE_OAUTH_TOKEN=%s\n' "$tok" > "$SECRETS" )
  chmod 600 "$SECRETS"; unset tok
  ok "token saved to $(pretty "$SECRETS") (outside the project, readable only by you)"
  echo "  testing it with one tiny Haiku call..."
  mkdir -p "$P/.sandbox/tmp/login-test"
  if out="$(cd "$P/.sandbox/tmp/login-test" && "$SB" --secrets -- "$T/bin/claude" -p "Reply with just the word OK." \
            --model claude-haiku-5-5 --max-turns 1 2>&1)" && printf '%s' "$out" | grep -q OK; then
    ok "Claude answered: the token works"
  else
    printf '%s\n' "$out" | tail -5 | sed 's/^/    /'
    die "the token did not work. Delete $(pretty "$SECRETS") and re-run ./setup.sh"
  fi
fi

# ---------------------------------------------------------------- 6. build + checks
step "6/6 build the worlds and run the checks"
if $CHECK; then
  if [ -d "$P/worlds/base" ]; then ok "worlds/ built"; else todo "worlds/ not built (bin/setup)"; fi
elif ! $BUILD; then echo "  skipped (--no-build)"
else
  # run with the project's Python directly: no system python3 needed
  "$T/.venv-store/bin/python" "$P/bin/setup" || die "bin/setup failed"
  "$T/.venv-store/bin/python" "$P/bin/check" || die "bin/check failed"
fi

# ---------------------------------------------------------------- done
if $CHECK; then
  echo
  if [ "$MISSING" -eq 0 ]; then printf '%sEverything is set up.%s\n' "$G" "$N"; exit 0
  else printf '%s%d item(s) missing:%s run ./setup.sh\n' "$Y" "$MISSING" "$N"; exit 1; fi
fi
cat <<EOF

${G}${B}Ready.${N} Next:
  bin/verify --core           end to end, the core 3x3: 27 graded Haiku runs (about 3 minutes)
  bin/verify                  end to end, every scenario x every configuration: 108 graded runs
  bin/session X-G3 T3         interactive: one live Claude session, watch its tool calls and answer
  core-3x3.html               the helper page: what this is, how it is isolated, a copy-paste command per cell
  ./setup.sh --clean          remove everything again, including the Claude token
EOF
# Open the helper page, unless asked not to or there is no one to look at it (CI, ssh without a display).
if $OPEN && $BUILD && [ -t 1 ] && [ -z "${CI:-}" ]; then
  "$P/bin/open-url" "$P/core-3x3.html"
fi
