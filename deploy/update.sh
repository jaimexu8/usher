#!/usr/bin/env bash
# Deploy/update the coc-bot on EC2: pull latest code, rebuild image, restart service.
# Run from the repo root or from deploy/:
#   ./deploy/update.sh
#   or from deploy/: ./update.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

echo "==> Pulling latest code..."
git pull origin main

echo "==> Building Docker image coc-bot:latest..."
sudo docker build -t coc-bot:latest .

echo "==> Restarting coc-bot.service..."
sudo systemctl restart coc-bot.service

echo "==> Waiting 2s for service to start..."
sleep 2
sudo systemctl status coc-bot.service --no-pager

echo ""
echo "Done. View logs: sudo journalctl -u coc-bot.service -f"
