# Security policy

## Supported versions

The latest released version is the only supported one. Update through the Home
Assistant Add-on Store (**⋮ → Check for updates**).

## Reporting a vulnerability

Please **do not open a public issue** for a security problem. Use GitHub's
[private vulnerability reporting](https://github.com/KarlisKocins/tarkov-raidbrief/security/advisories/new),
or email <kocins36@gmail.com>. Expect a reply within a few days.

## What this add-on handles

Worth knowing when judging whether something is a security issue:

- **Your TarkovTracker API token** is stored in the add-on's options by Home
  Assistant and sent only to `api.tarkovtracker.org`. It is declared as a `password`
  option, so the UI masks it. The add-on requests read-only progression access
  and never writes back.
- **Your Gemini API key**, if set, is sent only to Google's Generative Language
  API, and only when you press the advice button. Leaving it empty disables all
  AI features and every third-party call.
- **Outbound network access from the add-on** is limited to `json.tarkov.dev`,
  `api.tarkov.dev`, `api.tarkovtracker.org`, `raw.githubusercontent.com` (the
  community data overlay) and — only with a key configured —
  `generativelanguage.googleapis.com`. There is no telemetry, no analytics and no
  account system. The page also renders plain outbound links to tarkov.dev and
  the wiki, which only your browser follows, and only if you click them.
- **On-disk state** lives in the add-on's `/data`: the task cache, the last good
  progress snapshot and the cached overlay.
- **Ingress** is the intended entry point, and it inherits Home Assistant's
  authentication. Port `8099` is unauthenticated by design and unpublished by
  default — if you expose it, treat it as anyone-on-your-LAN readable.

A report that the add-on reads game memory, injects into the game, or automates
input is a bug in the report: it does none of those things and it is a stated
non-goal.
