# Tarkov Raid Brief

Per-map "what do I bring?" for Escape from Tarkov, driven by your live
TarkovTracker progress. Open it from the sidebar while you're packing.

For each map you get four blocks — **CARRY IN**, **KEYS**, **BRING OUT** and
**DO** — assembled from the tasks you can actually take right now, plus a
ranked **"Run next"** suggestion. Task data comes from tarkov.dev, progress from
TarkovTracker; the add-on is read-only and uses public APIs only. No game
memory reading, no injection, no in-game overlay.

## Setup

1. Get a token at [tarkovtracker.org](https://tarkovtracker.org) →
   **Settings → API Tokens → Create**, with the **`get progression`**
   permission. This add-on never writes, so that's the only one it needs.
2. Paste it into `tarkovtracker_token` below and **Start** the add-on.
3. Set your trader loyalty levels in the **TRADER STANDING** panel at the top
   of the page — the progress API does not expose them. Easiest way: press
   **Use estimate**, which fills the whole roster in from the reputation your
   completed tasks paid out, then correct any trader that reads wrong. They're
   used to hide tasks you can't unlock yet, and roughly half of all tasks
   carry a loyalty requirement, so leaving them all at `1` hides a lot. The
   panel says how many tasks each trader is holding back, so you can see at a
   glance which one is worth levelling.

Without a token the add-on still runs, showing every task as if for a maxed
character, with a banner saying so.

## Options

| Option | Default | Meaning |
|---|---|---|
| `tarkovtracker_token` | — | Your API token with `get progression`. |
| `game_mode` | `regular` | `regular` (PvP) or `pve`. Selects both the task set and which progress to read. |
| `refresh_minutes` | `60` | Background poll interval for TarkovTracker (5–1440). Never faster than once a minute. |
| `kappa_only` | `false` | Show only Kappa-required tasks. Also toggleable in the UI. Ignored while tarkov.dev's `kappaRequired` flag is degraded — the add-on says so on screen. |
| `trader_levels.*` | `1` | Starting loyalty level 1–4 per trader. Once you use the TRADER STANDING panel it takes over and these become the value **Reset** goes back to. |
| `excluded_maps` | `[]` | Maps to hide entirely, e.g. `Icebreaker`. Hidden before ranking, so they can't win "Run next". |
| `gemini_api_key` | — | Optional. Enables AI route advice. Empty = no AI and no third-party calls. |
| `gemini_model` | `gemini-2.5-flash` | Which Gemini model writes the advice. The flash models have a free tier. |

## "It's showing tasks I can't take"

Look for a **dot** beside the task name.

The 1.x trader rework gates much of the task tree behind per-trader
progression, carried in the data as `otherRequirements`. 173 of the 516 live
tasks have one — more than have a trader loyalty requirement. Nothing
publishes how far along each trader you are: TarkovTracker's progress API
returns tasks, objectives, hideout, level, edition and faction and no global
variables, and the 27 variable ids appear nowhere in the data overlay or in
TarkovTracker's own task feed.

So the add-on cannot check those gates. It lists the task and marks it, rather
than hiding something you might be able to take. A dotted task that is missing
in game is that gate.

## Trader standing

The panel above the map list holds the one thing neither upstream can tell us:
what each trader thinks of you. tarkov.dev knows what a task *demands* and
TarkovTracker knows which tasks you've finished, but nothing exposes your own
loyalty level, so you set it here.

- **Loyalty level** — click a pip. The brief rebuilds immediately, and the
  count beside each trader is how many otherwise-ready tasks that trader alone
  is holding back.
- **Reputation** — offered for the traders some task actually compares
  reputation against, which today is Fence and Lightkeeper. It stays blank and
  unenforced until you fill it in: the Fence "Compensation for Damage" chain
  wants your standing *below* a threshold, so guessing at 0.00 would hide
  tasks in one direction or the other on a number you never gave.
- **Use estimate** — each trader shows `est 2.70 → LL3`, added up from the
  reputation the tasks you've completed paid out; the button applies the lot.
  It's a suggestion, not a reading: loyalty also needs roubles spent with the
  trader, which no API reports, and EOD/Unheard start above zero reputation —
  so it can read one tier high. Fence is left out entirely, since their
  standing comes from scav karma rather than tasks. Applying it just writes
  normal overrides, so you can fix any trader afterwards by clicking a pip.
- **Reset** goes back to the `trader_levels` in the Configuration tab.

Your answers live in `/data/standing.json` and survive restarts and updates.

## AI route advice (optional)

Off unless you set `gemini_api_key`. It adds a per-map route briefing and a
one-line explanation of the "Run next" pick, and:

- **only generates when you press the button** — never on startup, on the
  poller, or on page load, so it cannot burn quota unattended. Answers are
  cached against your current tasks; *Regenerate* forces a fresh call.
- **can never touch your packing lists.** The advice sits in a labelled block
  below CARRY IN / KEYS / BRING OUT and cannot alter them, so a hallucinated
  key can't end up on your checklist. The lists come from live game data only.

The "Run next" ranking itself is not AI — it's a deterministic score shown with
its breakdown on screen. Note that enabling this sends your task progress and
player level to Google; leave the key empty to keep the add-on talking to
tarkov.dev and TarkovTracker only.

## Using it

- Pick a map from the dropdown at the top; the count next to each name is how
  many tasks you have available there.
- **CARRY IN** is the primary block — tick items off as you pack. Ticks are
  saved per map in your browser and survive reloads. **clear** resets them.
- **KEYS** items are also carry-in; they're separated because they live in your
  secure container.
- **BRING OUT** is what you're looting, with `(FiR)` marked where the item must
  be Found In Raid.
- **EXTRACTS** lists every exit a PMC can use on that map. An exit a task
  specifically asks for is pulled to the front and highlighted; `⌁` means the
  exit needs a switch thrown first. Scav-only exfils aren't listed. Underneath
  it, boss spawn chances; in the map header, raid length and lobby size.
- Each task links to its wiki page; each map links to the tarkov.dev map.

## Notes

- A task with objectives on several maps appears under each map, showing only
  that map's objectives.
- Objectives you've already completed are dropped, along with the keys and map
  placements they justified, so a task you're part-way through shows only what
  is left. Counted objectives show the remainder: `Bandage x3 (2/5 done)`.
  This needs a token; without one every objective is listed.
- Tasks with no map anywhere are grouped under **Any map**.
- Task data is cached for 24 hours and survives restarts. If tarkov.dev is
  unreachable you get the cached copy plus a staleness banner.
- Objectives that aren't raid activities (trader loyalty, skills, player level)
  are hidden, unless they need a key.
- Availability matches TarkovTracker, which means tarkov.dev's raw data is
  corrected by the same community `tarkov-data-overlay` the tracker uses —
  most trader loyalty gates live there rather than in the API, along with the
  32 quests BSG has retired. It refreshes hourly.
- Traders you haven't met hide their whole task list: the BTR Driver until
  A Helping Hand is done, the Lightkeeper until Getting Acquainted is.
- Prestige-only tasks never show, since the progress API reports no prestige
  level.

## Troubleshooting

| Banner | What to do |
|---|---|
| *TarkovTracker rejected the token (401)* | Re-copy the token; confirm it has `get progression`. |
| *TarkovTracker rate-limited us (429)* | Raise `refresh_minutes`. Data shown is the last good copy. |
| *tarkov.dev could not be reached* | Nothing to do; cached data is being served. It'll recover on its own. |
| *tarkov.dev rejected part of the query* | The schema changed. The add-on dropped the named block and kept going; some detail (often KEYS) is missing until it's updated. |
| *Could not reach tarkov.dev on either the JSON or GraphQL API* | Both sources failed and there's no cache yet. Check the add-on has internet access, then hit Refresh. |
| *The tarkov-data-overlay could not be fetched* | GitHub was unreachable. The list will show some tasks you can't take (loyalty gates live in the overlay, not the API) until it recovers. |
| *Every trader is configured at loyalty level 1* | Set your real levels in the TRADER STANDING panel; until you do, everything gated behind LL2–4 is hidden. |
| *N tasks below also need trader progression* | Nothing to do — those tasks carry a 1.x gate nobody publishes your side of, so they're listed with a dot instead of being vouched for. If a dotted task is missing in game, that gate is why. |
| *TarkovTracker accepted the token but reports no completed tasks* | Wrong `game_mode` (it defaults to `regular` = PVP), or the token belongs to a different TarkovTracker account than the one you browse. Run `tools/tracker-doctor.py` to see both modes. |
| *"Kappa only" is off because …* | Nothing to do. tarkov.dev's `kappaRequired` flag is degraded upstream; filtering on it would hide most of what Kappa needs, so the filter is ignored until it recovers. |

Task data comes from `json.tarkov.dev`; the GraphQL API has been down since
2026-07-21 and is used only as a fallback. See the repository README for detail.

For deeper debugging, expose port `8099` in the **Network** tab and hit
`/health`, `/api/brief` and `POST /api/refresh` directly.
