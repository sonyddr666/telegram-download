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

COPY bot.py .

RUN mkdir -p /downloads \
    && ffmpeg -version \
    && ffprobe -version \
    && deno --version

CMD ["python", "-u", "bot.py"]
