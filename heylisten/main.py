import os
import sys
import threading
import time

import schedule
from dotenv import load_dotenv
from loguru import logger

from heylisten.playlist_monitor import PlaylistMonitor

# Load environment variables
load_dotenv()

# Configure logger
logger.add("heylisten.log", rotation="10 MB", retention="7 days")


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
