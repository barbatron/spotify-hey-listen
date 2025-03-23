import json
import os
import sys  # Add missing import for sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import schedule
import spotipy
from dotenv import load_dotenv
from loguru import logger
from spotipy.oauth2 import SpotifyClientCredentials

from heylisten.notifications import NotificationManager

# Load environment variables
load_dotenv()

# Configure logger
logger.add("heylisten.log", rotation="10 MB", retention="7 days")


class PlaylistMonitor:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        market: str = "SE",
        cache_dir: Path = Path("cache"),
        db_path: str = "monitored_playlists.json",
    ):
        # Spotify API credentials
        self.client_id = client_id
        self.client_secret = client_secret
        self.market = market
        self.playlist_id = None  # Initialize playlist_id to None

        # Initialize notification manager
        self.notification_manager = NotificationManager()

        # Check if required parameters are valid
        self._validate_params()

        # Setup Spotify client
        self.sp = spotipy.Spotify(
            auth_manager=SpotifyClientCredentials(
                client_id=self.client_id,
                client_secret=self.client_secret,
            )
        )

        # Initialize cache directory
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(exist_ok=True)

        # Initialize playlist database
        from heylisten.db import PlaylistDatabase

        self.db = PlaylistDatabase(db_path)

        # Cached playlist data - now a dictionary with playlist IDs as keys
        self.cached_playlists = {}

        # Load cached playlist data for all monitored playlists
        for playlist in self.db.get_playlists():
            playlist_id = playlist["id"]
            cache_file = self.cache_dir / f"playlist_{playlist_id}.json"
            if cache_file.exists():
                try:
                    with open(cache_file, "r") as f:
                        self.cached_playlists[playlist_id] = json.load(f)
                        logger.debug(f"Loaded cached data for playlist {playlist_id}")
                except Exception as e:
                    logger.error(f"Error loading cache for playlist {playlist_id}: {e}")

    def _validate_params(self):
        """Validate that all required parameters are set."""
        missing_params = []
        for param_name, param_value in [
            ("client_id", self.client_id),
            ("client_secret", self.client_secret),
        ]:
            if not param_value:
                missing_params.append(param_name)

        if missing_params:
            logger.error(f"Missing required parameters: {', '.join(missing_params)}")
            raise ValueError(f"Missing required parameters: {', '.join(missing_params)}")

    def _load_cache(self) -> Optional[Dict[str, Any]]:
        """Load playlist data from cache if available."""
        if self.cache_file.exists():
            logger.debug(f"Loading cached playlist data from {self.cache_file}")
            try:
                with open(self.cache_file, "r") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                logger.error("Failed to parse cache file, will create new cache")
                return None
        logger.info("No cache file found, will create new cache")
        return None

    def _save_cache(self, playlist_data: Dict[str, Any]):
        """Save playlist data to cache."""
        playlist_id = playlist_data["id"]
        cache_file = self.cache_dir / f"playlist_{playlist_id}.json"
        try:
            with open(cache_file, "w") as f:
                json.dump(playlist_data, f)
            logger.debug(f"Saved playlist data to {cache_file}")
        except Exception as e:
            logger.error(f"Failed to save playlist data to cache: {e}")

    def _fetch_playlist_data(self, playlist_id: str) -> Dict[str, Any]:
        """Fetch playlist data from Spotify API for the given playlist ID."""
        try:
            playlist = self.sp.playlist(playlist_id, market=self.market)
            tracks_items = playlist["tracks"]["items"]

            # Handle pagination to get all tracks
            next_page = playlist["tracks"]["next"]
            while next_page:
                tracks_len = len(tracks_items)
                last_track_id = (
                    tracks_items[tracks_len - 1]["track"]["id"]
                    if tracks_items[tracks_len - 1]["track"]
                    else "unknown"
                )
                logger.debug(f"Got {tracks_len} tracks (last={last_track_id})")
                logger.debug(f"Fetching additional tracks page: {next_page}")
                tracks_page = self.sp.playlist_items(
                    playlist["id"], limit=100, offset=tracks_len, market=self.market
                )
                logger.debug(f"Got {len(tracks_page['items'])} additional tracks")
                tracks_items.extend(tracks_page["items"])
                next_page = tracks_page["next"]

            logger.info(f"Fetched {len(tracks_items)} total tracks from playlist {playlist_id}")

            # Extract relevant information (optimization to reduce cache size)
            return {
                "id": playlist["id"],
                "name": playlist["name"],
                "snapshot_id": playlist["snapshot_id"],
                "tracks": [
                    {
                        "id": item["track"]["id"] if item["track"] else None,
                        "name": item["track"]["name"] if item["track"] else "Removed track",
                        "artists": [artist["name"] for artist in item["track"]["artists"]]
                        if item["track"] and "artists" in item["track"]
                        else [],
                        "added_at": item["added_at"],
                        "added_by": item["added_by"]["id"]
                        if "added_by" in item and item["added_by"]
                        else None,
                    }
                    for item in tracks_items
                ],
            }
        except Exception as e:
            logger.error(f"Failed to fetch playlist data for {playlist_id}: {e}")
            raise

    def _compare_playlists(
        self, old_data: Dict[str, Any], new_data: Dict[str, Any], user_id: str = None
    ) -> Dict[str, Any]:
        """Compare old and new playlist data and log changes."""
        if old_data["snapshot_id"] != new_data["snapshot_id"]:
            user_info = f" (monitored by user: {user_id})" if user_id else ""
            logger.info(
                f"Detected changes in playlist '{new_data['name']}' (ID: {new_data['id']}){user_info}"
            )

        # Create track ID maps for easier comparison
        old_tracks = {track["id"]: track for track in old_data["tracks"]}
        new_tracks = {track["id"]: track for track in new_data["tracks"]}

        # Find added tracks
        added_tracks = [
            track
            for track_id, track in new_tracks.items()
            if track_id not in old_tracks or track["added_at"] != old_tracks[track_id]["added_at"]
        ]

        # Find removed tracks
        removed_tracks = [
            track for track_id, track in old_tracks.items() if track_id not in new_tracks
        ]

        # Log changes
        for track in added_tracks:
            artists = ", ".join(track["artists"])
            logger.info(f"Added: {track['name']} by {artists} (added by: {track['added_by']})")

        for track in removed_tracks:
            artists = ", ".join(track["artists"])
            logger.info(f"Removed: {track['name']} by {artists}")

        logger.info(
            f"Summary: {len(added_tracks)} track(s) added, {len(removed_tracks)} track(s) removed"
        )

        # Return changes for notifications
        return {
            "playlist_name": new_data["name"],
            "playlist_id": new_data["id"],
            "user_id": user_id,
            "added_tracks": added_tracks,
            "removed_tracks": removed_tracks,
        }

    def check_for_changes(self):
        """Fetch current playlists and check for changes in all monitored playlists."""
        try:
            # Get all monitored playlists from database
            monitored_playlists = self.db.get_playlists()

            if not monitored_playlists:
                logger.info("No playlists are currently being monitored")
                return

            logger.info(f"Checking {len(monitored_playlists)} playlists for changes...")

            changes_list = []  # Collect all changes for notifications

            for playlist_info in monitored_playlists:
                playlist_id = playlist_info["id"]
                playlist_name = playlist_info["name"]
                user_id = playlist_info.get("user_id")
                user_tag = f" (monitored by: {user_id})" if user_id else ""
                logger.info(f"Checking playlist {playlist_id} \"{playlist_name}\" for changes{user_tag}...")

                try:
                    current_playlist = self._fetch_playlist_data(playlist_id)

                    if playlist_id in self.cached_playlists:
                        changes = self._compare_playlists(
                            self.cached_playlists[playlist_id], current_playlist, user_id
                        )
                        if changes["added_tracks"] or changes["removed_tracks"]:
                            changes_list.append(changes)
                    else:
                        logger.info(
                            f"Initial load of playlist '{current_playlist['name']}'"
                            + f" with {len(current_playlist['tracks'])} tracks{user_tag}"
                        )

                    # Update cache
                    self._save_cache(current_playlist)
                    self.cached_playlists[playlist_id] = current_playlist

                    # Update playlist info in the database
                    for p in monitored_playlists:
                        if p["id"] == playlist_id:
                            p["name"] = current_playlist["name"]
                            p["track_count"] = len(current_playlist["tracks"])
                    self.db.save_playlists(monitored_playlists)

                except Exception as e:
                    logger.error(f"Error checking playlist {playlist_id}: {e}")

            # Send notifications for changes
            if changes_list:
                self._notify_users_of_changes(changes_list)

        except Exception as e:
            logger.error(f"Error during playlist check: {e}")

    def _notify_users_of_changes(self, changes_list: List[Dict[str, Any]]):
        """Notify users about changes to their monitored playlists."""
        logger.info(f"Processing notifications for {len(changes_list)} changed playlists")
        self.notification_manager.notify_users_of_changes(changes_list)


