#!/usr/bin/env python3
import asyncio
import ipaddress
import logging
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
BOT_API_URL = os.getenv("BOT_API_URL", "").strip()
DOWNLOADS_DIR = Path(os.getenv("DOWNLOADS_DIR", "/downloads"))
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0") or "0")
MAX_CONCURRENT_DOWNLOADS = max(
    1, int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "1") or "1")
)
DELETE_AFTER_SEND = os.getenv(
    "DELETE_AFTER_SEND", "true"
).strip().lower() in {"1", "true", "yes", "sim", "on"}

MAX_FILE_SIZE = 2_000_000_000 if BOT_API_URL else 50 * 1024 * 1024
MAX_FILE_SIZE_STR = "2 GB" if BOT_API_URL else "50 MB"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

jobs: dict[str, dict] = {}
user_jobs: dict[int, list[str]] = {}
download_limit = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)


def allowed(update: Update) -> bool:
    return (
        ALLOWED_USER_ID == 0
        or (
            update.effective_user is not None
            and update.effective_user.id == ALLOWED_USER_ID
        )
    )


async def deny(update: Update) -> None:
    if update.callback_query:
        await update.callback_query.answer("Este bot é privado.", show_alert=True)
    elif update.effective_message:
        await update.effective_message.reply_text("⛔ Este bot é privado.")


def safe_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False

        host = parsed.hostname.lower()
        if host == "localhost" or host.endswith(".local"):
            return False

        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return True

        return not any(
            (
                address.is_private,
                address.is_loopback,
                address.is_link_local,
                address.is_multicast,
                address.is_reserved,
                address.is_unspecified,
            )
        )
    except ValueError:
        return False


