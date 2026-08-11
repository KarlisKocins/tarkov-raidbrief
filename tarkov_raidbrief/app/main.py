"""FastAPI entrypoint for the Tarkov Raid Brief add-on.

Ingress note - this is the part that bites.

Home Assistant serves the add-on under a generated prefix and announces it in
the `X-Ingress-Path` header, but it *strips that prefix before proxying*, so
requests arrive here as plain `/`, `/static/app.css`, `/api/brief`.

This app therefore solves ingress purely with **relative URLs** in the frontend
(`static/app.css`, `fetch("api/brief")` - no leading slashes anywhere), which
resolve correctly under the ingress prefix and on the direct port alike.

It deliberately does NOT set Starlette's `root_path` from that header, which is
the obvious-looking alternative and is actively broken here: `Mount` appends
`/static` to `root_path` and then strips the combined prefix from the request
path. Since HA already stripped it, the path is just `/static/app.css`, the
strip does not match, and every static asset 404s - while the HTML itself still
renders, so it fails as an unstyled page rather than an obvious error. Verified
by reproducing it. Set `root_path` only if you also stop stripping.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .brief import build_brief, filter_brief
from .models import Brief, PlayerInfo, Settings, Warning_
from .tarkovdev import CACHE_TTL, TarkovDev, TarkovDevError
from .tracker import Tracker, TrackerAuthError, TrackerRateLimited, TrackerUnavailable

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("raidbrief")

HERE = Path(__file__).parent


class State:
    """Everything the request handlers read. Mutated only by the poller."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.tarkovdev = TarkovDev(settings.data_dir / "tasks.json", settings.game_mode)
        self.tracker = Tracker(
            settings.token,
            settings.tracker_game_mode,
            settings.data_dir / "progress.json",
        )
        self.tasks: list[dict] = []
        self.tasks_fetched: float | None = None
        self.tracker_warning: Warning_ | None = None
        self.tasks_warning: Warning_ | None = None
        self.lock = asyncio.Lock()

    # -- upstream refresh --------------------------------------------------

    async def refresh_tasks(self, force: bool = False) -> None:
        try:
            self.tasks, self.tasks_fetched, _ = await self.tarkovdev.get_tasks(force=force)
            self.tasks_warning = None
        except TarkovDevError as exc:
            log.error("Could not load tasks: %s", exc)
            self.tasks_warning = Warning_(
                "upstream",
                f"tarkov.dev is unreachable and there is no cached task data yet. {exc}",
            )

    async def refresh_progress(self) -> None:
        if not self.settings.token:
            return
        try:
            await self.tracker.fetch()
            self.tracker_warning = None
        except TrackerAuthError as exc:
            log.error("%s", exc)
            self.tracker_warning = Warning_("auth", str(exc))
        except TrackerRateLimited as exc:
            log.warning("%s", exc)
            self.tracker_warning = Warning_("ratelimit", str(exc))
        except TrackerUnavailable as exc:
            log.warning("TarkovTracker unavailable: %s", exc)
            self.tracker_warning = Warning_(
                "upstream", f"TarkovTracker is unreachable: {exc}"
            )

    async def refresh_all(self, force: bool = False) -> None:
        async with self.lock:
            await self.refresh_tasks(force=force)
            await self.refresh_progress()

    # -- brief -------------------------------------------------------------

    def current_brief(self, kappa_only: bool | None = None) -> Brief:
        settings = self.settings
        kappa = settings.kappa_only if kappa_only is None else kappa_only
        statuses = self.tracker.statuses()
        has_token = bool(settings.token)

        maps = build_brief(
            self.tasks,
            statuses,
            self.tracker.player_level if has_token else 99,
            self.tracker.faction if has_token else "USEC",
            settings.trader_levels,
            kappa_only=kappa,
        )

        warnings: list[Warning_] = []
        if self.tasks_warning:
            warnings.append(self.tasks_warning)
        if self.tracker_warning:
            warnings.append(self.tracker_warning)
        if not has_token:
            warnings.append(Warning_(
                "auth",
                "No TarkovTracker token configured - showing every task as if for a "
                "fresh level 99 character. Add a token in the add-on Configuration tab.",
            ))
        if self.tarkovdev.serving_stale or (
            self.tasks_fetched and (time.time() - self.tasks_fetched) > CACHE_TTL
        ):
            age = _age(time.time() - self.tasks_fetched) if self.tasks_fetched else "unknown age"
            warnings.append(Warning_(
                "stale",
                f"tarkov.dev could not be reached, so this is cached task data from "
                f"{age}. Everything still works; it just will not pick up a new patch "
                f"until the API is back.",
            ))
        if self.tarkovdev.dropped_blocks:
            dropped = ", ".join(self.tarkovdev.dropped_blocks)
            detail = (" The KEYS section may be incomplete."
                      if "requiredKeys" in self.tarkovdev.dropped_blocks else "")
            warnings.append(Warning_(
                "degraded",
                f"tarkov.dev rejected part of the query, so some detail is "
                f"missing: {dropped}.{detail}",
            ))

        now = time.time()
        return Brief(
            maps=maps,
            player=PlayerInfo(
                name=self.tracker.display_name if has_token else "no token",
                level=self.tracker.player_level if has_token else 0,
                faction=self.tracker.faction if has_token else "-",
                tasks_complete=sum(1 for s in statuses.values() if s == "complete"),
                has_token=has_token,
            ),
            warnings=warnings,
            tasks_age_seconds=(now - self.tasks_fetched) if self.tasks_fetched else None,
            progress_age_seconds=(
                (now - self.tracker.fetched_at) if self.tracker.fetched_at else None
            ),
            game_mode=settings.game_mode,
            kappa_only=kappa,
            dropped_blocks=list(self.tarkovdev.dropped_blocks),
            generated_at=now,
        )


