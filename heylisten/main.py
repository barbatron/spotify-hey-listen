import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import schedule
import spotipy
from dotenv import load_dotenv
from loguru import logger
from spotipy.oauth2 import SpotifyOAuth

# Load environment variables
load_dotenv()

# Configure logger
logger.add("heylisten.log", rotation="10 MB", retention="7 days")


class PlaylistMonitor:
    def __init__(self):
        # Spotify API credentials
        self.client_id = os.getenv("SPOT_CLIENT_ID")
        self.client_secret = os.getenv("SPOT_CLIENT_SECRET")
        self.redirect_uri = os.getenv("SPOT_REDIRECT_URI")
        self.playlist_id = os.getenv("SPOT_PLAYLIST_ID")
        self.market = os.getenv("SPOT_MARKET", "SE")

        # Check if required environment variables are set
        self._validate_env_vars()

        # Setup Spotify client
        self.sp = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                client_id=self.client_id,
                client_secret=self.client_secret,
                redirect_uri=self.redirect_uri,
                scope="playlist-read-collaborative",
            )
        )

        # Initialize cache directory
        self.cache_dir = Path("cache")
        self.cache_dir.mkdir(exist_ok=True)
        self.cache_file = self.cache_dir / f"playlist_{self.playlist_id}.json"

        # Load cached playlist data if available
        self.cached_playlist = self._load_cache()

    def _validate_env_vars(self):
        """Validate that all required environment variables are set."""
        missing_vars = []
        for var in [
            "SPOT_CLIENT_ID",
            "SPOT_CLIENT_SECRET",
            "SPOT_REDIRECT_URI",
            "SPOT_PLAYLIST_ID",
        ]:
            if not os.getenv(var):
                missing_vars.append(var)

        if missing_vars:
            logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
            raise EnvironmentError(
                f"Missing required environment variables: {', '.join(missing_vars)}"
            )

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
        with open(self.cache_file, "w") as f:
            json.dump(playlist_data, f)
        logger.debug(f"Saved playlist data to {self.cache_file}")

    def _fetch_playlist_data(self) -> Dict[str, Any]:
        """Fetch playlist data from Spotify API."""
        try:
            playlist = self.sp.playlist(self.playlist_id, market=self.market)
            tracks_items = playlist["tracks"]["items"]

            # Handle pagination to get all tracks
            next_page = playlist["tracks"]["next"]
            while next_page:
                tracks_len = len(tracks_items)
                last_track_id = tracks_items[tracks_len - 1]["track"]["id"]
                logger.debug(f"Got {tracks_len} tracks (last={last_track_id})")
                logger.debug("fetching additional tracks page: {next_page}")
                tracks_page = self.sp.playlist_items(
                    playlist["id"], limit=100, offset=tracks_len, market=self.market
                )
                logger.debug(f"Got {len(tracks_page['items'])} additional tracks")
                tracks_items.extend(tracks_page["items"])
                next_page = tracks_page["next"]

            logger.info(f"Fetched {len(tracks_items)} total tracks from playlist")

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
            logger.error(f"Failed to fetch playlist data: {e}")
            raise

    def _compare_playlists(self, old_data: Dict[str, Any], new_data: Dict[str, Any]):
        """Compare old and new playlist data and log changes."""
        if old_data["snapshot_id"] != new_data["snapshot_id"]:
            logger.info(
                f"Detected changes in playlist '{new_data['name']}' (ID: {new_data['id']})",
                old_data["snapshot_id"],
                new_data["snapshot_id"],
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

    def check_for_changes(self):
        """Fetch current playlist and check for changes."""
        try:
            logger.info(f"Checking playlist {self.playlist_id} for changes...")
            current_playlist = self._fetch_playlist_data()

            if self.cached_playlist:
                self._compare_playlists(self.cached_playlist, current_playlist)
            else:
                logger.info(
                    f"Initial load of playlist '{current_playlist['name']}' with {len(current_playlist['tracks'])} tracks"
                )

            # Update cache
            self._save_cache(current_playlist)
            self.cached_playlist = current_playlist
        except Exception as e:
            logger.error(f"Error during playlist check: {e}")


def main():
    """Main function to run the playlist monitor."""
    monitor = PlaylistMonitor()

    # Do an initial check
    monitor.check_for_changes()

    # Schedule periodic checks (every 5 minutes)
    period = 5
    schedule.every(period).seconds.do(monitor.check_for_changes)

    logger.info(f"Playlist monitor started, checking for changes every {period} seconds")

    # Keep the script running
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    main()
