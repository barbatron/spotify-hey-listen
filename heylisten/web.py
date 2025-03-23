import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from urllib.parse import urlencode

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from loguru import logger
import spotipy
from spotipy.oauth2 import SpotifyOAuth

# Initialize FastAPI app
app = FastAPI(title="Heylisten", description="Spotify Playlist Monitor")

# Set up templates directory
templates_dir = Path(__file__).parent.parent / "templates"
templates_dir.mkdir(exist_ok=True)
templates = Jinja2Templates(directory=str(templates_dir))

# Playlist monitor instance
playlist_monitor: Optional[object] = None

# OAuth settings
client_id = os.getenv("SPOT_CLIENT_ID", "")
client_secret = os.getenv("SPOT_CLIENT_SECRET", "")
redirect_uri = os.getenv("SPOT_REDIRECT_URI", "http://localhost:8000/callback")
scope = "playlist-read-collaborative playlist-read-private"

# Store user playlists in memory (in a real app, use a proper session management)
user_playlists: Dict[str, List[Dict[str, Any]]] = {}


def get_auth_manager():
    """Create and return a SpotifyOAuth manager."""
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="Spotify credentials not configured")

    return SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=scope,
        cache_path=".spotify_auth_cache",
    )


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Render the main page."""
    playlist_name = "Not loaded yet"
    track_count = 0

    if playlist_monitor and playlist_monitor.cached_playlist:
        playlist_name = playlist_monitor.cached_playlist.get("name", "Unknown Playlist")
        track_count = len(playlist_monitor.cached_playlist.get("tracks", []))

    # Get user playlists if available
    playlists = user_playlists.get("current", [])

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "playlist_name": playlist_name,
            "track_count": track_count,
            "playlist_id": os.getenv("SPOT_PLAYLIST_ID", "No playlist ID set"),
            "playlists": playlists,
        },
    )


@app.get("/login")
async def login():
    """Initiate the OAuth login flow."""
    try:
        auth_manager = get_auth_manager()
        auth_url = auth_manager.get_authorize_url()
        return RedirectResponse(url=auth_url)
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=500, detail=f"Login error: {str(e)}")


@app.get("/spotify/redirect")
async def callback(code: str = None, error: str = None):
    """Handle the OAuth callback from Spotify."""
    if error:
        return {"error": error}

    if not code:
        return {"error": "No code provided"}

    try:
        auth_manager = get_auth_manager()
        auth_manager.get_access_token(code)
        return RedirectResponse(url="/load-playlists")
    except Exception as e:
        logger.error(f"Callback error: {e}")
        return {"error": str(e)}


@app.get("/load-playlists")
async def load_playlists():
    """Load user's collaborative playlists from Spotify."""
    try:
        auth_manager = get_auth_manager()

        if not auth_manager.get_cached_token():
            # Not authenticated, redirect to login
            return RedirectResponse(url="/login")
        
        # Create Spotify client with the cached token
        sp = spotipy.Spotify(auth_manager=auth_manager)
        user_data = sp.current_user()
        
        # Fetch user playlists with pagination
        playlists = []
        results = sp.current_user_playlists(limit=50)
        playlists.extend(results['items'])
        
        # Handle pagination to get all playlists
        while results['next']:
            results = sp.next(results)
            playlists.extend(results['items'])
        
        logger.info(f"Fetched a total of {len(playlists)} playlists for user {user_data['id']}")

        # Filter for collaborative playlists and owned playlists
        collab_playlists = []
        for playlist in playlists:
            if (
                playlist.get("collaborative")
                or playlist.get("owner", {}).get("id") != user_data["id"]
            ):
                logger.debug(f"Adding playlist: {playlist['name']}")
                collab_playlists.append(
                    {
                        "id": playlist["id"],
                        "name": playlist["name"],
                        "owner": playlist["owner"]["display_name"],
                        "track_count": playlist["tracks"]["total"],
                        "collaborative": playlist.get("collaborative", False),
                    }
                )

        # Store playlists in memory
        user_playlists["current"] = collab_playlists

        logger.info(f"Loaded {len(collab_playlists)} collaborative/owned playlists for user {user_data['id']}")

        # Redirect back to main page
        return RedirectResponse(url="/")
    except Exception as e:
        logger.error(f"Error loading playlists: {e}")
        return {"error": str(e)}


@app.get("/select-playlist/{playlist_id}")
async def select_playlist(playlist_id: str):
    """Update the monitored playlist."""
    if not playlist_monitor:
        raise HTTPException(status_code=500, detail="Playlist monitor not initialized")

    try:
        # Update environment variable (for persistence after restart)
        os.environ["SPOT_PLAYLIST_ID"] = playlist_id

        # Set the new playlist in the monitor
        playlist_monitor.playlist_id = playlist_id

        # Perform an immediate check
        playlist_monitor.check_for_changes()

        logger.info(f"Now monitoring playlist: {playlist_id}")
        return RedirectResponse(url="/")
    except Exception as e:
        logger.error(f"Error selecting playlist: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
