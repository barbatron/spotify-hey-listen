import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import spotipy
from loguru import logger
from spotipy.oauth2 import SpotifyClientCredentials

from heylisten.notifications import NotificationManager

# Set data directory for persistence
data_dir = Path(os.getenv("DATA_DIR", "/app/data"))
data_dir.mkdir(exist_ok=True)

class PlaylistMonitor:
    """Monitor Spotify playlists for changes."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        market: str = "SE",
        cache_dir: Path = None,
        db_path: str = None,
    ):
        # Spotify API credentials
        self.client_id = client_id
        self.client_secret = client_secret
        self.market = market

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

        # Initialize cache directory with data persistence
        self.cache_dir = cache_dir or data_dir / "cache"
        self.cache_dir.mkdir(exist_ok=True)

        # Initialize playlist database with persistence
        from heylisten.db import PlaylistDatabase
        db_path = db_path or str(data_dir / "monitored_playlists.json")
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
        logger.debug(f"Saving playlist data to cache: {cache_file}")
        with open(cache_file, "w") as f:
            json.dump(playlist_data, f, indent=2)

    def _fetch_playlist_data(self, playlist_id: str) -> Dict[str, Any]:
        """Fetch playlist data from Spotify API for the given playlist ID."""
        logger.debug(f"Fetching playlist data for {playlist_id}")
        try:
            # Get basic playlist info
            playlist = self.sp.playlist(playlist_id, market=self.market)

            # Get all tracks with pagination
            tracks_items = []
            results = playlist["tracks"]
            tracks_items.extend(results["items"])

            while results["next"]:
                results = self.sp.next(results)
                tracks_items.extend(results["items"])

            # Flatten and clean up the track data
            return {
                "id": playlist["id"],
                "name": playlist["name"],
                "snapshot_id": playlist["snapshot_id"],
                "tracks": [
                    {
                        "id": item["track"]["id"] if item["track"] else "unknown",
                        "name": item["track"]["name"] if item["track"] else "Unknown Track",
                        "artists": [artist["name"] for artist in item["track"]["artists"]]
                        if item["track"]
                        else ["Unknown Artist"],
                        "added_at": item["added_at"],
                        "added_by": item["added_by"]["id"] if item["added_by"] else "unknown",
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
                logger.info(
                    f'Checking playlist {playlist_id} "{playlist_name}" for changes{user_tag}...'
                )

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
