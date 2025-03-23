import json
import os
from pathlib import Path
from typing import List, Dict, Any
from loguru import logger


class PlaylistDatabase:
    """Simple JSON-based database for storing monitored playlists."""

    def __init__(self, db_path: str = "monitored_playlists.json"):
        """Initialize the playlist database with the given path."""
        self.db_path = Path(db_path)
        self._ensure_db_exists()

    def _ensure_db_exists(self) -> None:
        """Create the database file if it doesn't exist."""
        if not self.db_path.exists():
            self.save_playlists([])
            logger.info(f"Created new playlist database at {self.db_path}")

    def get_playlists(self) -> List[Dict[str, Any]]:
        """Get all monitored playlists."""
        try:
            with open(self.db_path, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.error(f"Error decoding JSON from {self.db_path}, returning empty list")
            return []
        except Exception as e:
            logger.error(f"Error reading playlist database: {e}")
            return []

    def save_playlists(self, playlists: List[Dict[str, Any]]) -> bool:
        """Save the given playlists to the database."""
        try:
            with open(self.db_path, "w") as f:
                json.dump(playlists, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Error saving playlist database: {e}")
            return False

    def get_playlist_ids(self) -> List[str]:
        """Get all monitored playlist IDs."""
        playlists = self.get_playlists()
        return [playlist["id"] for playlist in playlists]

    def add_playlist(self, playlist: Dict[str, Any]) -> bool:
        """Add a playlist to the monitored list if not already present."""
        playlists = self.get_playlists()

        # Check if playlist already exists
        for existing in playlists:
            if existing["id"] == playlist["id"]:
                return True  # Already exists

        playlists.append(playlist)
        return self.save_playlists(playlists)

    def remove_playlist(self, playlist_id: str) -> bool:
        """Remove a playlist from the monitored list."""
        playlists = self.get_playlists()
        playlists = [p for p in playlists if p["id"] != playlist_id]
        return self.save_playlists(playlists)

    def update_monitored_playlists(
        self, playlist_ids: List[str], all_playlists: List[Dict[str, Any]]
    ) -> bool:
        """Update the list of monitored playlists based on selected IDs."""
        # Filter the complete playlist data for only the selected ones
        monitored = [p for p in all_playlists if p["id"] in playlist_ids]
        return self.save_playlists(monitored)
