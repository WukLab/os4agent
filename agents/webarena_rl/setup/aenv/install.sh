#!/bin/bash
# AgentENV on wuklab-08, step 1 (agents/osworld_rl/SETUP.md §5): host prep with osworld_rl's setup-host.sh (persistent:
# ublk_drv at boot, /etc/sysctl.d/99-aenv.conf) and the aenv CLI from the latest GitHub release into ~/.local/bin
# (the release script, downloaded into its own directory and read before running; it checks the tarball's SHA256).
#   bash agents/webarena_rl/setup/aenv/install.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OSW="$HERE/../../../osworld_rl/setup/aenv"
sudo -n bash "$OSW/setup-host.sh"
D=/mnt/data/btrfs/aenv/dl_cli
mkdir -p "$D"
[ -s "$D/install-cli.sh" ] || curl -fsSL -o "$D/install-cli.sh" \
    https://github.com/kvcache-ai/AgentENV/releases/latest/download/install-cli.sh
INSTALL_DIR="$HOME/.local/bin" bash "$D/install-cli.sh"
"$HOME/.local/bin/aenv" --version
