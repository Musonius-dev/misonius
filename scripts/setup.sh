#!/usr/bin/env bash
# Musonius — one-time setup script for macOS/Linux
# Run: bash scripts/setup.sh
set -euo pipefail

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
DIM='\033[2m'
RESET='\033[0m'

echo -e "${BOLD}Musonius Setup${RESET}"
echo -e "${DIM}One-time configuration for your development environment.${RESET}"
echo ""

# ─── Step 1: Check Python version ───────────────────────────────────────────
echo -e "${BOLD}[1/6] Checking Python...${RESET}"
PYTHON=""
for cmd in python3.12 python3.11 python3.10 python3; do
    if command -v "$cmd" &>/dev/null; then
        version=$($cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "")
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [ "$major" = "3" ] && [ "$minor" -ge 10 ]; then
            PYTHON="$cmd"
            echo -e "  ${GREEN}Found $cmd ($version)${RESET}"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo -e "  ${RED}Python 3.10+ not found. Install it first:${RESET}"
    echo -e "  ${DIM}brew install python@3.12${RESET}  (macOS)"
    echo -e "  ${DIM}sudo apt install python3.12${RESET}  (Ubuntu)"
    exit 1
fi

# ─── Step 2: Create/fix virtual environment ──────────────────────────────────
echo -e "${BOLD}[2/6] Setting up virtual environment...${RESET}"
VENV_DIR=".venv"

if [ -d "$VENV_DIR" ]; then
    # Check if venv python is usable
    if "$VENV_DIR/bin/python" --version &>/dev/null; then
        echo -e "  ${GREEN}Existing .venv is healthy.${RESET}"
    else
        echo -e "  ${YELLOW}Existing .venv is broken — recreating...${RESET}"
        rm -rf "$VENV_DIR"
        $PYTHON -m venv "$VENV_DIR"
        echo -e "  ${GREEN}Virtual environment recreated.${RESET}"
    fi
else
    $PYTHON -m venv "$VENV_DIR"
    echo -e "  ${GREEN}Virtual environment created.${RESET}"
fi

# ─── Step 3: Install dependencies ────────────────────────────────────────────
echo -e "${BOLD}[3/6] Installing dependencies...${RESET}"
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -e ".[dev]" -q 2>/dev/null || "$VENV_DIR/bin/pip" install -e . -q
echo -e "  ${GREEN}Dependencies installed.${RESET}"

# ─── Step 4: Initialize project (local indexing only) ─────────────────────────
echo -e "${BOLD}[4/6] Running musonius init...${RESET}"
"$VENV_DIR/bin/python" -m musonius init --auto 2>/dev/null && \
    echo -e "  ${GREEN}Project initialized.${RESET}" || \
    echo -e "  ${YELLOW}Init skipped (run 'musonius init' manually).${RESET}"

# ─── Step 5: API key setup ──────────────────────────────────────────────────
echo -e "${BOLD}[5/6] Checking API keys...${RESET}"

check_key() {
    local name="$1"
    local var="$2"
    if [ -n "${!var:-}" ]; then
        echo -e "  ${GREEN}$name: configured${RESET}"
        return 0
    else
        echo -e "  ${DIM}$name: not set ($var)${RESET}"
        return 1
    fi
}

has_any_key=false
check_key "Gemini (free tier)" "GEMINI_API_KEY" && has_any_key=true
check_key "Google AI" "GOOGLE_API_KEY" && has_any_key=true
check_key "Anthropic" "ANTHROPIC_API_KEY" && has_any_key=true
check_key "OpenAI" "OPENAI_API_KEY" && has_any_key=true

if [ "$has_any_key" = false ]; then
    echo ""
    echo -e "  ${YELLOW}No API keys detected.${RESET}"
    echo -e "  ${DIM}Musonius init/prep/memory work without keys.${RESET}"
    echo -e "  ${DIM}For plan/verify, set at least one:${RESET}"
    echo -e "    ${DIM}export GEMINI_API_KEY=...  (free at aistudio.google.com)${RESET}"
    echo -e "    ${DIM}export ANTHROPIC_API_KEY=...${RESET}"
fi

# ─── Step 6: MCP configuration ──────────────────────────────────────────────
echo ""
echo -e "${BOLD}[6/6] MCP server configuration${RESET}"
echo -e "  ${DIM}To use Musonius as an MCP server with Claude Code:${RESET}"
echo ""

MUSONIUS_PATH="$(cd "$(dirname "$0")/.." && pwd)"
cat <<MCPEOF
  Add to ~/.claude/claude_code_config.json:

  {
    "mcpServers": {
      "musonius": {
        "command": "$MUSONIUS_PATH/$VENV_DIR/bin/python",
        "args": ["-m", "musonius", "serve"]
      }
    }
  }

MCPEOF

echo -e "  ${DIM}For Cursor, add to .cursor/mcp.json in the same format.${RESET}"

# ─── Done ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}Setup complete!${RESET}"
echo ""
echo -e "  ${BOLD}Quick start:${RESET}"
echo -e "    source $VENV_DIR/bin/activate"
echo -e "    musonius go \"add rate limiting to the API\""
echo ""
echo -e "  ${BOLD}Or step by step:${RESET}"
echo -e "    musonius init              ${DIM}# Index codebase (no API key needed)${RESET}"
echo -e "    musonius plan \"task\"        ${DIM}# Generate phased plan${RESET}"
echo -e "    musonius prep              ${DIM}# Generate handoff for your agent${RESET}"
echo -e "    musonius verify --no-llm   ${DIM}# Check your changes${RESET}"
echo ""
