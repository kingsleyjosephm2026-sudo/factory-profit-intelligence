import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import sessionmaker

from .config import get_settings
from .database import SessionLocal
from .routers import actions, analytics, data, meta
from .services.simulator import Simulator

log = logging.getLogger("fpi")


def create_app(session_factory: sessionmaker | None = None) -> FastAPI:
    cfg = get_settings()
    logging.basicConfig(level=cfg.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sf = session_factory or SessionLocal
    sim = Simulator(sf, cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if cfg.sim_autostart:
            sim.start()
        task = asyncio.create_task(sim.run_forever())
        yield
        task.cancel()

    app = FastAPI(
        title="Factory Profit Intelligence API", version="1.0.0", lifespan=lifespan,
        description="SIMULATED DEMO DATA by default. Not production-hardened: no authentication, intended for local use.",
    )
    app.state.session_factory = sf
    app.state.simulator = sim
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in cfg.cors_origins.split(",") if o.strip()], allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["*"])
    for r in (meta.router, analytics.router, actions.router, data.router):
        app.include_router(r)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):  # never leak internals or secrets
        log.exception("Unhandled error on %s", request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error. Check the server log for details."})

    return app


app = create_app()
