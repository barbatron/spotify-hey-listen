# Heylisten: Spotify Playlist Monitor

A Python application that monitors a Spotify collaborative playlist for changes
and logs when tracks are added or removed.

## Setup

1. Make sure you have [Poetry](https://python-poetry.org/docs/#installation)
   installed.

2. Install dependencies:
   ```bash
   poetry install
   ```

3. Configure the `.env` file with your Spotify credentials and playlist ID:
   ```
   SPOT_CLIENT_ID=your_spotify_client_id
   SPOT_CLIENT_SECRET=your_spotify_client_secret
   SPOT_REDIRECT_URI=your_redirect_uri
   SPOT_PLAYLIST_ID=your_playlist_id_to_monitor
   ```

## Usage

Run the application:

```bash
poetry run python -m heylisten.main
```

The application will:

- Check the specified playlist every 5 minutes
- Compare with the previous state
- Log any changes (tracks added or removed)
- Store logs in `heylisten.log`

## Development

This project uses Ruff for linting. Run:

```bash
poetry run ruff check .
```
