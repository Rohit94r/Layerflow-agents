#!/usr/bin/env bash
# LayerFlow Agents — local model host setup (Ollama + Qwen2.5 + nomic-embed)
#
# Installs Ollama, pulls the models the app expects, verifies the endpoint, and
# optionally writes the MODEL_* block into apps/api/.env and runs the benchmark.
#
#   ./scripts/local_model_setup.sh                 # standard tier (3B + 7B + embed)
#   ./scripts/local_model_setup.sh --tier minimal  # 3B + embed only (~2.2 GB)
#   ./scripts/local_model_setup.sh --tier stretch  # 14B writer (16 GB+ RAM, tight)
#   ./scripts/local_model_setup.sh --write-env     # also update apps/api/.env
#   ./scripts/local_model_setup.sh --bench         # run scripts/bench_model.py after
#   ./scripts/local_model_setup.sh --check         # report only, change nothing
#
# Tested on macOS (Apple Silicon) and Linux. Re-running is safe (idempotent).

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$ROOT/apps/api"
ENV_FILE="$API_DIR/.env"
OLLAMA_HOST_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
LOG_FILE="${TMPDIR:-/tmp}/layerflow-ollama.log"

TIER="standard"
WRITE_ENV=0
RUN_BENCH=0
CHECK_ONLY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --tier)       TIER="${2:-standard}"; shift 2 ;;
    --tier=*)     TIER="${1#*=}"; shift ;;
    --write-env)  WRITE_ENV=1; shift ;;
    --bench)      RUN_BENCH=1; shift ;;
    --check)      CHECK_ONLY=1; shift ;;
    -h|--help)    sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

case "$TIER" in
  minimal|standard|stretch) ;;
  *) printf "Unknown tier '%s' (use: minimal | standard | stretch)\n" "$TIER" >&2; exit 2 ;;
esac

say()  { printf '%s\n' "$*"; }
step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33mWARN:\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- hardware ----
detect_hardware() {
  local os ram_bytes ram_gb disk_avail_gb
  os="$(uname -s)"
  case "$os" in
    Darwin) ram_bytes=$(sysctl -n hw.memsize 2>/dev/null || echo 0) ;;
    Linux)  ram_bytes=$(awk '/MemTotal/{print $2*1024}' /proc/meminfo 2>/dev/null || echo 0) ;;
    *)      ram_bytes=0 ;;
  esac
  ram_gb=$(( ram_bytes / 1073741824 ))
  disk_avail_gb=$(df -Pk "$ROOT" 2>/dev/null | awk 'NR==2{print int($4/1048576)}')
  printf '%s %s %s\n' "$os" "$ram_gb" "${disk_avail_gb:-0}"
}

# ---------------------------------------------------------------- models ------
models_for_tier() {
  case "$TIER" in
    minimal) echo "qwen2.5:3b-instruct nomic-embed-text" ;;
    standard) echo "qwen2.5:3b-instruct qwen2.5:7b-instruct nomic-embed-text" ;;
    stretch) echo "qwen2.5:3b-instruct qwen2.5:14b-instruct nomic-embed-text" ;;
    *) die "Unknown tier '$TIER' (use: minimal | standard | stretch)" ;;
  esac
}

writer_for_tier() {
  case "$TIER" in
    minimal) echo "qwen2.5:3b-instruct" ;;
    standard) echo "qwen2.5:7b-instruct" ;;
    stretch) echo "qwen2.5:14b-instruct" ;;
  esac
}

# Rough download size in GB for the tier (weights only).
size_for_tier() {
  case "$TIER" in
    minimal) echo 2 ;;
    standard) echo 7 ;;
    stretch) echo 10 ;;
  esac
}

# ---------------------------------------------------------------- helpers -----
have() { command -v "$1" >/dev/null 2>&1; }

ollama_up() {
  curl -fsS -m 3 "$OLLAMA_HOST_URL/api/tags" >/dev/null 2>&1
}

install_ollama() {
  if have ollama; then
    say "Ollama already installed: $(ollama --version 2>/dev/null | head -1)"
    return
  fi
  step "Installing Ollama"
  if have brew; then
    brew install ollama || die "brew install ollama failed"
  elif [ "$(uname -s)" = "Linux" ]; then
    curl -fsSL https://ollama.com/install.sh | sh || die "Ollama install script failed"
  else
    die "No Homebrew found. Install it from https://brew.sh or download Ollama from https://ollama.com/download"
  fi
  have ollama || die "Ollama installed but not on PATH — open a new terminal and re-run"
}

start_ollama() {
  ollama_up && { say "Ollama already running at $OLLAMA_HOST_URL"; return; }
  step "Starting Ollama"
  if have brew && [ "$(uname -s)" = "Darwin" ]; then
    brew services start ollama >/dev/null 2>&1 || true
  fi
  if ! ollama_up; then
    # Background server as a fallback (works everywhere).
    OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:11434}" nohup ollama serve >"$LOG_FILE" 2>&1 &
    local i
    for i in $(seq 1 30); do
      sleep 1
      ollama_up && break
    done
  fi
  ollama_up || die "Ollama did not come up. Check $LOG_FILE"
  say "Ollama is up at $OLLAMA_HOST_URL"
}

