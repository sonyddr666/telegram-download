#!/usr/bin/env python3
import ipaddress
import logging
import os
import re
import secrets
import shutil
import socket
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from flask import Flask, abort, jsonify, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

app = Flask(__name__)

DOWNLOADS_DIR = Path(os.getenv("WEB_DOWNLOADS_DIR", "/downloads/web"))
WEB_ACCESS_TOKEN = os.getenv("WEB_ACCESS_TOKEN", "").strip()
MAX_CONCURRENT_DOWNLOADS = max(
    1, int(os.getenv("WEB_MAX_CONCURRENT_DOWNLOADS", "1") or "1")
)
MAX_FILE_SIZE = int(
    os.getenv("WEB_MAX_FILE_SIZE", str(2 * 1024 * 1024 * 1024))
)
JOB_TTL_SECONDS = max(
    300, int(os.getenv("WEB_JOB_TTL_SECONDS", "3600") or "3600")
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()
download_slots = threading.Semaphore(MAX_CONCURRENT_DOWNLOADS)
ansi_pattern = re.compile(r"\x1b\[[0-9;]*m")


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_text(value: object, default: str = "") -> str:
    if value is None:
        return default
    return ansi_pattern.sub("", str(value)).strip()


def request_token() -> str:
    return (
        request.headers.get("X-Access-Token", "").strip()
        or request.args.get("token", "").strip()
    )


def require_access() -> None:
    if WEB_ACCESS_TOKEN and not secrets.compare_digest(
        request_token(), WEB_ACCESS_TOKEN
    ):
        abort(401, description="Chave de acesso inválida")


def public_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        if parsed.username or parsed.password:
            return False

        hostname = parsed.hostname.lower().rstrip(".")
        if hostname == "localhost" or hostname.endswith(".local"):
            return False

        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
        if not addresses:
            return False

        for entry in addresses:
            address = ipaddress.ip_address(entry[4][0])
            if not address.is_global:
                return False

        return True
    except (OSError, ValueError):
        return False


def format_options(quality: str, directory: Path, progress_hook) -> dict:
    common = {
        "outtmpl": str(directory / "%(title).180B [%(id)s].%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "continuedl": True,
        "concurrent_fragment_downloads": 4,
        "progress_hooks": [progress_hook],
        "postprocessor_hooks": [progress_hook],
        "restrictfilenames": False,
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

    formats = {
        "best": "bv*+ba/b",
        "1080p": "bv*[height<=1080]+ba/b[height<=1080]",
        "720p": "bv*[height<=720]+ba/b[height<=720]",
        "480p": "bv*[height<=480]+ba/b[height<=480]",
    }

    return {
        **common,
        "format": formats.get(quality, formats["best"]),
        "merge_output_format": "mp4",
    }


def update_job(job_id: str, **values) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return
        job.update(values)
        job["updated_at"] = utc_iso()
        job["updated_ts"] = time.time()


def download_worker(job_id: str) -> None:
    with jobs_lock:
        job = dict(jobs[job_id])

    directory = Path(job["directory"])
    directory.mkdir(parents=True, exist_ok=True)

    def progress_hook(data: dict) -> None:
        status = data.get("status")

        if status == "downloading":
            downloaded = int(data.get("downloaded_bytes") or 0)
            total = int(
                data.get("total_bytes")
                or data.get("total_bytes_estimate")
                or 0
            )
            progress = round(downloaded * 100 / total, 1) if total else 0.0
            update_job(
                job_id,
                status="downloading",
                progress=max(0.0, min(progress, 99.9)),
                downloaded_bytes=downloaded,
                total_bytes=total,
                speed=clean_text(data.get("_speed_str"), "Calculando..."),
                eta=clean_text(data.get("_eta_str"), "Calculando..."),
                message="Baixando mídia...",
            )
        elif status == "finished":
            update_job(
                job_id,
                status="processing",
                progress=100.0,
                speed="",
                eta="",
                message="Convertendo e preparando o arquivo...",
            )
        elif status == "processing":
            update_job(
                job_id,
                status="processing",
                progress=100.0,
                message="Processando com FFmpeg...",
            )

    try:
        update_job(
            job_id,
            status="queued",
            message="Aguardando uma vaga na fila...",
        )

        with download_slots:
            update_job(
                job_id,
                status="starting",
                message="Analisando o link...",
            )

            options = format_options(job["quality"], directory, progress_hook)
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(job["url"], download=True)

            title = clean_text(info.get("title"), "Arquivo baixado")
            update_job(job_id, title=title)

            generated_files = [
                path
                for path in directory.iterdir()
                if path.is_file()
                and not path.name.endswith((".part", ".ytdl", ".temp"))
            ]
            if not generated_files:
                raise RuntimeError("O yt-dlp não gerou nenhum arquivo")

            media = max(generated_files, key=lambda item: item.stat().st_size)
            size = media.stat().st_size
            if size > MAX_FILE_SIZE:
                raise RuntimeError(
                    "O arquivo ultrapassou o limite configurado de "
                    f"{MAX_FILE_SIZE / 1024 / 1024:.0f} MB"
                )

            filename = secure_filename(media.name) or f"download{media.suffix}"
            update_job(
                job_id,
                status="ready",
                progress=100.0,
                message="Arquivo pronto para baixar.",
                title=title,
                filename=filename,
                path=str(media),
                size=size,
                downloaded_bytes=size,
                total_bytes=size,
            )

    except Exception as error:
        logger.exception("Erro no download web %s", job_id)
        shutil.rmtree(directory, ignore_errors=True)
        update_job(
            job_id,
            status="error",
            message="Não foi possível concluir o download.",
            error=str(error)[:500],
        )


def serialized_job(job_id: str) -> dict:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            abort(404, description="Download não encontrado")
        result = {
            key: value
            for key, value in job.items()
            if key not in {"path", "directory", "created_ts", "updated_ts"}
        }

    if result["status"] == "ready":
        result["download_url"] = url_for("download_file", job_id=job_id)
    return result


def cleanup_loop() -> None:
    while True:
        time.sleep(60)
        now = time.time()
        expired: list[tuple[str, str]] = []

        with jobs_lock:
            for job_id, job in list(jobs.items()):
                if job["status"] in {"ready", "error"} and (
                    now - job["updated_ts"] > JOB_TTL_SECONDS
                ):
                    expired.append((job_id, job["directory"]))
                    jobs.pop(job_id, None)

        for _, directory in expired:
            shutil.rmtree(directory, ignore_errors=True)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/health")
def health():
    return jsonify(status="ok", jobs=len(jobs))


@app.get("/api/config")
def config():
    return jsonify(
        token_required=bool(WEB_ACCESS_TOKEN),
        max_concurrent_downloads=MAX_CONCURRENT_DOWNLOADS,
        max_file_size=MAX_FILE_SIZE,
    )


@app.post("/api/jobs")
def create_job():
    require_access()
    payload = request.get_json(silent=True) or {}
    url = str(payload.get("url", "")).strip()
    quality = str(payload.get("quality", "best")).strip().lower()

    if quality not in {"best", "1080p", "720p", "480p", "audio"}:
        return jsonify(error="Qualidade inválida"), 400
    if not public_url(url):
        return jsonify(error="Envie uma URL pública HTTP ou HTTPS válida"), 400

    job_id = uuid.uuid4().hex[:12]
    directory = DOWNLOADS_DIR / job_id
    now = time.time()

    with jobs_lock:
        jobs[job_id] = {
            "id": job_id,
            "url": url,
            "quality": quality,
            "status": "queued",
            "progress": 0.0,
            "message": "Download adicionado à fila.",
            "title": "",
            "filename": "",
            "size": 0,
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "speed": "",
            "eta": "",
            "error": "",
            "directory": str(directory),
            "path": "",
            "created_at": utc_iso(),
            "updated_at": utc_iso(),
            "created_ts": now,
            "updated_ts": now,
        }

    threading.Thread(
        target=download_worker,
        args=(job_id,),
        name=f"download-{job_id}",
        daemon=True,
    ).start()

    return jsonify(id=job_id, status_url=url_for("job_status", job_id=job_id)), 202


@app.get("/api/jobs/<job_id>")
def job_status(job_id: str):
    require_access()
    return jsonify(serialized_job(job_id))


@app.get("/download/<job_id>")
def download_file(job_id: str):
    require_access()

    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            abort(404, description="Download não encontrado")
        if job["status"] != "ready":
            abort(409, description="O arquivo ainda não está pronto")
        path = Path(job["path"])
        filename = job["filename"]

    if not path.is_file():
        abort(410, description="O arquivo expirou")

    return send_file(
        path,
        as_attachment=True,
        download_name=filename,
        conditional=True,
        max_age=0,
    )


threading.Thread(
    target=cleanup_loop,
    name="download-cleanup",
    daemon=True,
).start()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("WEB_PORT", "7776")),
        threaded=True,
    )
