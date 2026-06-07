FROM python:3.14-alpine

# Alpine's ffmpeg is musl-native, apk-maintained, and small (no Debian GUI tree).
# Provides both ffmpeg and ffprobe, used by yt-dlp's FFmpeg postprocessors.
RUN apk add --no-cache ffmpeg

# Patch the build tooling that ships in the base image (pip/setuptools/wheel CVEs).
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p downloads && chmod 777 downloads

EXPOSE 8000

CMD ["python", "main.py"]
