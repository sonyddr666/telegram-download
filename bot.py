#!/usr/bin/env python3
"""
Bot de Download de Vídeos para Telegram — yt-dlp
Suporta arquivos até 2GB via self-hosted Bot API Server
"""

import asyncio
import logging
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

import yt_dlp
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Configuração
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_API_URL = os.getenv("BOT_API_URL")  # URL do self-hosted Bot API Server
DOWNLOADS_DIR = Path(os.getenv("DOWNLOADS_DIR", "/downloads"))

# Limite de arquivo: 2GB com self-hosted API, 50MB com API pública
if BOT_API_URL:
    MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB
    MAX_FILE_SIZE_STR = "2GB"
else:
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
    MAX_FILE_SIZE_STR = "50MB"

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Armazenamento de jobs
_jobs: dict[str, dict] = {}
_user_jobs: dict[int, list[str]] = {}  # user_id -> [job_ids]


def _build_ydl_opts(quality: str, outdir: Path, progress_hook=None) -> dict:
    tmpl = str(outdir / "video.%(ext)s")
    common = {
        "outtmpl": tmpl,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    if progress_hook:
        common["progress_hooks"] = [progress_hook]

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


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.1f}MB"
    return f"{size_bytes / 1024 / 1024 / 1024:.1f}GB"


def _format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


async def _download_video(job_id: str, url: str, quality: str, update: Update, context: ContextTypes.DEFAULT_TYPE):
    job = _jobs[job_id]
    job["status"] = "downloading"
    
    outdir = DOWNLOADS_DIR / job_id
    outdir.mkdir(parents=True, exist_ok=True)
    
    def progress_hook(d: dict):
        if d["status"] == "downloading":
            percent = d.get("_percent_str", "0%").strip()
            speed = d.get("_speed_str", "—").strip()
            eta = d.get("_eta_str", "—").strip()
            job["progress"] = {"percent": percent, "speed": speed, "eta": eta}
        elif d["status"] == "finished":
            job["progress"]["percent"] = "100%"
    
    try:
        # Primeiro, obter informações do vídeo
        opts = {"quiet": True, "no_warnings": True, "noplaylist": True}
        
        def get_info():
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False)
        
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, get_info)
        
        job["title"] = info.get("title", "Sem título")
        job["thumbnail"] = info.get("thumbnail", "")
        job["duration"] = info.get("duration", 0)
        job["uploader"] = info.get("uploader", "")
        
        # Atualizar mensagem com info do vídeo
        duration_str = _format_duration(job["duration"]) if job["duration"] else "—"
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=job["message_id"],
            text=f"📥 Baixando: {job['title']}\n"
                 f"⏱ Duração: {duration_str}\n"
                 f"📊 Qualidade: {quality}\n"
                 f"⏳ Iniciando download...",
        )
        
        # Download
        opts = _build_ydl_opts(quality, outdir, progress_hook)
        
        def do_download():
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        
        await loop.run_in_executor(None, do_download)
        
        # Encontrar arquivo baixado
        files = sorted(
            outdir.glob("video.*"),
            key=lambda f: f.stat().st_size,
            reverse=True,
        )
        
        if not files:
            raise RuntimeError("Nenhum arquivo gerado após o download")
        
        vf = files[0]
        file_size = vf.stat().st_size
        
        job.update({
            "status": "done",
            "file": str(vf),
            "filename": vf.name,
            "filesize": file_size,
            "finished_at": datetime.utcnow().isoformat() + "Z",
        })
        
        # Verificar tamanho do arquivo
        if file_size > MAX_FILE_SIZE:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=job["message_id"],
                text=f"⚠️ Arquivo muito grande\n\n"
                     f"📹 {job['title']}\n"
                     f"📦 Tamanho: {_format_size(file_size)} (limite: {MAX_FILE_SIZE_STR})\n\n"
                     f"Dica: Use qualidade menor ou extraia apenas o áudio.",
            )
            return
        
        # Enviar arquivo
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=job["message_id"],
            text=f"✅ Download concluído!\n\n"
                 f"📹 {job['title']}\n"
                 f"📦 Tamanho: {_format_size(file_size)}\n"
                 f"⏳ Enviando arquivo...",
        )
        
        is_audio = vf.suffix == ".mp3"
        
        if is_audio:
            await context.bot.send_audio(
                chat_id=update.effective_chat.id,
                audio=vf.open("rb"),
                filename=job["filename"],
                title=job["title"],
                performer=job.get("uploader", ""),
                caption=f"🎵 {job['title']}",
            )
        else:
            await context.bot.send_video(
                chat_id=update.effective_chat.id,
                video=vf.open("rb"),
                filename=job["filename"],
                caption=f"📹 {job['title']}\n📦 {_format_size(file_size)}",
                supports_streaming=True,
            )
        
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=job["message_id"],
        )
        
    except Exception as exc:
        job.update({
            "status": "error",
            "error": str(exc),
            "finished_at": datetime.utcnow().isoformat() + "Z",
        })
        
        logger.error(f"Erro no download {job_id}: {exc}")
        
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=job["message_id"],
            text=f"❌ Erro no download\n\n"
                 f"URL: {url}\n"
                 f"Erro: {str(exc)[:200]}",
        )


