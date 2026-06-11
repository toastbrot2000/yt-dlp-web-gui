# very simple yt downloader

A lightweight, stateless-ish web interface for `yt-dlp`. Download videos as MP4 or extract audio as MP3 directly from your browser.

## Features

- **Stateless-ish Design:** Files are served directly to your browser and then deleted from the server.
- **Background Cleanup:** Automatic garbage collection for abandoned or stale downloads.
- **Rich UI:** Modern, responsive interface with real-time progress tracking.
- **Docker Ready:** Run instantly with a single command via Docker Hub.
- **FFmpeg Integration:** Seamlessly handles audio conversion and video merging.
- **Per-task isolation:** Each download gets its own directory; concurrent downloads never collide and cleanup only touches dirs we created.
- **Concurrency & size limits:** Configurable max concurrent downloads, queue depth, and file size cap.

<img width="889" height="857" alt="image" src="https://github.com/user-attachments/assets/aa8255ec-c465-4b75-94ab-bf6899238187" />

<img width="1186" height="882" alt="image" src="https://github.com/user-attachments/assets/d25d35fd-480a-4c4f-a172-8bdc6b6a3661" />

## Quick Start (Docker Hub)

You don't even need to clone this repository to run the app. Just create a `docker-compose.yml` file with the following content:

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
      - PORT=8000
      - MAX_CONCURRENT_DOWNLOADS=1
      - MAX_PENDING_DOWNLOADS=10
      - MAX_FILESIZE_MB=5120
      - FILE_TTL_MINUTES=60
    restart: unless-stopped
```

Then run:
```bash
docker compose up -d
```

Access the UI at `http://localhost:8000`.

> **Note:** The default port binding is `127.0.0.1:8000:8000` (localhost only). To expose to your LAN, change it to `8000:8000`. **Warning:** there is no authentication — only do this on trusted networks.

## Non-Technical Start (Docker Desktop)

If you're not into self-hosting, you can still run this without touching the console or code using Docker Desktop: 
1. Install Docker Desktop: https://www.docker.com/products/docker-desktop/
2. Run Docker Desktop and in the top search bar search for "toastbrotlf2000/yt-dlp-web-gui"
3. Click "Run" on the image in the result
4. Optionally give it a name, path and a port (default is 8000)
5. Click "Run"
6. You can now go to any browser on the same computer and access the UI at `http://localhost:8000`

## Build from Source

If you want to contribute or modify the code:

1. **Clone the repository:**
   ```bash
   git clone https://github.com/toastbrot2000/very-simple-yt-downloader.git
   ```

2. **Run with Docker Compose:**
   ```bash
   docker compose up -d --build
   ```

## Local Development (No Docker)

Ensure you have `ffmpeg` installed on your system.

1. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the server:**
   ```bash
   python main.py
   ```

   By default the server binds to `127.0.0.1:8000`. Override with `HOST` and `PORT` env vars if needed.

## Configuration

All settings are environment variables. Copy `.env.example` to `.env` and adjust:

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `127.0.0.1` | Bind address (container must use `0.0.0.0`; host exposure controlled by compose port mapping) |
| `PORT` | `8000` | Listen port |
| `MAX_CONCURRENT_DOWNLOADS` | `1` | Downloads running at once; others wait as `queued` |
| `MAX_PENDING_DOWNLOADS` | `10` | Active + queued cap; beyond it `POST /api/download` returns 429 |
| `MAX_FILESIZE_MB` | `5120` | Max file size in MB (passed to yt-dlp `max_filesize`) |
| `FILE_TTL_MINUTES` | `60` | Stale task/file cleanup age in minutes |
| `ALLOWED_HOSTS` | (unset) | Comma-separated host allowlist; when set, enables `TrustedHostMiddleware` for DNS-rebinding protection |

See `.env.example` for a ready-to-copy template with comments.

## How it Works

1. **Request:** The user submits a video URL and selects a format (MP3/MP4).
2. **Queue:** If the concurrency limit is reached, the task waits in `queued` status.
3. **Download:** The server uses `yt-dlp` to download into a per-task directory (`downloads/<task_id>/`).
4. **Processing:** If conversion or merging is needed, `ffmpeg` is invoked automatically.
5. **Delivery:** Once ready, the frontend triggers a native browser download.
6. **Cleanup:** The task directory is deleted immediately after the download is initiated. A background loop also prunes stale tasks and orphaned dirs (only UUID-named dirs — user files on the host mount are never touched).

## Exposing to your LAN

Change the compose port binding from `"127.0.0.1:8000:8000"` to `"8000:8000"`. The container will then accept connections on all interfaces.

**Warning:** The API has no authentication. Only expose on trusted networks, or set `ALLOWED_HOSTS` in `.env` (e.g. `ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.50`) to restrict the Host header.

## Roadmap

Future goals for this project include:

- [ ] **Playlist Support:** Ability to download entire YouTube playlists.
- [ ] **Advanced Format Selection:** UI to choose specific video/audio codecs.
- [ ] **Authentication:** Optional basic auth for private deployments.
- [ ] **Mobile App PWA:** Make the web interface a fully installable Progressive Web App.
- [ ] **Download History:** Optional local-storage based history (keeping the server stateless).

## Acknowledgements & Licensing

This project is a wrapper around several incredible open-source tools:

- **[yt-dlp](https://github.com/yt-dlp/yt-dlp):** Licensed under The Unlicense. The engine that makes downloading possible.
- **[FastAPI](https://fastapi.tiangolo.com/):** Licensed under MIT. The high-performance backend.
- **[FFmpeg](https://ffmpeg.org/):** Licensed under LGPL/GPL. Used for media conversion and merging.
- **[Font Awesome](https://fontawesome.com/):** Icons used under the CC BY 4.0 license.
- **[Hanken Grotesk Font](https://fonts.google.com/specimen/Hanken-Grotesk):** Used under the Open Font License.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
