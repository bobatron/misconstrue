import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.api import tune
from app.api.routes import router
from app.core import aligner, phonetics, verify_read
from app.models import init_db
from app.worker import worker

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
    # Load the speech model and the aligner's dictionary on the worker thread, so the server
    # answers straight away and the first upload (queued behind this) doesn't pay for them.
    worker.submit(_warm_up)
    yield


def _warm_up() -> None:
    log = logging.getLogger("misconstrue")
    start = time.perf_counter()
    try:
        verify_read._whisper()
        if config.PRONUNCIATION_DICT.exists():
            aligner._dictionary_lines(config.PRONUNCIATION_DICT)
        log.info("Speech models ready in %.1fs", time.perf_counter() - start)
    except Exception:
        log.exception("Warming up the speech models failed; they'll load on the first upload instead")


app = FastAPI(title="misconstrue", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router)
app.include_router(tune.router)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}
