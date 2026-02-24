#!/usr/bin/env python3
"""
Bot de Download de Vídeos — FastAPI + yt-dlp + SSE
"""

import asyncio
import json
import os
import uuid
from datetime import datetime
from pathlib import Path

import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

DOWNLOADS_DIR = Path(os.getenv("DOWNLOADS_DIR", "/downloads"))
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Video Downloader Bot", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_jobs: dict[str, dict] = {}


class DownloadRequest(BaseModel):
    url: str
    quality: str = "best"  # best | 1080p | 720p | 480p | audio


def _build_ydl_opts(quality: str, outdir: Path, progress_hook) -> dict:
    tmpl = str(outdir / "video.%(ext)s")
    common = {
        "outtmpl": tmpl,
        "progress_hooks": [progress_hook],
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    if quality == "audio":
        return {
            **common,
            "format": "bestaudio/best",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
        }
    fmt_map = {
        "1080p": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]/best",
        "720p": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]/best",
        "480p": "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]/best",
        "best": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
    }
    return {
        **common,
        "format": fmt_map.get(quality, fmt_map["best"]),
        "merge_output_format": "mp4",
    }


async def _run_download(job_id: str, url: str, quality: str):
    job = _jobs[job_id]
    job["status"] = "running"
    job["started_at"] = datetime.utcnow().isoformat() + "Z"

    outdir = DOWNLOADS_DIR / job_id
    outdir.mkdir(parents=True, exist_ok=True)

    def progress_hook(d: dict):
        if d["status"] == "downloading":
            job["progress"].update(
                {
                    "percent": d.get("_percent_str", "0%").strip(),
                    "speed": d.get("_speed_str", "—").strip(),
                    "eta": d.get("_eta_str", "—").strip(),
                    "total": d.get(
                        "_total_bytes_str", d.get("_total_bytes_estimate_str", "—")
                    ).strip(),
                }
            )
        elif d["status"] == "finished":
            job["progress"]["percent"] = "100%"

    try:
        opts = _build_ydl_opts(quality, outdir, progress_hook)
        loop = asyncio.get_event_loop()

        def blocking():
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                job["title"] = info.get("title", "Sem título")
                job["thumbnail"] = info.get("thumbnail", "")
                job["duration"] = info.get("duration", 0)
                job["uploader"] = info.get("uploader", "")
                ydl.download([url])

        await loop.run_in_executor(None, blocking)

        files = sorted(
            outdir.glob("video.*"),
            key=lambda f: f.stat().st_size,
            reverse=True,
        )
        if not files:
            raise RuntimeError("Nenhum arquivo gerado após o download")

        vf = files[0]
        job.update(
            {
                "status": "done",
                "file": str(vf),
                "filename": vf.name,
                "filesize": vf.stat().st_size,
                "finished_at": datetime.utcnow().isoformat() + "Z",
            }
        )

    except Exception as exc:
        job.update(
            {
                "status": "error",
                "error": str(exc),
                "finished_at": datetime.utcnow().isoformat() + "Z",
            }
        )


# ── Endpoints ────────────────────────────────────────────────────────────────


@app.post("/api/jobs/download", status_code=201)
async def create_job(req: DownloadRequest):
    jid = uuid.uuid4().hex[:8]
    _jobs[jid] = {
        "id": jid,
        "url": req.url,
        "quality": req.quality,
        "status": "queued",
        "progress": {"percent": "0%", "speed": "—", "eta": "—", "total": "—"},
        "title": "",
        "thumbnail": "",
        "duration": 0,
        "uploader": "",
        "file": None,
        "filename": None,
        "filesize": None,
        "error": None,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "started_at": None,
        "finished_at": None,
    }
    asyncio.create_task(_run_download(jid, req.url, req.quality))
    return {"id": jid, "status": "queued"}


@app.get("/api/jobs")
async def list_jobs():
    return sorted(_jobs.values(), key=lambda j: j["created_at"], reverse=True)


@app.get("/api/jobs/{jid}")
async def get_job(jid: str):
    if jid not in _jobs:
        raise HTTPException(404, "Job não encontrado")
    return _jobs[jid]


@app.get("/api/jobs/{jid}/stream")
async def stream_progress(jid: str):
    """Server-Sent Events — progresso em tempo real"""
    if jid not in _jobs:
        raise HTTPException(404, "Job não encontrado")

    async def sse():
        while True:
            j = _jobs[jid]
            payload = {
                k: j[k]
                for k in (
                    "status",
                    "progress",
                    "title",
                    "thumbnail",
                    "filename",
                    "error",
                )
            }
            yield f"data: {json.dumps(payload)}\n\n"
            if j["status"] in ("done", "error"):
                break
            await asyncio.sleep(0.4)

    return StreamingResponse(
        sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/jobs/{jid}/download-file")
async def serve_file(jid: str):
    if jid not in _jobs:
        raise HTTPException(404, "Job não encontrado")
    j = _jobs[jid]
    if j["status"] != "done":
        raise HTTPException(400, f"Job ainda não concluído: {j['status']}")
    path = Path(j["file"])
    if not path.exists():
        raise HTTPException(404, "Arquivo não encontrado no servidor")
    mt = "audio/mpeg" if path.suffix == ".mp3" else "video/mp4"
    return FileResponse(str(path), filename=j["filename"], media_type=mt)


# Serve frontend estático
app.mount("/", StaticFiles(directory="static", html=True), name="static")
