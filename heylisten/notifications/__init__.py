"""
Notifications package for Heylisten - handles sending notifications to users about playlist changes.
"""

import os
from typing import Any, Dict, List, Optional

from loguru import logger

# Import notification services
try:
    from heylisten.notifications.discord import DiscordNotifier
    DISCORD_AVAILABLE = True
except ImportError:
    logger.warning("Discord notifications not available")
    DISCORD_AVAILABLE = False


class NotificationManager:
    """Manages notifications for playlist changes."""

    def __init__(self):
        # Configure notification settings
        self.enable_notifications = os.getenv("ENABLE_NOTIFICATIONS", "false").lower() == "true"
        
        # Initialize notification services
        self.discord = None
        self._init_discord()

    def _init_discord(self):
        """Initialize Discord notification service if configured."""
        if not DISCORD_AVAILABLE:
            return
            
        discord_app_id = os.getenv("DISCORD_APP_ID")
        discord_public_key = os.getenv("DISCORD_PUBLIC_KEY")
        discord_bot_token = os.getenv("DISCORD_BOT_TOKEN")
        
        if discord_app_id and discord_public_key:
            try:
                self.discord = DiscordNotifier(
                    app_id=discord_app_id,
                    public_key=discord_public_key,
                    bot_token=discord_bot_token
                )
                logger.info("Discord notification service initialized")
            except Exception as e:
                logger.error(f"Failed to initialize Discord notification service: {e}")

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

            # Log the notification attempt
            logger.info(
                f"Notifying user {user_id} about {added_count} additions and {removed_count} removals in '{playlist_name}'"
            )

            # Try to send via Discord if available
            discord_sent = False
            if self.discord:
                discord_sent = self.discord.send_notification(user_id, changes)
                if discord_sent:
                    logger.info(f"Discord notification sent to user {user_id}")
                
            # Example of formatting notification content for logging
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

            # Print notification details in logs
            if added_count > 0:
                logger.debug(f"Added tracks:\n{added_tracks_text}")
                if added_count > 5:
                    logger.debug(f"... and {added_count - 5} more")

            if removed_count > 0:
                logger.debug(f"Removed tracks:\n{removed_tracks_text}")
                if removed_count > 5:
                    logger.debug(f"... and {removed_count - 5} more")

            return discord_sent or True  # Return True if any notification was sent or if just logged

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

    def register_discord_webhook(self, user_id: str, webhook_url: str) -> bool:
        """
        Register a Discord webhook URL for a user.
        
        Args:
            user_id: Spotify user ID
            webhook_url: Discord webhook URL
            
        Returns:
            bool: True if registration was successful, False otherwise
        """
        if not self.discord:
            logger.error("Discord notification service not initialized")
            return False
            
        return self.discord.save_webhook_mapping(user_id, webhook_url)
