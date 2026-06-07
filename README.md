# very simple yt downloader

A lightweight, stateless-ish web interface for `yt-dlp`. Download videos as MP4 or extract audio as MP3 directly from your browser.

## Features

- **Stateless-ish Design:** Files are served directly to your browser and then deleted from the server.
- **Background Cleanup:** Automatic garbage collection for abandoned or stale downloads.
- **Rich UI:** Modern, responsive interface with real-time progress tracking.
- **Docker Ready:** Run instantly with a single command via Docker Hub.
- **FFmpeg Integration:** Seamlessly handles audio conversion and video merging.

<img width="889" height="857" alt="image" src="https://github.com/user-attachments/assets/aa8255ec-c465-4b75-94ab-bf6899238187" />

<img width="1186" height="882" alt="image" src="https://github.com/user-attachments/assets/d25d35fd-480a-4c4f-a172-8bdc6b6a3661" />

## Quick Start (Docker Hub)

You don't even need to clone this repository to run the app. Just create a `docker-compose.yml` file with the following content:

```yaml
services:
  yt-dlp-web-gui:
    image: toastbrotlf2000/yt-dlp-web-gui:latest
    ports:
      - "8000:8000"
    volumes:
      - ./downloads:/app/downloads
    restart: unless-stopped
```

Then run:
```bash
docker compose up -d
```

Access the UI at `http://localhost:8000`.

## Build from Source

If you want to contribute or modify the code:

1. **Clone the repository:**
   ```bash
   git clone https://github.com/toastbrot2000/very-simple-yt-downloader.git
   cd yt-dlp-web-gui
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

## How it Works

1. **Request:** The user submits a video URL and selects a format (MP3/MP4).
2. **Download:** The server uses `yt-dlp` to download the content.
3. **Processing:** If conversion or merging is needed, `ffmpeg` is invoked automatically.
4. **Delivery:** Once ready, the frontend triggers a native browser download.
5. **Cleanup:** The file is deleted from the server immediately after the download is initiated.

## Roadmap

Future goals for this project include:

- [ ] **Playlist Support:** Ability to download entire YouTube playlists.
- [ ] **Advanced Format Selection:** UI to choose specific video/audio codecs.
- [ ] **Authentication:** Optional basic auth for private deployments.
- [ ] **Dark Mode / Themes:** Customizable UI aesthetics.
- [ ] **Mobile App PWA:** Make the web interface a fully installable Progressive Web App.
- [ ] **Download History:** Optional local-storage based history (keeping the server stateless).

## Acknowledgements & Licensing

This project is a wrapper around several incredible open-source tools:

- **[yt-dlp](https://github.com/yt-dlp/yt-dlp):** Licensed under The Unlicense. The engine that makes downloading possible.
- **[FastAPI](https://fastapi.tiangolo.com/):** Licensed under MIT. The high-performance backend.
- **[FFmpeg](https://ffmpeg.org/):** Licensed under LGPL/GPL. Used for media conversion and merging.
- **[Font Awesome](https://fontawesome.com/):** Icons used under the CC BY 4.0 license.
- **[Outfit Font](https://fonts.google.com/specimen/Outfit):** Used under the Open Font License.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
