"""A small single-worker SpotDL download queue for a private tailnet."""

import asyncio
from collections import deque
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
import re
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

jobs: dict[str, dict] = {}
queue: asyncio.Queue[str] = asyncio.Queue()
MAX_QUEUED = 10
MAX_HISTORY = 50
LOG_LIMIT = 120
MUSIC_DIR = Path("/music")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_spotify_url(raw: str) -> str:
    """Accept only public Spotify track/album/playlist URLs; discard tracking params."""
    try:
        u = urlsplit(raw.strip())
        if u.scheme != "https" or u.hostname != "open.spotify.com":
            raise ValueError("Only open.spotify.com links are supported")
        if u.username or u.password or u.port:
            raise ValueError("Unexpected URL credentials or port")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    parts = [piece for piece in u.path.split("/") if piece]
    # Spotify sometimes prefixes shared URLs with a locale path.
    if len(parts) == 3 and re.fullmatch(r"intl-[a-z]{2}", parts[0]):
        parts.pop(0)
    if (len(parts) != 2 or parts[0] not in {"track", "album", "playlist"}
            or not re.fullmatch(r"[A-Za-z0-9]{22}", parts[1])):
        raise HTTPException(
            status_code=422,
            detail="Paste a full open.spotify.com track, album, or playlist URL",
        )
    return f"https://open.spotify.com/{parts[0]}/{parts[1]}"


def view(job: dict) -> dict:
    return {
        "id": job["id"], "url": job["url"], "status": job["status"],
        "created": job["created"], "updated": job["updated"],
        "return_code": job["return_code"], "logs": list(job["logs"]),
    }


def append_logs(job: dict, chunk: bytes) -> None:
    # tqdm and other CLI tools use carriage returns to update progress.
    text = chunk.decode("utf-8", errors="replace")
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    for line in text.replace("\r", "\n").splitlines():
        if line.strip():
            job["logs"].append(line[:500])


async def worker() -> None:
    while True:
        job_id = await queue.get()
        process = None
        try:
            job = jobs[job_id]
            job["status"] = "running"
            job["updated"] = now()
            job["logs"].append("Starting SpotDL download...")
            process = await asyncio.create_subprocess_exec(
                "spotdl", "download", job["url"],
                "--format", "mp3",
                "--output", "{artist}/{album}/{title}.{output-ext}",
                "--overwrite", "skip",
                cwd=str(MUSIC_DIR),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            assert process.stdout is not None
            while data := await process.stdout.read(2048):
                append_logs(job, data)
                job["updated"] = now()
            job["return_code"] = await process.wait()
            job["status"] = "completed" if job["return_code"] == 0 else "failed"
            job["logs"].append(
                "Completed. Navidrome will index the new files on its next scan."
                if job["return_code"] == 0 else
                f"SpotDL exited with code {job['return_code']}. Check logs above."
            )
            job["updated"] = now()
        except asyncio.CancelledError:
            if process is not None and process.returncode is None:
                process.terminate()
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(process.wait(), timeout=5)
                if process.returncode is None:
                    process.kill()
                    await process.wait()
            raise
        except Exception as exc:
            if job_id in jobs:
                jobs[job_id]["status"] = "failed"
                jobs[job_id]["logs"].append(f"Application error: {exc}")
                jobs[job_id]["updated"] = now()
        finally:
            queue.task_done()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(worker())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="Homelab Music Downloader", docs_url=None, redoc_url=None,
              openapi_url=None, lifespan=lifespan)


@app.middleware("http")
async def private_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


class DownloadRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


@app.get("/")
async def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html", media_type="text/html")


@app.get("/api/jobs")
async def get_jobs():
    return [view(job) for job in reversed(list(jobs.values()))]


@app.post("/api/jobs", status_code=202)
async def create_job(request: DownloadRequest):
    url = validate_spotify_url(request.url)
    active = sum(job["status"] in ("queued", "running") for job in jobs.values())
    if active >= MAX_QUEUED:
        raise HTTPException(status_code=429, detail="Queue is full. Try again later.")

    # Keep recent completed history in memory; no credentials or data stored on disk.
    for key in list(jobs):
        if len(jobs) < MAX_HISTORY:
            break
        if jobs[key]["status"] not in ("queued", "running"):
            del jobs[key]

    job_id = uuid4().hex[:12]
    job = {
        "id": job_id, "url": url, "status": "queued", "created": now(),
        "updated": now(), "return_code": None, "logs": deque(maxlen=LOG_LIMIT),
    }
    jobs[job_id] = job
    await queue.put(job_id)
    return view(job)
