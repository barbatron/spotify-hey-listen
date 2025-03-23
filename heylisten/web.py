import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from loguru import logger

# Initialize FastAPI app
app = FastAPI(title="Heylisten", description="Spotify Playlist Monitor")

# Set up templates directory
templates_dir = Path(__file__).parent.parent / "templates"
templates_dir.mkdir(exist_ok=True)
templates = Jinja2Templates(directory=str(templates_dir))

# Playlist monitor instance
playlist_monitor: Optional[object] = None


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Render the main page."""
    playlist_name = "Not loaded yet"
    track_count = 0
    
    if playlist_monitor and playlist_monitor.cached_playlist:
        playlist_name = playlist_monitor.cached_playlist.get("name", "Unknown Playlist")
        track_count = len(playlist_monitor.cached_playlist.get("tracks", []))
    
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "playlist_name": playlist_name,
            "track_count": track_count,
            "playlist_id": os.getenv("SPOT_PLAYLIST_ID", "No playlist ID set"),
        },
    )


@app.get("/health")
async def health_check():
    """Return health status of the application."""
    return {"status": "healthy", "monitor_active": playlist_monitor is not None}


def set_playlist_monitor(monitor):
    """Set the playlist monitor instance for the web server."""
    global playlist_monitor
    playlist_monitor = monitor
    logger.info("Playlist monitor instance registered with web server")


def start_web_server(host="0.0.0.0", port=8000):
    """Start the web server."""
    import uvicorn
    
    logger.info(f"Starting web server on {host}:{port}")
    uvicorn.run(app, host=host, port=port)
