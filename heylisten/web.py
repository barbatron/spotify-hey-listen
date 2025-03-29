import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import spotipy
from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from loguru import logger
from spotipy.oauth2 import SpotifyOAuth

from heylisten.playlist_monitor import PlaylistMonitor
from heylisten.config import data_dir

# Initialize FastAPI app
app = FastAPI(title="Heylisten", description="Spotify Playlist Monitor")

# Set up templates directory - ensure it works both in development and when containerized
templates_dir = Path(__file__).parent.parent / "templates"
if not templates_dir.exists():
    # Try alternate path for Docker deployment
    templates_dir = Path("/app/templates")
templates = Jinja2Templates(directory=str(templates_dir))

# Playlist monitor instance
playlist_monitor: Optional[PlaylistMonitor] = None

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

    # Use the data directory for the auth cache
    cache_path = data_dir / ".spotify_auth_cache"

    return SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=scope,
        cache_path=str(cache_path),
    )


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Render the main page."""
    stats = []
    auth_manager = get_auth_manager()

    if not auth_manager.get_cached_token():
        # Not authenticated, redirect to login
        return RedirectResponse(url="/login")

    # Create Spotify client with the cached token
    sp = spotipy.Spotify(auth_manager=auth_manager)
    user_data = sp.current_user()
    user_id = user_data["id"]

    # Get only playlists monitored by this user
    monitored_playlists = []
    if playlist_monitor:
        # Get only playlists monitored by this user instead of all playlists
        monitored_playlists = playlist_monitor.db.get_user_playlists(user_id)
        for playlist in monitored_playlists:
            playlist_id = playlist["id"]
            if playlist_id in playlist_monitor.cached_playlists:
                cached_data = playlist_monitor.cached_playlists[playlist_id]
                stats.append(
                    {
                        "id": playlist_id,
                        "name": cached_data.get("name", "Unknown Playlist"),
                        "track_count": len(cached_data.get("tracks", [])),
                    }
                )

    # Get user playlists if available
    available_playlists = user_playlists.get(user_id, [])

    # Mark which playlists are being monitored by this user
    monitored_ids = [p["id"] for p in monitored_playlists]
    for playlist in available_playlists:
        playlist["monitored"] = playlist["id"] in monitored_ids

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "stats": stats,
            "monitored_count": len(monitored_playlists),
            "playlists": available_playlists,
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
        user_id = user_data["id"]

        # Fetch user playlists with pagination
        playlists = []
        results = sp.current_user_playlists(limit=50)
        playlists.extend(results["items"])

        # Handle pagination to get all playlists
        while results["next"]:
            results = sp.next(results)
            playlists.extend(results["items"])

        logger.info(f"Fetched a total of {len(playlists)} playlists for user {user_id}")

        # Filter for collaborative playlists and owned playlists
        collab_playlists = []
        for playlist in playlists:
            owner = playlist.get("owner", {}).get("id")
            type = playlist.get("type")
            is_collab = playlist.get("collaborative", False)
            is_owner = owner == user_id
            is_public = playlist.get("public")
            logger.debug(
                f"  - \"{playlist['name']}\": type={type} collaborative={is_collab} owner={owner} is_owner={is_owner} is_public={is_public}"
            )
            if (
                playlist.get("collaborative")
                # or playlist.get("owner", {}).get("id") != user_data["id"]
            ):
                logger.debug(f"Adding playlist: {playlist['name']}")
                collab_playlists.append(
                    {
                        "id": playlist["id"],
                        "name": playlist["name"],
                        "owner": owner,
                        "track_count": playlist["tracks"]["total"],
                        "collaborative": is_collab,
                    }
                )

        # Store playlists in memory
        user_playlists[user_id] = collab_playlists

        logger.info(
            f"Loaded {len(collab_playlists)} collaborative/owned playlists for user {user_data['id']}"
        )

        # Redirect back to main page
        return RedirectResponse(url="/")
    except Exception as e:
        logger.error(f"Error loading playlists: {e}")
        return {"error": str(e)}


@app.post("/update-monitored-playlists")
async def update_monitored_playlists(request: Request):
    """Update which playlists should be monitored."""
    if not playlist_monitor:
        raise HTTPException(status_code=500, detail="Playlist monitor not initialized")

    try:
        form_data = await request.form()
        selected_ids = form_data.getlist("playlist_ids")

        if not selected_ids:
            # Form data might be structured differently
            selected_ids = []
            for key, value in form_data.items():
                if key.startswith("playlist_") and value == "on":
                    # Extract playlist ID from the checkbox name (playlist_XXXX)
                    playlist_id = key.split("_")[1]
                    selected_ids.append(playlist_id)

        # Get user_id from session or Spotify
        auth_manager = get_auth_manager()
        user_id = None
        if auth_manager.get_cached_token():
            sp = spotipy.Spotify(auth_manager=auth_manager)
            user_data = sp.current_user()
            user_id = user_data["id"]

        logger.info(f"Updating monitored playlists for user {user_id}: {selected_ids}")

        # Update the database with selected playlists
        all_playlists = user_playlists.get(user_id, [])
        playlist_monitor.db.update_monitored_playlists(selected_ids, all_playlists, user_id)

        # Perform an immediate check
        playlist_monitor.check_for_changes()

        return RedirectResponse(url="/", status_code=303)  # POST-redirect-GET pattern
    except Exception as e:
        logger.error(f"Error updating monitored playlists: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/select-playlist/{playlist_id}")
async def select_playlist(playlist_id: str):
    """Update the monitored playlist (legacy endpoint)."""
    if not playlist_monitor:
        raise HTTPException(status_code=500, detail="Playlist monitor not initialized")

    try:
        # Get user_id from session or Spotify
        auth_manager = get_auth_manager()
        user_id = None
        if auth_manager.get_cached_token():
            sp = spotipy.Spotify(auth_manager=auth_manager)
            user_data = sp.current_user()
            user_id = user_data["id"]

        # Find the playlist in the available playlists
        playlist_data = None
        for playlist in user_playlists.get(user_id, []):
            if playlist["id"] == playlist_id:
                playlist_data = playlist
                break

        if not playlist_data:
            raise HTTPException(status_code=404, detail="Playlist not found")

        # Add to database with user_id
        playlist_monitor.db.add_playlist(playlist_data, user_id)

        # Perform an immediate check
        playlist_monitor.check_for_changes()

        logger.info(f"Now monitoring playlist: {playlist_id} for user: {user_id}")
        return RedirectResponse(url="/")
    except Exception as e:
        logger.error(f"Error selecting playlist: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """Return health status of the application."""
    return {"status": "healthy", "monitor_active": playlist_monitor is not None}


@app.get("/stop-monitoring/{playlist_id}")
async def stop_monitoring(playlist_id: str):
    """Stop monitoring a specific playlist for the current user."""
    if not playlist_monitor:
        raise HTTPException(status_code=500, detail="Playlist monitor not initialized")

    try:
        # Get user_id from session or Spotify
        auth_manager = get_auth_manager()
        user_id = None
        if not auth_manager.get_cached_token():
            # Not authenticated, redirect to login
            return RedirectResponse(url="/login")

        # Create Spotify client with the cached token
        sp = spotipy.Spotify(auth_manager=auth_manager)
        user_data = sp.current_user()
        user_id = user_data["id"]

        # Get all playlists from the database
        all_playlists = playlist_monitor.db.get_playlists()
        
        # Find the user's specific instance of this playlist
        for i, playlist in enumerate(all_playlists):
            if playlist["id"] == playlist_id and playlist.get("user_id") == user_id:
                # Remove this playlist from the list
                all_playlists.pop(i)
                # Save updated list back to database
                playlist_monitor.db.save_playlists(all_playlists)
                
                logger.info(f"User {user_id} stopped monitoring playlist {playlist_id}")
                
                # Update the user_playlists memory cache
                if user_id in user_playlists:
                    for p in user_playlists[user_id]:
                        if p["id"] == playlist_id:
                            p["monitored"] = False
                
                break
        
        return RedirectResponse(url="/")
    except Exception as e:
        logger.error(f"Error stopping playlist monitoring: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/add-playlist-by-url")
async def add_playlist_by_url(playlist_url: str = Form(...)):
    """Add a playlist to monitor by URL."""
    if not playlist_monitor:
        raise HTTPException(status_code=500, detail="Playlist monitor not initialized")

    try:
        # Extract playlist ID from URL
        # URLs can be in format: https://open.spotify.com/playlist/37i9dQZF1DX0XUsuxWHRQd
        # or spotify:playlist:37i9dQZF1DX0XUsuxWHRQd
        playlist_id = None

        # Match URLs like https://open.spotify.com/playlist/37i9dQZF1DX0XUsuxWHRQd
        url_match = re.search(r"spotify\.com/playlist/([a-zA-Z0-9]+)", playlist_url)
        if url_match:
            playlist_id = url_match.group(1)

        # Match URIs like spotify:playlist:37i9dQZF1DX0XUsuxWHRQd
        uri_match = re.search(r"spotify:playlist:([a-zA-Z0-9]+)", playlist_url)
        if uri_match:
            playlist_id = uri_match.group(1)

        if not playlist_id:
            raise HTTPException(status_code=400, detail="Invalid Spotify playlist URL")

        logger.info(f"Adding playlist by ID: {playlist_id}")

        # Get user_id from session or Spotify
        auth_manager = get_auth_manager()
        user_id = None
        if not auth_manager.get_cached_token():
            # Not authenticated, redirect to login
            return RedirectResponse(url="/login")

        # Create Spotify client with the cached token
        sp = spotipy.Spotify(auth_manager=auth_manager)
        user_data = sp.current_user()
        user_id = user_data["id"]
        
        # Check if playlist is already monitored by this user
        user_monitored_playlists = playlist_monitor.db.get_user_playlists(user_id)
        for existing_playlist in user_monitored_playlists:
            if existing_playlist["id"] == playlist_id:
                logger.info(f"Playlist {playlist_id} is already monitored by user {user_id}")
                return RedirectResponse(url="/", status_code=303)
        
        # Try to fetch the playlist from Spotify
        try:
            playlist_data = sp.playlist(playlist_id, market=playlist_monitor.market)

            # Extract necessary info for monitoring
            simplified_data = {
                "id": playlist_data["id"],
                "name": playlist_data["name"],
                "owner": playlist_data["owner"]["id"],
                "track_count": playlist_data["tracks"]["total"],
                "collaborative": playlist_data.get("collaborative", False),
                "user_id": user_id,  # Explicitly set the user_id in the data
            }

            # Add to database with user_id
            playlist_monitor.db.add_playlist(simplified_data, user_id)

            # Update user_playlists in memory if this is a new playlist
            if user_id in user_playlists:
                # Check if playlist is already in the list
                playlist_exists = False
                for p in user_playlists[user_id]:
                    if p["id"] == simplified_data["id"]:
                        playlist_exists = True
                        break
                
                if not playlist_exists:
                    # Add the playlist to the user's list with monitored flag
                    simplified_data["monitored"] = True
                    user_playlists[user_id].append(simplified_data)

            # Perform an immediate check
            playlist_monitor.check_for_changes()

            logger.info(f"Successfully added playlist '{simplified_data['name']}' to monitoring for user {user_id}")
            return RedirectResponse(url="/", status_code=303)

        except Exception as e:
            logger.error(f"Error fetching playlist {playlist_id}: {e}")
            raise HTTPException(status_code=404, detail=f"Could not fetch playlist: {str(e)}")

    except Exception as e:
        logger.error(f"Error adding playlist by URL: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