async def poller(state: State) -> None:
    """Background refresh loop. Nothing is ever fetched on a page load."""
    interval = max(60, state.settings.refresh_minutes * 60)
    while True:
        try:
            await asyncio.sleep(interval)
            log.debug("Background refresh")
            await state.refresh_all()
        except asyncio.CancelledError:
            raise
        except Exception:  # a poller that dies takes the whole app stale with it
            log.exception("Background refresh failed; continuing")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    log.info(
        "Settings: mode=%s refresh=%dm kappa_only=%s token=%s",
        settings.game_mode, settings.refresh_minutes, settings.kappa_only,
        "set" if settings.token else "MISSING",
    )
    log.info("Trader levels: %s",
             ", ".join(f"{k} {v}" for k, v in settings.trader_levels.items()))

    state = State(settings)
    app.state.brief_state = state

    await state.refresh_all()
    task = asyncio.create_task(poller(state))
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Tarkov Raid Brief",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
)

app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=str(HERE / "templates"))


def _age(seconds: float | None) -> str:
    """Render a data age compactly enough for the header strip."""
    if seconds is None:
        return "never"
    seconds = int(seconds)
    if seconds < 90:
        return f"{seconds}s ago"
    if seconds < 5400:
        return f"{seconds // 60}m ago"
    if seconds < 172800:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


templates.env.filters["age"] = _age


def _state(request: Request) -> State:
    return request.app.state.brief_state


@app.get("/health")
async def health(request: Request) -> JSONResponse:
    """Liveness only - deliberately makes no upstream calls."""
    state = _state(request)
    return JSONResponse({
        "status": "ok",
        "tasks_loaded": len(state.tasks),
        "tasks_age_seconds": (
            round(time.time() - state.tasks_fetched) if state.tasks_fetched else None
        ),
        "progress_age_seconds": (
            round(time.time() - state.tracker.fetched_at)
            if state.tracker.fetched_at else None
        ),
        "has_token": bool(state.settings.token),
        "game_mode": state.settings.game_mode,
    })


@app.get("/api/brief")
async def api_brief(
    request: Request,
    map: str | None = Query(None, description="Filter to one map, e.g. customs"),
    kappa_only: bool | None = Query(None),
) -> JSONResponse:
    brief = _state(request).current_brief(kappa_only=kappa_only)
    return JSONResponse(asdict(filter_brief(brief, map)))


@app.post("/api/refresh")
async def api_refresh(request: Request) -> JSONResponse:
    """Force-refresh both upstreams and bust the task cache."""
    state = _state(request)
    await state.refresh_all(force=True)
    brief = state.current_brief()
    return JSONResponse({
        "status": "ok",
        "tasks_loaded": len(state.tasks),
        "warnings": [asdict(w) for w in brief.warnings],
    })


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    kappa_only: bool | None = Query(None),
    map: str | None = Query(None),
) -> HTMLResponse:
    """The whole page, server-rendered. Never touches an upstream."""
    brief = filter_brief(_state(request).current_brief(kappa_only=kappa_only), map)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"brief": brief},
    )