def ydl_options(quality: str, directory: Path) -> dict:
    common = {
        "outtmpl": str(directory / "video.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "restrictfilenames": True,
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
        "best": (
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
            "bestvideo+bestaudio/best"
        ),
        "1080p": (
            "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/"
            "best[height<=1080]/best"
        ),
        "720p": (
            "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/"
            "best[height<=720]/best"
        ),
        "480p": (
            "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/"
            "best[height<=480]/best"
        ),
    }

    return {
        **common,
        "format": formats.get(quality, formats["best"]),
        "merge_output_format": "mp4",
    }


def size_text(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024**2:
        return f"{size / 1024:.1f} KB"
    if size < 1024**3:
        return f"{size / 1024**2:.1f} MB"
    return f"{size / 1024**3:.1f} GB"


async def download(
    job_id: str,
    quality: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    job = jobs[job_id]
    directory = DOWNLOADS_DIR / job_id
    directory.mkdir(parents=True, exist_ok=True)

    try:
        async with download_limit:
            job["status"] = "downloading"
            loop = asyncio.get_running_loop()

            def fetch_info():
                with yt_dlp.YoutubeDL(
                    {"quiet": True, "no_warnings": True, "noplaylist": True}
                ) as ydl:
                    return ydl.extract_info(job["url"], download=False)

            info = await loop.run_in_executor(None, fetch_info)
            job["title"] = info.get("title") or "Sem título"
            job["uploader"] = info.get("uploader") or ""

            await context.bot.edit_message_text(
                chat_id=job["chat_id"],
                message_id=job["message_id"],
                text=(
                    f"📥 Baixando: {job['title']}\n"
                    f"📊 Qualidade: {quality}\n"
                    "⏳ Aguarde..."
                ),
            )

            def run_download():
                with yt_dlp.YoutubeDL(
                    ydl_options(quality, directory)
                ) as ydl:
                    ydl.download([job["url"]])

            await loop.run_in_executor(None, run_download)

            files = sorted(
                directory.glob("video.*"),
                key=lambda file: file.stat().st_size,
                reverse=True,
            )
            if not files:
                raise RuntimeError("O yt-dlp não gerou nenhum arquivo")

            media = files[0]
            media_size = media.stat().st_size

            if media_size > MAX_FILE_SIZE:
                raise RuntimeError(
                    f"arquivo com {size_text(media_size)} excede "
                    f"o limite de {MAX_FILE_SIZE_STR}"
                )

            await context.bot.edit_message_text(
                chat_id=job["chat_id"],
                message_id=job["message_id"],
                text=(
                    "✅ Download concluído\n\n"
                    f"📹 {job['title']}\n"
                    f"📦 {size_text(media_size)}\n"
                    "⏳ Enviando..."
                ),
            )

            upload = str(media) if BOT_API_URL else media.open("rb")
            try:
                options = {
                    "chat_id": job["chat_id"],
                    "filename": media.name,
                    "caption": f"📹 {job['title']}\n📦 {size_text(media_size)}",
                    "read_timeout": None,
                    "write_timeout": None,
                    "connect_timeout": 60,
                    "pool_timeout": 60,
                }

                if media.suffix.lower() == ".mp3":
                    await context.bot.send_audio(
                        audio=upload,
                        title=job["title"],
                        performer=job["uploader"],
                        **options,
                    )
                else:
                    await context.bot.send_video(
                        video=upload,
                        supports_streaming=True,
                        **options,
                    )
            finally:
                if hasattr(upload, "close"):
                    upload.close()

            job.update(
                status="done",
                filesize=media_size,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            await context.bot.delete_message(
                chat_id=job["chat_id"],
                message_id=job["message_id"],
            )

    except Exception as error:
        job.update(
            status="error",
            error=str(error),
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        logger.exception("Falha no download %s", job_id)

        try:
            await context.bot.edit_message_text(
                chat_id=job["chat_id"],
                message_id=job["message_id"],
                text=f"❌ Erro no download\n\n{str(error)[:300]}",
            )
        except Exception:
            logger.exception("Falha ao enviar a mensagem de erro")
    finally:
        if DELETE_AFTER_SEND:
            shutil.rmtree(directory, ignore_errors=True)


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not allowed(update):
        await deny(update)
        return

    await update.effective_message.reply_text(
        "🎬 <b>Bot de Download de Vídeos</b>\n\n"
        "Envie uma URL e escolha a qualidade.\n"
        f"Limite por arquivo: <b>{MAX_FILE_SIZE_STR}</b>.",
        parse_mode=ParseMode.HTML,
    )


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not allowed(update):
        await deny(update)
        return

    await update.effective_message.reply_text(
        "📚 <b>Como usar</b>\n\n"
        "1. Envie uma URL.\n"
        "2. Escolha melhor, 1080p, 720p, 480p ou MP3.\n"
        "3. Aguarde o envio.\n\n"
        "/start - iniciar\n"
        "/help - ajuda\n"
        "/jobs - downloads recentes",
        parse_mode=ParseMode.HTML,
    )


async def receive_url(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not allowed(update):
        await deny(update)
        return

    message = update.effective_message
    if not message or not message.text:
        return

    url = message.text.strip()
    if not safe_url(url):
        await message.reply_text(
            "⚠️ Envie uma URL pública HTTP ou HTTPS válida."
        )
        return

    job_id = uuid.uuid4().hex[:8]
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🎬 Melhor", callback_data=f"dl:{job_id}:best"
                ),
                InlineKeyboardButton(
                    "📺 1080p", callback_data=f"dl:{job_id}:1080p"
                ),
            ],
            [
                InlineKeyboardButton(
                    "📺 720p", callback_data=f"dl:{job_id}:720p"
                ),
                InlineKeyboardButton(
                    "📺 480p", callback_data=f"dl:{job_id}:480p"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🎵 MP3", callback_data=f"dl:{job_id}:audio"
                )
            ],
        ]
    )

    reply = await message.reply_text(
        f"🎬 Novo download\n\nURL: {url}\n\nSelecione a qualidade:",
        reply_markup=keyboard,
    )

    user_id = update.effective_user.id
    jobs[job_id] = {
        "url": url,
        "user_id": user_id,
        "chat_id": update.effective_chat.id,
        "message_id": reply.message_id,
        "status": "waiting",
        "title": "",
        "uploader": "",
        "filesize": None,
        "error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    recent = user_jobs.setdefault(user_id, [])
    recent.append(job_id)
    del recent[:-20]


async def choose_quality(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    if not query:
        return

    if not allowed(update):
        await deny(update)
        return

    try:
        _, job_id, quality = (query.data or "").split(":", 2)
    except ValueError:
        await query.answer("Ação inválida.", show_alert=True)
        return

    job = jobs.get(job_id)
    if not job:
        await query.answer("Download expirado.", show_alert=True)
        return
    if query.from_user.id != job["user_id"]:
        await query.answer("Este download não é seu.", show_alert=True)
        return
    if job["status"] != "waiting":
        await query.answer("Este download já foi iniciado.", show_alert=True)
        return

    await query.answer()
    job["status"] = "queued"

    await query.edit_message_text(
        "📥 Download colocado na fila\n\n"
        f"URL: {job['url']}\n"
        f"Qualidade: {quality}\n\n"
        "⏳ Aguarde..."
    )
    asyncio.create_task(download(job_id, quality, context))


async def jobs_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not allowed(update):
        await deny(update)
        return

    ids = user_jobs.get(update.effective_user.id, [])
    if not ids:
        await update.effective_message.reply_text(
            "📋 Nenhum download recente."
        )
        return

    icons = {
        "waiting": "⏳",
        "queued": "📋",
        "downloading": "📥",
        "done": "✅",
        "error": "❌",
    }
    lines = ["📋 Downloads recentes\n"]

    for job_id in ids[-10:]:
        job = jobs.get(job_id)
        if job:
            title = (job.get("title") or job["url"])[:50]
            lines.append(
                f"{icons.get(job['status'], '❓')} {job_id} - {title}"
            )

    await update.effective_message.reply_text("\n".join(lines))


async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    error = context.error
    logger.error(
        "Erro não tratado",
        exc_info=(type(error), error, error.__traceback__) if error else None,
    )


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN não foi definido")

    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    builder = Application.builder().token(BOT_TOKEN)

    if BOT_API_URL:
        root = BOT_API_URL.removesuffix("/bot")
        builder = (
            builder.base_url(BOT_API_URL)
            .base_file_url(f"{root}/file/bot")
            .local_mode(True)
            .media_write_timeout(None)
            .read_timeout(None)
            .write_timeout(None)
            .connect_timeout(60)
            .pool_timeout(60)
        )

    application = builder.build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("jobs", jobs_command))
    application.add_handler(
        CallbackQueryHandler(choose_quality, pattern=r"^dl:")
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, receive_url)
    )
    application.add_error_handler(error_handler)

    logger.info(
        "Bot iniciado | usuário=%s | limite=%s | simultâneos=%s",
        ALLOWED_USER_ID or "todos",
        MAX_FILE_SIZE_STR,
        MAX_CONCURRENT_DOWNLOADS,
    )
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
