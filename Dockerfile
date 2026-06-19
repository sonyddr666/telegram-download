FROM mwader/static-ffmpeg:8.1.2 AS ffmpeg
FROM denoland/deno:bin-2.8.2 AS deno

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120

COPY --from=ffmpeg /ffmpeg /usr/local/bin/ffmpeg
COPY --from=ffmpeg /ffprobe /usr/local/bin/ffprobe
COPY --from=deno /deno /usr/local/bin/deno

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install \
    --no-cache-dir \
    --retries 10 \
    --timeout 120 \
    --index-url https://pypi.org/simple \
    -r requirements.txt

COPY bot.py web_app.py web_page.py ./

RUN mkdir -p /downloads /app/templates \
    && python -c "from pathlib import Path; from web_page import PAGE_HTML; Path('/app/templates/index.html').write_text(PAGE_HTML, encoding='utf-8')" \
    && python -m py_compile bot.py web_app.py web_page.py \
    && ffmpeg -version \
    && ffprobe -version \
    && deno --version

EXPOSE 7776

CMD ["python", "-u", "bot.py"]
