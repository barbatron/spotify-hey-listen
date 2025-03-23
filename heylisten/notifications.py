"""
Notifications module for Heylisten - handles sending notifications to users about playlist changes.
"""

import os
from typing import Dict, List, Any

from loguru import logger


class NotificationManager:
    """Manages notifications for playlist changes."""

    def __init__(self):
        # Configure notification settings
        # Could be extended to support multiple notification methods
        self.enable_notifications = os.getenv("ENABLE_NOTIFICATIONS", "false").lower() == "true"

    def notify_user(self, user_id: str, changes: Dict[str, Any]) -> bool:
        """
        Notify a user about changes to their monitored playlist.

        Args:
            user_id: The Spotify user ID to notify
            changes: Dictionary containing change information

        Returns:
            bool: True if notification was sent successfully, False otherwise
        """
        if not self.enable_notifications:
            logger.debug(f"Notifications disabled. Would have notified user {user_id}")
            return False

        try:
            playlist_name = changes["playlist_name"]
            added_count = len(changes["added_tracks"])
            removed_count = len(changes["removed_tracks"])

            if added_count == 0 and removed_count == 0:
                return True  # No changes to notify about

            # Log the notification attempt (placeholder for actual notification)
            logger.info(
                f"Notifying user {user_id} about {added_count} additions and {removed_count} removals in '{playlist_name}'"
            )

            # This is where you would implement the actual notification logic
            # For example:
            # - Send an email
            # - Send a push notification
            # - Log to a database for display in the web UI

            # Example of formatting notification content
            added_tracks_text = "\n".join(
                [
                    f"- {track['name']} by {', '.join(track['artists'])} (added by {track['added_by']})"
                    for track in changes["added_tracks"][:5]  # Limit to first 5 for brevity
                ]
            )

            removed_tracks_text = "\n".join(
                [
                    f"- {track['name']} by {', '.join(track['artists'])}"
                    for track in changes["removed_tracks"][:5]  # Limit to first 5 for brevity
                ]
            )

            # Print notification details for demonstration
            if added_count > 0:
                logger.debug(f"Added tracks:\n{added_tracks_text}")
                if added_count > 5:
                    logger.debug(f"... and {added_count - 5} more")

            if removed_count > 0:
                logger.debug(f"Removed tracks:\n{removed_tracks_text}")
                if removed_count > 5:
                    logger.debug(f"... and {removed_count - 5} more")

            return True

        except Exception as e:
            logger.error(f"Failed to send notification to user {user_id}: {e}")
            return False

    def notify_users_of_changes(self, changes_list: List[Dict[str, Any]]) -> None:
        """
        Process a list of changes and send notifications to the relevant users.

        Args:
            changes_list: List of dictionaries containing change information
        """
        for changes in changes_list:
            user_id = changes.get("user_id")
            if user_id:
                self.notify_user(user_id, changes)
            else:
                logger.debug(
                    f"No user associated with playlist {changes['playlist_id']}, skipping notification"
                )