# ── Handlers ────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    limit_info = f"📦 *Limite:* {MAX_FILE_SIZE_STR} por arquivo" if BOT_API_URL else "📦 *Limite:* 50MB por arquivo"
    await update.message.reply_text(
        "🎬 *Bot de Download de Vídeos*\n\n"
        "Envie uma URL de vídeo para baixar.\n\n"
        "✅ Suporta +1000 sites:\n"
        "• YouTube, TikTok, Instagram\n"
        "• Facebook, Twitter/X, Twitch\n"
        "• Vimeo, Reddit, SoundCloud\n"
        "• E muitos outros!\n\n"
        f"{limit_info}\n\n"
        "Use /help para mais informações.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 *Como usar*\n\n"
        "1️⃣ Envie a URL do vídeo\n"
        "2️⃣ Escolha a qualidade desejada\n"
        "3️⃣ Aguarde o download\n"
        "4️⃣ Receba o arquivo!\n\n"
        "🎯 *Qualidades disponíveis:*\n"
        "• Melhor — máxima qualidade\n"
        "• 1080p — Full HD\n"
        "• 720p — HD\n"
        "• 480p — SD (menor tamanho)\n"
        "• 🎵 MP3 — apenas áudio\n\n"
        "📦 *Limite:* 2GB por arquivo\n\n"
        "📋 Comandos:\n"
        "/start — Iniciar o bot\n"
        "/help — Esta mensagem\n"
        "/jobs — Ver seus downloads",
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    
    # Validação básica de URL
    url_pattern = re.compile(
        r'^https?://'  # http:// ou https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domínio
        r'localhost|'  # localhost
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # IP
        r'(?::\d+)?'  # porta opcional
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    
    if not url_pattern.match(url):
        await update.message.reply_text(
            "⚠️ Por favor, envie uma URL válida.",
        )
        return
    
    # Criar job
    jid = uuid.uuid4().hex[:8]
    
    keyboard = [
        [
            InlineKeyboardButton("🎬 Melhor", callback_data=f"dl:{jid}:best"),
            InlineKeyboardButton("📺 1080p", callback_data=f"dl:{jid}:1080p"),
        ],
        [
            InlineKeyboardButton("📺 720p", callback_data=f"dl:{jid}:720p"),
            InlineKeyboardButton("📺 480p", callback_data=f"dl:{jid}:480p"),
        ],
        [
            InlineKeyboardButton("🎵 MP3 (Áudio)", callback_data=f"dl:{jid}:audio"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = await update.message.reply_text(
        "🎬 *Novo Download*\n\n"
        f"URL: {url}\n\n"
        "Selecione a qualidade:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup,
    )
    
    _jobs[jid] = {
        "id": jid,
        "url": url,
        "user_id": update.effective_user.id,
        "chat_id": update.effective_chat.id,
        "message_id": message.message_id,
        "status": "waiting",
        "quality": None,
        "progress": {"percent": "0%", "speed": "—", "eta": "—"},
        "title": "",
        "thumbnail": "",
        "duration": 0,
        "uploader": "",
        "file": None,
        "filename": None,
        "filesize": None,
        "error": None,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    
    # Registrar job no usuário
    user_id = update.effective_user.id
    if user_id not in _user_jobs:
        _user_jobs[user_id] = []
    _user_jobs[user_id].append(jid)


async def quality_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if not data.startswith("dl:"):
        return
    
    _, jid, quality = data.split(":")
    
    if jid not in _jobs:
        await query.edit_message_text("❌ Job não encontrado. Inicie novamente.")
        return
    
    job = _jobs[jid]
    job["quality"] = quality
    job["status"] = "queued"
    
    await query.edit_message_text(
        f"📥 *Download iniciado*\n\n"
        f"URL: {job['url']}\n"
        f"Qualidade: {quality}\n\n"
        f"⏳ Aguarde...",
        parse_mode=ParseMode.MARKDOWN,
    )
    
    # Iniciar download em background
    asyncio.create_task(_download_video(jid, job["url"], quality, update, context))


async def jobs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in _user_jobs or not _user_jobs[user_id]:
        await update.message.reply_text(
            "📋 Você não tem downloads recentes.",
        )
        return
    
    lines = ["📋 *Seus Downloads*\n"]
    
    for jid in _user_jobs[user_id][-10:]:  # Últimos 10
        job = _jobs.get(jid)
        if not job:
            continue
        
        status_emoji = {
            "waiting": "⏳",
            "queued": "📋",
            "downloading": "📥",
            "done": "✅",
            "error": "❌",
        }.get(job["status"], "❓")
        
        title = job.get("title", job["url"])[:40]
        lines.append(f"{status_emoji} `{jid}` — {title}")
    
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
    )


def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN não definido! Use: export BOT_TOKEN=seu_token")
        return
    
    # Criar diretório de downloads
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Log de configuração
    logger.info("=" * 50)
    logger.info("Video Downloader Telegram Bot")
    logger.info("=" * 50)
    
    # Criar aplicação com self-hosted Bot API (se configurado)
    builder = Application.builder().token(BOT_TOKEN)
    
    if BOT_API_URL:
        logger.info(f"✅ Bot API Server: {BOT_API_URL}")
        logger.info(f"✅ Limite de arquivo: {MAX_FILE_SIZE_STR}")
        builder = builder.base_url(BOT_API_URL)
    else:
        logger.warning("⚠️ Usando Bot API pública (limite 50MB)")
        logger.warning("⚠️ Configure BOT_API_URL para limite de 2GB")
    
    logger.info("=" * 50)
    
    application = builder.build()
    
    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("jobs", jobs_command))
    application.add_handler(CallbackQueryHandler(quality_callback, pattern=r"^dl:"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    
    # Iniciar bot
    logger.info("Bot iniciado!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
