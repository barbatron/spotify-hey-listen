"""Discord notification service for Heylisten."""

import json
import os
from typing import Dict, Any, List, Optional

import requests
from loguru import logger


class DiscordNotifier:
    """Discord notification service that sends playlist changes to a webhook."""

    def __init__(self, app_id: str, public_key: str, bot_token: Optional[str] = None):
        """
        Initialize Discord notifier.

        Args:
            app_id: Discord application ID
            public_key: Discord application public key
            bot_token: Discord bot token (optional)
        """
        self.app_id = app_id
        self.public_key = public_key
        self.bot_token = bot_token
        self.webhook_urls = {}  # Map of user_id -> webhook_url
        self._load_webhook_mappings()
    
    def _load_webhook_mappings(self):
        """Load webhook mappings from configuration file."""
        from heylisten.config import data_dir
        
        webhook_file = data_dir / "discord_webhooks.json"
        if webhook_file.exists():
            try:
                with open(webhook_file, "r") as f:
                    self.webhook_urls = json.load(f)
                logger.info(f"Loaded {len(self.webhook_urls)} Discord webhook mappings")
            except Exception as e:
                logger.error(f"Failed to load Discord webhook mappings: {e}")

    def save_webhook_mapping(self, user_id: str, webhook_url: str) -> bool:
        """
        Save a mapping between a Spotify user and a Discord webhook.
        
        Args:
            user_id: Spotify user ID
            webhook_url: Discord webhook URL
            
        Returns:
            bool: True if saved successfully, False otherwise
        """
        from heylisten.config import data_dir
        
        self.webhook_urls[user_id] = webhook_url
        
        webhook_file = data_dir / "discord_webhooks.json"
        try:
            with open(webhook_file, "w") as f:
                json.dump(self.webhook_urls, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Failed to save Discord webhook mapping: {e}")
            return False

    def send_notification(self, user_id: str, changes: Dict[str, Any]) -> bool:
        """
        Send a Discord notification for playlist changes.

        Args:
            user_id: Spotify user ID to notify
            changes: Dictionary containing change information

        Returns:
            bool: True if notification was sent successfully, False otherwise
        """
        webhook_url = self.webhook_urls.get(user_id)
        if not webhook_url:
            logger.warning(f"No Discord webhook URL configured for user {user_id}")
            return False

        try:
            playlist_name = changes["playlist_name"]
            added_tracks = changes["added_tracks"]
            removed_tracks = changes["removed_tracks"]
            
            if not added_tracks and not removed_tracks:
                return True  # No changes to notify about
            
            # Create Discord embed
            embed = self._create_embed(playlist_name, added_tracks, removed_tracks)
            
            # Send to Discord webhook
            payload = {"embeds": [embed]}
            response = requests.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 204:
                logger.info(f"Discord notification sent successfully for user {user_id}")
                return True
            else:
                logger.error(f"Failed to send Discord notification: {response.status_code} {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error sending Discord notification: {e}")
            return False
            
    def _create_embed(self, playlist_name: str, added_tracks: List[Dict], removed_tracks: List[Dict]) -> Dict[str, Any]:
        """
        Create a Discord embed message for playlist changes.
        
        Args:
            playlist_name: Name of the playlist
            added_tracks: List of added tracks
            removed_tracks: List of removed tracks
            
        Returns:
            Dict containing the Discord embed object
        """
        added_count = len(added_tracks)
        removed_count = len(removed_tracks)
        
        # Create description with stats
        description = f"**{added_count}** tracks added, **{removed_count}** tracks removed"
        
        embed = {
            "title": f"Playlist '{playlist_name}' Updated",
            "description": description,
            "color": 3447003,  # Blue color
            "fields": []
        }
        
        # Add field for added tracks
        if added_tracks:
            added_tracks_text = "\n".join([
                f"• {track['name']} by {', '.join(track['artists'])} (added by {track['added_by']})"
                for track in added_tracks[:10]  # Limit to first 10
            ])
            
            if added_count > 10:
                added_tracks_text += f"\n... and {added_count - 10} more"
                
            embed["fields"].append({
                "name": "🆕 Added Tracks",
                "value": added_tracks_text
            })
            
        # Add field for removed tracks
        if removed_tracks:
            removed_tracks_text = "\n".join([
                f"• {track['name']} by {', '.join(track['artists'])}"
                for track in removed_tracks[:10]  # Limit to first 10
            ])
            
            if removed_count > 10:
                removed_tracks_text += f"\n... and {removed_count - 10} more"
                
            embed["fields"].append({
                "name": "❌ Removed Tracks",
                "value": removed_tracks_text
            })
            
        return embed
