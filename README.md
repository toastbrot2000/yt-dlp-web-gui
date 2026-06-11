# very simple yt downloader

A lightweight, stateless-ish web interface for `yt-dlp`. Download videos as MP4 or extract audio as MP3 directly from your browser.

## Features

- **Stateless-ish Design:** Files are served directly to your browser and then deleted from the server.
- **Background Cleanup:** Automatic garbage collection for abandoned or stale downloads.
- **Rich UI:** Modern, responsive interface with real-time progress tracking.
- **Docker Ready:** Run instantly with a single command.
- **FFmpeg Integration:** Seamlessly handles audio conversion and video merging.
- **Per-task isolation:** Each download gets its own directory; concurrent downloads never collide and cleanup only touches dirs we created.
- **Concurrency & size limits:** Configurable max concurrent downloads, queue depth, and file size cap.
- **Security hardened:** CSP, SRI, security headers, no CORS, no root container, configurable Host header restriction.

<img width="889" height="857" alt="image" src="https://github.com/user-attachments/assets/aa8255ec-c465-4b75-94ab-bf6899238187" />

<img width="1186" height="882" alt="image" src="https://github.com/user-attachments/assets/d25d35fd-480a-4c4f-a172-8bdc6b6a3661" />

## Quick Start (Docker Hub)

```bash
docker run -d \
  --name yt-dlp-web-gui \
  -p 127.0.0.1:8000:8000 \
  -v ./downloads:/app/downloads \
  -e HOST=0.0.0.0 \
  -e MAX_CONCURRENT_DOWNLOADS=1 \
  -e MAX_PENDING_DOWNLOADS=10 \
  -e MAX_FILESIZE_MB=5120 \
  -e FILE_TTL_MINUTES=60 \
  --restart unless-stopped \
  toastbrotlf2000/yt-dlp-web-gui:latest
```

Or with Docker Compose. Create a `docker-compose.yml`:

```yaml
services:
  yt-dlp-web-gui:
    image: toastbrotlf2000/yt-dlp-web-gui:latest
    ports:
      - "127.0.0.1:8000:8000"
    volumes:
      - ./downloads:/app/downloads
    environment:
      - HOST=0.0.0.0
      - MAX_CONCURRENT_DOWNLOADS=1
      - MAX_PENDING_DOWNLOADS=10
      - MAX_FILESIZE_MB=5120
      - FILE_TTL_MINUTES=60
    restart: unless-stopped
```

Then run `docker compose up -d` and open `http://localhost:8000`.

> **Note:** The default port binding is `127.0.0.1:8000:8000` (localhost only). To expose to your LAN, change it to `8000:8000`. **Warning:** there is no authentication — only do this on trusted networks.

## Build from Source

1. **Clone the repository:**
   ```bash
   git clone https://github.com/toastbrot2000/very-simple-yt-downloader.git
   cd very-simple-yt-downloader
   ```

2. **Run with Docker Compose:**
   ```bash
   docker compose up -d --build
   ```

## Local Development (No Docker)

Ensure you have `ffmpeg` installed on your system.

```bash
pip install -r requirements.txt
python main.py
```

By default the server binds to `127.0.0.1:8000`. Override with `HOST` and `PORT` env vars, or use a `.env` file (see `.env.example`).

## Configuration

All settings are environment variables. Copy `.env.example` to `.env` and adjust:

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `127.0.0.1` | Bind address (container uses `0.0.0.0`; host exposure controlled by port mapping) |
| `PORT` | `8000` | Listen port |
| `MAX_CONCURRENT_DOWNLOADS` | `1` | Downloads running at once; others wait as `queued` |
| `MAX_PENDING_DOWNLOADS` | `10` | Active + queued cap; beyond it `POST /api/download` returns 429 |
| `MAX_FILESIZE_MB` | `5120` | Max file size in MB (passed to yt-dlp `max_filesize`) |
| `FILE_TTL_MINUTES` | `60` | Stale task/file cleanup age in minutes |
| `ALLOWED_HOSTS` | (unset) | Comma-separated host allowlist; enables `TrustedHostMiddleware` for DNS-rebinding protection |

## How it Works

1. **Request:** Paste a video URL and pick a format (MP3/MP4).
2. **Probe:** The server checks the link and lists available video heights (or uses the default list if probing fails).
3. **Queue:** If the concurrency limit is reached, the task waits in `queued` status.
4. **Download:** `yt-dlp` downloads into a per-task directory (`downloads/<uuid>/`), so concurrent tasks never collide.
5. **Processing:** `ffmpeg` converts/merges as needed. Metadata and thumbnail are embedded.
6. **Delivery:** The frontend triggers a native browser download.
7. **Cleanup:** The task directory is deleted right after the download starts. A background loop also prunes stale tasks and orphaned UUID-named dirs — anything else in the mount is left alone.

## Nightly Builds

A GitHub Actions workflow checks daily for new yt-dlp releases. When a new version is found, it updates `requirements.txt`, commits the change, and publishes a Docker image to both GHCR and Docker Hub. Manual trigger also available via the Actions tab.

## Exposing to your LAN

Change the port binding from `"127.0.0.1:8000:8000"` to `"8000:8000"`. The container then accepts connections on all interfaces.

**Warning:** The API has no authentication. Only expose on trusted networks, or set `ALLOWED_HOSTS` (e.g. `ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.50`) to restrict the Host header.

## Roadmap

Future goals for this project include:

- [ ] **Playlist Support:** Ability to download entire YouTube playlists.
- [ ] **Advanced Format Selection:** UI to choose specific video/audio codecs.
- [ ] **Authentication:** Optional basic auth for private deployments.
- [ ] **Mobile App PWA:** Make the web interface a fully installable Progressive Web App.
- [ ] **Download History:** Optional local-storage based history (keeping the server stateless).

## Acknowledgements

- **[yt-dlp](https://github.com/yt-dlp/yt-dlp):** The engine that makes downloading possible.
- **[FastAPI](https://fastapi.tiangolo.com/):** The high-performance backend.
- **[FFmpeg](https://ffmpeg.org/):** Media conversion and merging.
- **[Font Awesome](https://fontawesome.com/):** Icons under CC BY 4.0.
- **[Hanken Grotesk](https://fonts.google.com/specimen/Hanken+Grotesk):** UI font under OFL.

## License

MIT — see [LICENSE](LICENSE).
