# Tarkov Raid Brief

Per-map "what do I bring?" for Escape from Tarkov, driven by your live
TarkovTracker progress. Open it from the sidebar while you're packing.

## Setup

1. Get a token at [tarkovtracker.org](https://tarkovtracker.org) →
   **Settings → API Tokens → Create**, with the **`get progression`**
   permission. This add-on never writes, so that's the only one it needs.
2. Paste it into `tarkovtracker_token` below and **Start** the add-on.
3. Set your trader loyalty levels under `trader_levels` — the progress API does
   not expose them, so they have to be entered by hand. They're used to hide
   tasks you can't unlock yet.

Without a token the add-on still runs, showing every task as if for a maxed
character, with a banner saying so.

## Options

| Option | Meaning |
|---|---|
| `tarkovtracker_token` | Your API token with `get progression`. |
| `game_mode` | `regular` or `pve`. Selects both the task set and which progress to read. |
| `refresh_minutes` | Background poll interval for TarkovTracker (5–1440). Never faster than once a minute. |
| `kappa_only` | Show only Kappa-required tasks. Also toggleable in the UI. |
| `trader_levels.*` | Loyalty level 1–4 per trader. |

## Using it

- Pick a map from the dropdown at the top; the count next to each name is how
  many tasks you have available there.
- **CARRY IN** is the primary block — tick items off as you pack. Ticks are
  saved per map in your browser and survive reloads. **clear** resets them.
- **KEYS** items are also carry-in; they're separated because they live in your
  secure container.
- **BRING OUT** is what you're looting, with `(FiR)` marked where the item must
  be Found In Raid.
- Each task links to its wiki page; each map links to the tarkov.dev map.

## Notes

- A task with objectives on several maps appears under each map, showing only
  that map's objectives.
- Tasks with no map anywhere are grouped under **Any map**.
- Task data is cached for 24 hours and survives restarts. If tarkov.dev is
  unreachable you get the cached copy plus a staleness banner.
- Objectives that aren't raid activities (trader loyalty, skills, player level)
  are hidden, unless they need a key.

## Troubleshooting

| Banner | What to do |
|---|---|
| *TarkovTracker rejected the token (401)* | Re-copy the token; confirm it has `get progression`. |
| *TarkovTracker rate-limited us (429)* | Raise `refresh_minutes`. Data shown is the last good copy. |
| *tarkov.dev could not be reached* | Nothing to do; cached data is being served. It'll recover on its own. |
| *tarkov.dev rejected part of the query* | The schema changed. The add-on dropped the named block and kept going; some detail (often KEYS) is missing until it's updated. |
| *Could not reach tarkov.dev on either the JSON or GraphQL API* | Both sources failed and there's no cache yet. Check the add-on has internet access, then hit Refresh. |

Task data comes from `json.tarkov.dev`; the GraphQL API has been down since
2026-07-21 and is used only as a fallback. See the repository README for detail.

For deeper debugging, expose port `8099` in the **Network** tab and hit
`/health`, `/api/brief` and `POST /api/refresh` directly.