def start_monitor(monitor):
    """Run the playlist monitor in a loop."""
    # Do an initial check
    monitor.check_for_changes()

    # Schedule periodic checks
    period = 30
    schedule.every(period).seconds.do(monitor.check_for_changes)

    logger.info(f"Playlist monitor started, checking for changes every {period} seconds")

    # Keep the script running
    while True:
        schedule.run_pending()
        time.sleep(1)


def periodic_check(monitor, stop_event, interval_seconds):
    """Run periodic playlist checks at the specified interval."""
    while not stop_event.is_set():
        monitor.check_for_changes()
        # Sleep for the interval, but check for stop event periodically
        for _ in range(interval_seconds):
            if stop_event.is_set():
                break
            time.sleep(1)


def main():
    """Main function to run the playlist monitor and web server."""
    # Get environment variables
    client_id = os.getenv("SPOT_CLIENT_ID")
    client_secret = os.getenv("SPOT_CLIENT_SECRET")
    redirect_uri = os.getenv("SPOT_REDIRECT_URI", "http://localhost:8000/callback")
    playlist_id = os.getenv("SPOT_PLAYLIST_ID")  # Keep for backward compatibility
    market = os.getenv("SPOT_MARKET", "SE")
    web_port = int(os.getenv("WEB_PORT", "8000"))
    web_host = os.getenv("WEB_HOST", "0.0.0.0")

    # Validate environment variables
    missing_vars = []
    for var_name, var_value in [
        ("SPOT_CLIENT_ID", client_id),
        ("SPOT_CLIENT_SECRET", client_secret),
    ]:
        if not var_value:
            missing_vars.append(var_name)

    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        sys.exit(1)

    # Create and start the playlist monitor
    monitor = PlaylistMonitor(
        client_id=client_id,
        client_secret=client_secret,
        market=market,
    )

    # Set up the web server
    from heylisten.web import set_playlist_monitor, start_web_server

    # Register the monitor with the web server
    set_playlist_monitor(monitor)

    # Check for changes immediately
    monitor.check_for_changes()

    # Start the periodic check thread
    stop_event = threading.Event()
    check_thread = threading.Thread(target=periodic_check, args=(monitor, stop_event, 300))
    check_thread.daemon = True
    check_thread.start()

    try:
        # Start the web server (this will block until the server is stopped)
        start_web_server(host=web_host, port=web_port)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, shutting down...")
    finally:
        # Stop the check thread
        stop_event.set()
        check_thread.join(timeout=1)
        logger.info("Playlist monitor stopped")


if __name__ == "__main__":
    main()
