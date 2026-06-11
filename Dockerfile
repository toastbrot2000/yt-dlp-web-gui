FROM python:3-alpine3.24

# Alpine's ffmpeg is musl-native, apk-maintained, and small (no Debian GUI tree).
# Provides both ffmpeg and ffprobe, used by yt-dlp's FFmpeg postprocessors.
RUN apk add --no-cache ffmpeg

# Pin build tooling so renewing the lockfile produces deterministic transitive deps.
RUN pip install --no-cache-dir pip==26.1.2 setuptools==82.0.1 wheel==0.47.0

# Create non-root user and prepare downloads dir with correct ownership
RUN adduser -D -u 1000 app && mkdir -p /app/downloads && chown app:app /app/downloads

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app . .

ENV HOST=0.0.0.0

USER app

EXPOSE 8000

CMD ["python", "main.py"]
