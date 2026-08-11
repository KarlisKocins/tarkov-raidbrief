# Contributing

Thanks for taking a look. This is a small single-add-on repository, so the
process is deliberately light.

## Reporting a bug

[Open an issue](https://github.com/KarlisKocins/tarkov-raidbrief/issues/new/choose).
For "the brief shows a task I can't take", the add-on version, your player level
and your real trader loyalty levels are what make it reproducible — availability
depends on all three.

**Never paste your TarkovTracker token or Gemini API key** into an issue.

If the wrong thing is the *task data itself* (a name, XP value, or a trader
loyalty requirement), the fix usually belongs in
[tarkov-data-overlay](https://github.com/tarkovtracker-org/tarkov-data-overlay)
rather than here — this add-on applies that overlay and inherits its
corrections automatically.

## Working on the code

The frontend has no build step and no framework: `app/static/app.css`,
`app/static/app.js` and one Jinja template. The backend is FastAPI. Keeping it
that way is intentional.

```bash
pip install -r tarkov_raidbrief/requirements.txt graphql-core

# Offline: every rung of the GraphQL query fallback ladder is a valid document.
python3 tests/test_query_validates.py

# Live: every objective type in the task dump is explicitly classified.
python3 tests/test_objective_coverage.py
```

Running the add-on outside Home Assistant, and building the image locally, are
both covered in the [README](README.md#development).

Two constraints worth knowing before you change the frontend or the server:

- **All frontend URLs must stay relative.** Ingress serves the add-on under a
  generated path prefix, so an absolute `/static/app.css` 404s inside Home
  Assistant while working fine on the direct port. Do not set Starlette's
  `root_path` from `X-Ingress-Path` — the README explains why it breaks every
  static asset while still rendering the HTML.
- **AI output must never reach the packing lists.** CARRY IN / KEYS / BRING OUT
  come from live game data only. Route advice stays in its labelled block.

## Pull requests

- One topic per PR, based on `main`.
- Don't bump `version` in `tarkov_raidbrief/config.yaml` in a PR — that's what
  triggers a release build, and it's done at merge time.
- If the change is user-visible, add a `CHANGELOG.md` entry. There are two
  copies (the root one and `tarkov_raidbrief/CHANGELOG.md`, shown in Home
  Assistant); they're kept identical.
- New task-data assumptions should come with a test if there's a plausible way a
  game patch could invalidate them. That's what both existing tests are for.
