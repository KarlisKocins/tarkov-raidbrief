#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -e

export RAIDBRIEF_TOKEN="$(bashio::config 'tarkovtracker_token')"
export RAIDBRIEF_GAME_MODE="$(bashio::config 'game_mode')"
export RAIDBRIEF_REFRESH_MINUTES="$(bashio::config 'refresh_minutes')"
export RAIDBRIEF_KAPPA_ONLY="$(bashio::config 'kappa_only')"
export RAIDBRIEF_DATA_DIR="/data"

# Optional AI. bashio prints "null" for an unset optional option, which must
# not reach the app as a literal API key. Written as plain `if` blocks on
# purpose: `[ a ] || [ b ] && c` parses as `([ a ] || [ b ]) && c`, which is
# both easy to misread and awkward under `set -e`.
gemini_key="$(bashio::config 'gemini_api_key')"
if [ "${gemini_key}" = "null" ]; then
    gemini_key=""
fi
export RAIDBRIEF_GEMINI_KEY="${gemini_key}"

gemini_model="$(bashio::config 'gemini_model')"
if [ -z "${gemini_model}" ] || [ "${gemini_model}" = "null" ]; then
    gemini_model="gemini-2.5-flash"
fi
export RAIDBRIEF_GEMINI_MODEL="${gemini_model}"

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

# bashio prints one array element per line; the app wants them comma-separated.
excluded=""
if bashio::config.has_value 'excluded_maps'; then
    while read -r entry; do
        if [ -z "${entry}" ] || [ "${entry}" = "null" ]; then
            continue
        fi
        if [ -z "${excluded}" ]; then
            excluded="${entry}"
        else
            excluded="${excluded},${entry}"
        fi
    done < <(bashio::config 'excluded_maps')
fi
export RAIDBRIEF_EXCLUDED_MAPS="${excluded}"
if [ -n "${excluded}" ]; then
    bashio::log.info "Hiding maps: ${excluded}"
fi

if [ -n "${RAIDBRIEF_GEMINI_KEY}" ]; then
    bashio::log.info "Gemini advice enabled (${RAIDBRIEF_GEMINI_MODEL}). Your task progress and level will be sent to Google."
else
    bashio::log.info "Gemini advice disabled (no API key). Only tarkov.dev and TarkovTracker are contacted."
fi

bashio::log.info "Starting Tarkov Raid Brief on :8099 (mode: ${RAIDBRIEF_GAME_MODE}, refresh: ${RAIDBRIEF_REFRESH_MINUTES}m)"

exec python3 -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8099 \
    --app-dir /app \
    --no-server-header \
    --log-level info
