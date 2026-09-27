import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.api import tune
from app.api.routes import router
from app.core import phonetics
from app.models import init_db

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    log = logging.getLogger("misconstrue")
    log.info("%s", config.describe())
    if not config.PRONUNCIATION_DICT.exists():
        log.warning("Pronunciation dictionary not found at %s; planning with CMUdict instead, "
                    "which may not match the aligner. Run `make models`.", config.PRONUNCIATION_DICT)
    init_db()
    phonetics.carrier_index()  # build the word index once, before the first request
    yield


app = FastAPI(title="misconstrue", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router)
app.include_router(tune.router)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}
