import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from heylisten.main import PlaylistMonitor


class TestPlaylistMonitor(unittest.TestCase):
    def setUp(self):
        # Mock Spotify credentials
        self.client_id = "test_client_id"
        self.client_secret = "test_client_secret"
        self.redirect_uri = "http://localhost:8888/callback"
        self.playlist_id = "test_playlist_id"
        self.market = "SE"

        # Create a temporary directory for cache
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self.temp_dir.name)

        # Mock Spotify client
        self.spotify_patcher = patch("heylisten.main.spotipy.Spotify")
        self.mock_spotify = self.spotify_patcher.start()
        self.mock_sp_instance = MagicMock()
        self.mock_spotify.return_value = self.mock_sp_instance

        # Mock OAuth manager
        self.oauth_patcher = patch("heylisten.main.SpotifyOAuth")
        self.mock_oauth = self.oauth_patcher.start()

    def tearDown(self):
        # Clean up patches
        self.spotify_patcher.stop()
        self.oauth_patcher.stop()
        # Clean up temp directory
        self.temp_dir.cleanup()

    def test_init_with_valid_parameters(self):
        """Test PlaylistMonitor initialization with valid parameters."""
        monitor = PlaylistMonitor(
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uri=self.redirect_uri,
            playlist_id=self.playlist_id,
            market=self.market,
            cache_dir=self.cache_dir,
        )

        self.assertEqual(monitor.client_id, self.client_id)
        self.assertEqual(monitor.client_secret, self.client_secret)
        self.assertEqual(monitor.redirect_uri, self.redirect_uri)
        self.assertEqual(monitor.playlist_id, self.playlist_id)
        self.assertEqual(monitor.market, self.market)
        self.assertEqual(monitor.cache_dir, self.cache_dir)
        self.assertTrue(self.cache_dir.exists())

    def test_init_with_missing_parameters(self):
        """Test PlaylistMonitor initialization with missing parameters."""
        with self.assertRaises(ValueError):
            PlaylistMonitor(
                client_id="",
                client_secret=self.client_secret,
                redirect_uri=self.redirect_uri,
                playlist_id=self.playlist_id,
                cache_dir=self.cache_dir,
            )

    def test_load_cache_no_file(self):
        """Test loading from cache when no cache file exists."""
        monitor = PlaylistMonitor(
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uri=self.redirect_uri,
            playlist_id=self.playlist_id,
            cache_dir=self.cache_dir,
        )

        # Cache should be None if no file exists
        self.assertIsNone(monitor.cached_playlist)

    def test_load_cache_with_existing_file(self):
        """Test loading from cache when a valid cache file exists."""
        # Create a mock cache file
        cache_file = self.cache_dir / f"playlist_{self.playlist_id}.json"
        mock_data = {
            "id": self.playlist_id,
            "name": "Test Playlist",
            "snapshot_id": "snapshot123",
            "tracks": [
                {
                    "id": "track1",
                    "name": "Track 1",
                    "artists": ["Artist 1"],
                    "added_at": "2023-01-01T00:00:00Z",
                    "added_by": "user1",
                }
            ],
        }
        with open(cache_file, "w") as f:
            json.dump(mock_data, f)

        # Initialize PlaylistMonitor which should load the cache
        monitor = PlaylistMonitor(
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uri=self.redirect_uri,
            playlist_id=self.playlist_id,
            cache_dir=self.cache_dir,
        )

        # Cache should be loaded
        self.assertEqual(monitor.cached_playlist, mock_data)

    @patch("heylisten.main.logger")
    def test_compare_playlists(self, mock_logger):
        """Test comparing playlists and detecting changes."""
        monitor = PlaylistMonitor(
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uri=self.redirect_uri,
            playlist_id=self.playlist_id,
            cache_dir=self.cache_dir,
        )

        old_data = {
            "id": self.playlist_id,
            "name": "Test Playlist",
            "snapshot_id": "snapshot123",
            "tracks": [
                {
                    "id": "track1",
                    "name": "Track 1",
                    "artists": ["Artist 1"],
                    "added_at": "2023-01-01T00:00:00Z",
                    "added_by": "user1",
                },
                {
                    "id": "track2",
                    "name": "Track 2",
                    "artists": ["Artist 2"],
                    "added_at": "2023-01-01T00:00:00Z",
                    "added_by": "user1",
                },
            ],
        }

        new_data = {
            "id": self.playlist_id,
            "name": "Test Playlist",
            "snapshot_id": "snapshot124",
            "tracks": [
                {
                    "id": "track1",
                    "name": "Track 1",
                    "artists": ["Artist 1"],
                    "added_at": "2023-01-01T00:00:00Z",
                    "added_by": "user1",
                },
                {
                    "id": "track3",
                    "name": "Track 3",
                    "artists": ["Artist 3"],
                    "added_at": "2023-01-02T00:00:00Z",
                    "added_by": "user2",
                },
            ],
        }

        monitor._compare_playlists(old_data, new_data)

        # Verify log calls
        mock_logger.info.assert_any_call("Added: Track 3 by Artist 3 (added by: user2)")
        mock_logger.info.assert_any_call("Removed: Track 2 by Artist 2")
        mock_logger.info.assert_any_call("Summary: 1 track(s) added, 1 track(s) removed")

    @patch("heylisten.main.logger")
    def test_fetch_playlist_data(self, mock_logger):
        """Test fetching playlist data from Spotify API."""
        # Prepare mock response
        mock_playlist = {
            "id": self.playlist_id,
            "name": "Test Playlist",
            "snapshot_id": "snapshot123",
            "tracks": {
                "items": [
                    {
                        "track": {
                            "id": "track1",
                            "name": "Track 1",
                            "artists": [{"name": "Artist 1"}],
                        },
                        "added_at": "2023-01-01T00:00:00Z",
                        "added_by": {"id": "user1"},
                    }
                ],
                "next": None,
            },
        }
        self.mock_sp_instance.playlist.return_value = mock_playlist

        monitor = PlaylistMonitor(
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uri=self.redirect_uri,
            playlist_id=self.playlist_id,
            cache_dir=self.cache_dir,
        )

        result = monitor._fetch_playlist_data()

        # Verify API call
        self.mock_sp_instance.playlist.assert_called_once_with(self.playlist_id, market=self.market)

        # Verify result
        self.assertEqual(result["id"], self.playlist_id)
        self.assertEqual(result["name"], "Test Playlist")
        self.assertEqual(len(result["tracks"]), 1)
        self.assertEqual(result["tracks"][0]["id"], "track1")
        self.assertEqual(result["tracks"][0]["name"], "Track 1")
        self.assertEqual(result["tracks"][0]["artists"], ["Artist 1"])


if __name__ == "__main__":
    unittest.main()
