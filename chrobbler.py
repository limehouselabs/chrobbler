#!/usr/bin/env python3
import argparse
import logging
import os
import time
import pylast
import pychromecast

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

RETRY_INTERVAL = 10

class ConnectionListener:
    def __init__(self):
        self.connected = True

    def new_connection_status(self, status):
        self.connected = status.status == "CONNECTED"


class TrackListener(pychromecast.controllers.media.MediaStatusListener):
    def __init__(self, lastfm):
        self.lastfm = lastfm
        self.last_content_id = None
        self.track_started_at = None
        self.scrobbled = False
        self.last_artist = None
        self.last_title = None
        self.last_album = None
        self.player_state = None

    def load_media_failed(self, item, error_code):
        pass

    def playing(self):
        return self.player_state in ("PLAYING", "BUFFERING")

    def new_media_status(self, status):
        self.player_state = status.player_state

        content_id = status.content_id
        if content_id == self.last_content_id:
            return
        self.last_content_id = content_id
        self.track_started_at = None
        self.scrobbled = False

        if not self.playing():
            return

        self.track_started_at = time.time()
        self.last_title = status.title
        self.last_artist = status.artist
        self.last_album = status.album_name

        logging.info(f"Playing: {self.last_artist} - {self.last_title} ({self.last_album})")

        try:
            self.lastfm.update_now_playing(
                artist=self.last_artist,
                title=self.last_title,
                album=self.last_album,
            )
            logging.info("Now playing updated.")
        except pylast.WSError as e:
            logging.error("Now playing update failed: %s", e)

    def check_scrobble(self):
        if (
            not self.scrobbled
            and self.track_started_at
            and self.playing()
            and time.time() - self.track_started_at >= 30
        ):
            self.scrobble()

    def scrobble(self):
        if self.scrobbled:
            return

        logging.info("Scrobbling...")
        try:
            self.lastfm.scrobble(
                artist=self.last_artist,
                title=self.last_title,
                timestamp=int(self.track_started_at),
                album=self.last_album,
            )
            self.scrobbled = True
            logging.info("Scrobbled!")
        except pylast.WSError as e:
            logging.error("Scrobble failed: %s", e)


def main():
    parser = argparse.ArgumentParser(description="Scrobble music played on a Chromecast device")
    parser.add_argument("name", help="Chromecast name")
    args = parser.parse_args()

    try:
        lastfm = pylast.LastFMNetwork(
            api_key=os.environ["LASTFM_API_KEY"],
            api_secret=os.environ["LASTFM_API_SECRET"],
            username=os.environ["LASTFM_USERNAME"],
            password_hash=pylast.md5(os.environ["LASTFM_PASSWORD"]),
        )
    except KeyError as e:
        logging.error("Missing last.fm credential environment var: %s", e)
        return

    while True:
        logging.info("Searching for '%s'...", args.name)
        chromecasts, browser = pychromecast.get_listed_chromecasts(friendly_names=[args.name])

        if not chromecasts:
            browser.stop_discovery()
            logging.info("Chromecast not found, retrying in %ss...", RETRY_INTERVAL)
            time.sleep(RETRY_INTERVAL)
            continue

        try:
            chromecast = chromecasts[0]
            chromecast.wait(timeout=10)
        except pychromecast.error.RequestTimeout as e:
            logging.error("Timed out connecting to chromecast")
            continue

        logging.info("Connected to %s", chromecast.name)

        conn_listener = ConnectionListener()
        chromecast.register_connection_listener(conn_listener)

        track_listener = TrackListener(lastfm)
        chromecast.media_controller.register_status_listener(track_listener)
        chromecast.media_controller.update_status()

        try:
            while conn_listener.connected:
                time.sleep(1)
                track_listener.check_scrobble()

        except KeyboardInterrupt:
            browser.stop_discovery()
            return

        logging.info("Disconnected from %s", chromecast.name)
        browser.stop_discovery()
        time.sleep(RETRY_INTERVAL)


if __name__ == "__main__":
    main()
