# Heylisten: Spotify Playlist Monitor

A Python application that monitors a Spotify collaborative playlist for changes
and logs when tracks are added or removed. Includes a web interface to view the
current status.

## Setup

1. Make sure you have [Poetry](https://python-poetry.org/docs/#installation)
   installed.

2. Install dependencies:
   ```bash
   poetry install
   ```

3. Set up your Spotify Developer Application:
   - Go to
     [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/)
   - Create a new app
   - Add `http://localhost:8000/spotify/callback` to the Redirect URIs

4. Configure the `.env` file with your Spotify app credentials and more:
   ```
   SPOT_CLIENT_ID=your_spotify_client_id
   SPOT_CLIENT_SECRET=your_client_secret
   SPOT_REDIRECT_URI=http://localhost:8000/spotify/callback
   SPOT_PLAYLIST_MARKET=<iso_country_code>
   WEB_HOST=0.0.0.0
   WEB_PORT=8000
   ```

## Usage

Run the application:

```bash
./run.sh # poetry run python -m heylisten.main
```

The application will:

- Start a web server on port 8000 (configurable via WEB_PORT)
- Check the specified playlist every 5 minutes
- Compare with the previous state
- Log any changes (tracks added or removed)
- Store logs in `heylisten.log`

## Web Interface

Access the web interface by visiting:

```
http://localhost:8000
```

The web interface displays:

- Monitored playlists

### Loading Your Playlists

The interface includes a "Load My Playlists" button that allows you to:

1. Authenticate with your Spotify account
2. View your collaborative and personal playlists
3. Select a playlist to monitor

This feature uses Spotify's OAuth authentication to securely access your
playlists.

## Development

This project uses Ruff for linting. Run:

```bash
ci/format
ci/lint # optionally, --fix
```
