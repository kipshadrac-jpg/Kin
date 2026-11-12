#!/usr/bin/env bash
# Day-to-day commands for Kin. Run from the kin folder:  ./kin.sh <command>
set -euo pipefail
cd "$(dirname "$0")"

DC="docker compose"
if ! docker info >/dev/null 2>&1; then DC="sudo docker compose"; fi

env_set() { # env_set KEY VALUE  (edits .env in place)
  local k="$1" v="$2"
  if grep -q "^${k}=" .env; then sed -i "s|^${k}=.*|${k}=${v}|" .env; else echo "${k}=${v}" >> .env; fi
}

case "${1:-help}" in
  status)   $DC ps ;;
  logs)     $DC logs --tail "${3:-100}" -f ${2:-} ;;
  start|up) $DC up -d ;;
  stop|down) $DC down ;;
  restart)  $DC restart ${2:-} ;;
  update)   # after uploading a new zip over this folder
            $DC build --pull && $DC up -d && $DC ps ;;
  health)   $DC exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/v1/health').read().decode())" ;;
  set-key)
            read -r -s -p "Anthropic API key: " k; echo
            env_set ANTHROPIC_API_KEY "$k"
            $DC up -d api worker && echo "Saved. Chat is on." ;;
  set-openai-key)
            read -r -s -p "OpenAI API key (empty = built-in search): " k; echo
            env_set OPENAI_API_KEY "$k"
            if [ -n "$k" ]; then env_set EMBEDDING_PROVIDER openai; else env_set EMBEDDING_PROVIDER hashing; fi
            $DC up -d api worker
            echo "Saved. Re-indexing your journal for the new search..."
            $DC run --rm migrate python -m app.db.reembed ;;
  set-model)
            env_set LLM_MODEL "${2:?usage: ./kin.sh set-model <model-id>}"
            $DC up -d api worker && echo "Model set to $2" ;;
  lock-signups)   env_set DISABLE_SIGNUP true;  $DC up -d auth && echo "Sign-ups are now closed." ;;
  unlock-signups) env_set DISABLE_SIGNUP false; $DC up -d auth && echo "Sign-ups are open." ;;
  backup)
            mkdir -p backups
            f="backups/kin-$(date +%Y%m%d-%H%M%S).dump"
            $DC exec -T db pg_dump -U supabase_admin -d postgres -Fc --exclude-schema=extensions > "$f"
            chmod 600 "$f"
            find backups -name 'kin-*.dump' -mtime +14 -delete
            echo "Backup written: $f" ;;
  restore)
            f="${2:?usage: ./kin.sh restore backups/kin-XXXX.dump}"
            read -r -p "This REPLACES all current data with $f. Type 'restore' to continue: " c
            [ "$c" = "restore" ] || { echo "Cancelled."; exit 1; }
            $DC stop api worker auth
            $DC exec -T db pg_restore -U supabase_admin -d postgres --clean --if-exists --no-owner \
              --schema=public --schema=auth --schema=kin_meta < "$f" || true
            $DC up -d && echo "Restored from $f" ;;
  help|*)
            cat <<'EOF'
Kin commands:
  ./kin.sh status            what's running
  ./kin.sh logs [service]    follow logs (api, worker, auth, db, caddy)
  ./kin.sh health            API + database check
  ./kin.sh restart [service] restart everything or one service
  ./kin.sh stop | start      stop or start Kin
  ./kin.sh update            rebuild after uploading a new version
  ./kin.sh set-key           add or change the Anthropic API key
  ./kin.sh set-openai-key    add/remove the OpenAI key for journal search
  ./kin.sh set-model <id>    change the Claude model (e.g. claude-sonnet-5-5)
  ./kin.sh lock-signups      stop new accounts (do this after creating yours)
  ./kin.sh unlock-signups    allow new accounts again
  ./kin.sh backup            database backup into ./backups (also runs daily)
  ./kin.sh restore FILE      restore a backup (replaces current data)
EOF
            ;;
esac
