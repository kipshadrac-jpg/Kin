#!/usr/bin/env bash
# Kin installer for a fresh Ubuntu server.
#
#   cd ~/kin && sudo bash install.sh
#
# Safe to run again: it keeps your existing .env (passwords, keys) and data.
set -euo pipefail

trap 'echo; echo "xx  install.sh stopped at line $LINENO. Send this screen to get help." >&2' ERR

cd "$(dirname "$0")"
KIN_DIR="$(pwd)"
DEFAULT_DOMAIN="kin-ai.site"

say()  { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!!  %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31mxx  %s\033[0m\n' "$*"; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run with sudo:  sudo bash install.sh"

# ---------------------------------------------------------------- 1. packages
say "Installing Docker (this takes a few minutes the first time)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y >/dev/null
apt-get install -y ca-certificates curl openssl ufw dnsutils >/dev/null
if ! command -v docker >/dev/null 2>&1; then
  if ! apt-get install -y docker.io docker-compose-v2 >/dev/null 2>&1; then
    warn "Ubuntu's Docker packages were not available; using Docker's official installer"
    curl -fsSL https://get.docker.com | sh
  fi
fi
if ! docker compose version >/dev/null 2>&1; then
  apt-get install -y docker-compose-v2 >/dev/null 2>&1 || apt-get install -y docker-compose-plugin >/dev/null 2>&1 \
    || die "Could not install 'docker compose'"
fi
systemctl enable --now docker >/dev/null
SUDO_USER_NAME="${SUDO_USER:-}"
if [ -n "$SUDO_USER_NAME" ] && [ "$SUDO_USER_NAME" != "root" ]; then
  usermod -aG docker "$SUDO_USER_NAME" || true
fi
docker --version
docker compose version

# ---------------------------------------------------------------- 2. swap
if [ "$(swapon --show | wc -l)" -eq 0 ]; then
  say "Adding 2 GB of swap (helps a small server stay stable)"
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# ---------------------------------------------------------------- 3. firewall
say "Firewall: allowing SSH, HTTP and HTTPS only"
# sshd -T can fail on some systems (e.g. no /run/sshd yet); fall back to the listening port, then 22.
SSH_PORT="$( (sshd -T 2>/dev/null || true) | awk '/^port /{print $2; exit}' )"
[ -n "$SSH_PORT" ] || SSH_PORT="$( (ss -tlnp 2>/dev/null || true) | awk '/sshd/ {n=split($4,a,":"); print a[n]; exit}' )"
SSH_PORT="${SSH_PORT:-22}"
ufw allow "${SSH_PORT}/tcp" >/dev/null   # SSH first, so you never lock yourself out
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw allow 443/udp >/dev/null
ufw --force enable >/dev/null
ufw status | sed -n '1,12p'

# ---------------------------------------------------------------- 4. settings
rand() { openssl rand -hex "$1"; }
ask() { # ask VAR "Question" default secret
  local var="$1" q="$2" def="${3:-}" secret="${4:-}" val=""
  if [ -n "${!var:-}" ]; then return; fi
  if [ -t 0 ]; then
    if [ "$secret" = "secret" ]; then read -r -s -p "$q " val || true; echo; else read -r -p "$q [${def}] " val || true; fi
  fi
  printf -v "$var" '%s' "${val:-$def}"
}

if [ -f .env ]; then
  say "Keeping your existing settings in .env"
  set -a; . ./.env; set +a
else
  say "A few settings"
  ask DOMAIN "Domain name pointing at this server?" "$DEFAULT_DOMAIN"
  echo
  echo "Kin uses Claude (Anthropic) to think things through. Paste your Anthropic API key"
  echo "(starts with sk-ant-). Leave empty to add it later with:  ./kin.sh set-key"
  ask ANTHROPIC_API_KEY "Anthropic API key:" "" secret
  echo
  echo "Optional: an OpenAI API key gives better journal search (embeddings)."
  echo "Leave empty to use Kin's built-in search, which never sends journal text anywhere."
  ask OPENAI_API_KEY "OpenAI API key (optional):" "" secret
  EMBEDDING_PROVIDER="hashing"; [ -n "${OPENAI_API_KEY:-}" ] && EMBEDDING_PROVIDER="openai"
  umask 077
  cat > .env <<EOF
# Kin settings. Keep this file private: it holds passwords and API keys.
APP_NAME=Kin
DOMAIN=${DOMAIN}
POSTGRES_PASSWORD=$(rand 24)
JWT_SECRET=$(rand 32)
KIN_API_DB_PASSWORD=$(rand 24)
KIN_WORKER_DB_PASSWORD=$(rand 24)
LLM_PROVIDER=anthropic
LLM_MODEL=claude-opus-5-5
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}
EMBEDDING_PROVIDER=${EMBEDDING_PROVIDER}
OPENAI_API_KEY=${OPENAI_API_KEY:-}
DISABLE_SIGNUP=false
EOF
  chmod 600 .env
  set -a; . ./.env; set +a
fi
[ -n "${SUDO_USER_NAME}" ] && chown -R "${SUDO_USER_NAME}:" "$KIN_DIR" 2>/dev/null || true

# ---------------------------------------------------------------- 5. DNS check
say "Checking that ${DOMAIN} points at this server"
PUBLIC_IP="$(curl -4 -fsS --max-time 8 https://api.ipify.org 2>/dev/null || true)"
DNS_IP="$(dig +short A "${DOMAIN}" @1.1.1.1 2>/dev/null | tail -n1 || true)"
if [ -n "$PUBLIC_IP" ] && [ "$PUBLIC_IP" = "$DNS_IP" ]; then
  echo "OK: ${DOMAIN} -> ${DNS_IP}"
else
  warn "${DOMAIN} resolves to '${DNS_IP:-nothing}', this server is '${PUBLIC_IP:-unknown}'."
  warn "HTTPS will start working once the domain's A record points here. Continuing."
fi

# ---------------------------------------------------------------- 6. start
[ -f web/out/index.html ] || die "web/out is missing from the package. Re-download the zip."
say "Building and starting Kin (first build: ~3-6 minutes)"
docker compose build --pull
docker compose up -d

say "Waiting for Kin to come up"
for i in $(seq 1 60); do
  if docker compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')" >/dev/null 2>&1; then
    ok=1; break
  fi
  sleep 5
done
[ "${ok:-0}" = 1 ] || { docker compose ps; docker compose logs --tail 40 migrate api; die "Kin did not become healthy. See logs above."; }

# ---------------------------------------------------------------- 7. backups
cat > /etc/cron.d/kin-backup <<EOF
# Daily database backup for Kin at 02:17 server time; keeps 14 days.
17 2 * * * root cd ${KIN_DIR} && ./kin.sh backup >/dev/null 2>&1
EOF
chmod 644 /etc/cron.d/kin-backup

docker compose ps
say "Kin is running:  https://${DOMAIN}"
echo "  1. Open it on your phone and create your account."
echo "  2. Then lock sign-ups so nobody else can register:   ./kin.sh lock-signups"
echo "  3. Add to home screen from your browser menu to use it like an app."
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then warn "No Anthropic key yet: the Think tab will be off until you run  ./kin.sh set-key"; fi
echo "Help:  ./kin.sh help"