pull_models() {
  local m
  for m in $(models_for_tier); do
    step "Pulling $m"
    ollama pull "$m" || die "Failed to pull $m (check disk space and network)"
  done
}

set_env_key() {
  local file="$1" key="$2" val="$3"
  [ -f "$file" ] || : > "$file"
  if grep -qE "^${key}=" "$file"; then
    if sed --version >/dev/null 2>&1; then
      sed -i "s|^${key}=.*|${key}=${val}|" "$file"
    else
      sed -i '' "s|^${key}=.*|${key}=${val}|" "$file"
    fi
  else
    printf '%s=%s\n' "$key" "$val" >> "$file"
  fi
}

write_env() {
  step "Updating $ENV_FILE"
  if [ -f "$ENV_FILE" ]; then
    cp "$ENV_FILE" "$ENV_FILE.bak.$(date +%Y%m%d%H%M%S)"
    say "Backup written next to it"
  else
    warn "No .env found — creating a minimal one. Copy the rest from SETUP.md §3."
    printf 'APP_ENV=development\n' > "$ENV_FILE"
  fi
  set_env_key "$ENV_FILE" MODEL_PROVIDER "ollama"
  set_env_key "$ENV_FILE" OLLAMA_BASE_URL "$OLLAMA_HOST_URL"
  set_env_key "$ENV_FILE" MODEL_WRITER "$(writer_for_tier)"
  set_env_key "$ENV_FILE" MODEL_FAST "qwen2.5:3b-instruct"
  set_env_key "$ENV_FILE" MODEL_EMBED "nomic-embed-text"
  set_env_key "$ENV_FILE" MODEL_TIMEOUT_S "600"
  set_env_key "$ENV_FILE" MODEL_CONCURRENCY "1"
  set_env_key "$ENV_FILE" MODEL_NUM_CTX "8192"
  say "MODEL_WRITER=$(writer_for_tier)  MODEL_FAST=qwen2.5:3b-instruct  MODEL_EMBED=nomic-embed-text"
}

run_bench() {
  local py="$API_DIR/.venv/bin/python" model
  model="$(writer_for_tier)"
  step "Benchmarking $model"
  if [ ! -x "$py" ]; then
    warn "apps/api/.venv missing — skipping bench. Create it first:"
    say "  cd apps/api && python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'"
    return
  fi
  ( cd "$ROOT" && "$py" scripts/bench_model.py --model "$model" --runs 3 ) || warn "Benchmark failed (model/deps?)"
}

# ---------------------------------------------------------------- main --------
read -r OS RAM_GB DISK_GB <<<"$(detect_hardware)"
NEED_GB="$(size_for_tier)"

step "LayerFlow local model setup"
say "OS            : $OS"
say "RAM           : ${RAM_GB} GB"
say "Disk free     : ${DISK_GB} GB (need ~${NEED_GB} GB for this tier)"
say "Tier          : $TIER -> $(models_for_tier)"
say "Endpoint      : $OLLAMA_HOST_URL"

# Capacity guard-rails.
if [ "$RAM_GB" -lt 8 ]; then
  warn "Under 8 GB RAM: use --tier minimal and expect slow generation."
fi
if [ "$TIER" = "standard" ] && [ "$RAM_GB" -lt 12 ]; then
  warn "7B needs ~6–7 GB resident. Close heavy apps or use --tier minimal."
fi
if [ "$TIER" = "stretch" ] && [ "$RAM_GB" -lt 16 ]; then
  die "14B needs 16 GB+ unified RAM. Use --tier standard on this machine."
fi
if [ "$DISK_GB" -lt $(( NEED_GB + 3 )) ]; then
  warn "Low disk: ${DISK_GB} GB free, want $(( NEED_GB + 3 )) GB. Free space before pulling."
fi

if [ "$CHECK_ONLY" -eq 1 ]; then
  step "Check-only mode"
  if ollama_up; then
    say "Ollama: running"
    ollama list 2>/dev/null || true
  else
    say "Ollama: not running / not installed"
  fi
  exit 0
fi

install_ollama
start_ollama
pull_models

if [ "$WRITE_ENV" -eq 1 ]; then write_env; fi

step "Verify"
if ollama_up; then
  say "Installed models:"
  ollama list 2>/dev/null | sed 's/^/  /'
else
  warn "Ollama endpoint not reachable after setup."
fi

if [ "$RUN_BENCH" -eq 1 ]; then run_bench; fi

step "Done"
cat <<EOF
Next steps:
  1. Ensure apps/api/.env has MODEL_PROVIDER=ollama (use --write-env to set it).
  2. Start the stack:            ./scripts/dev.sh
  3. Dashboard → Settings → Models → Test (expect latency + sample reply).
  4. Measure this machine:       cd apps/api && .venv/bin/python ../../scripts/bench_model.py --model $(writer_for_tier)

Notes:
  • Keep ONE model loaded: OLLAMA_MAX_LOADED_MODELS=1 (compose already sets this).
  • Swap writer to the 3B for fast demos: MODEL_WRITER=qwen2.5:3b-instruct
  • Ollama logs: $LOG_FILE
EOF
