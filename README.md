# yt-dlp Web GUI

A lightweight, stateless web interface for `yt-dlp`. Download videos as MP4 or extract audio as MP3 directly from your browser.

## Features

- **Stateless Design:** Files are served directly to your browser and then deleted from the server.
- **Background Cleanup:** Automatic garbage collection for abandoned or stale downloads.
- **Rich UI:** Modern, responsive interface with real-time progress tracking.
- **Dockerized:** Easy deployment using Docker and Docker Compose.
- **FFmpeg Integration:** Seamlessly handles audio conversion and video merging.

## Quick Start (Docker)

The easiest way to run the application is using Docker:

1. **Clone the repository:**
   ```bash
   git clone https://github.com/toastbrot2000/yt-dlp-web-gui.git
   cd yt-dlp-web-gui
   ```

2. **Run with Docker Compose:**
   ```bash
   docker compose up -d
   ```

3. **Access the Web UI:**
   Open your browser and navigate to `http://localhost:8000`.

## Local Development

If you prefer to run it without Docker, ensure you have `ffmpeg` installed on your system.

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
- **[FFmpeg](https://ffmpeg.org/):** Licensed under LGPL/GPL. Used for media conversion and merging. (Note: This project does not distribute FFmpeg; it must be installed on the host or used via the provided Docker image).
- **[Font Awesome](https://fontawesome.com/):** Icons used under the CC BY 4.0 license.
- **[Outfit Font](https://fonts.google.com/specimen/Outfit):** Used under the Open Font License.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
