#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -e

export RAIDBRIEF_TOKEN="$(bashio::config 'tarkovtracker_token')"
export RAIDBRIEF_GAME_MODE="$(bashio::config 'game_mode')"
export RAIDBRIEF_REFRESH_MINUTES="$(bashio::config 'refresh_minutes')"
export RAIDBRIEF_KAPPA_ONLY="$(bashio::config 'kappa_only')"
export RAIDBRIEF_DATA_DIR="/data"

# One env var per trader keeps run.sh dumb and the schema readable in the UI.
for trader in prapor therapist fence skier peacekeeper mechanic ragman jaeger ref lightkeeper; do
    value="$(bashio::config "trader_levels.${trader}")"
    # bashio prints "null" for an option the user removed from the YAML.
    if [ -z "${value}" ] || [ "${value}" = "null" ]; then
        value=1
    fi
    export "RAIDBRIEF_TRADER_$(echo "${trader}" | tr '[:lower:]' '[:upper:]')=${value}"
done

if bashio::config.is_empty 'tarkovtracker_token'; then
    bashio::log.warning "No TarkovTracker token set - showing every task for a fresh character."
    bashio::log.warning "Add one under the add-on Configuration tab to see your real progress."
fi

bashio::log.info "Starting Tarkov Raid Brief on :8099 (mode: ${RAIDBRIEF_GAME_MODE}, refresh: ${RAIDBRIEF_REFRESH_MINUTES}m)"

exec python3 -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8099 \
    --app-dir /app \
    --no-server-header \
    --log-level info
