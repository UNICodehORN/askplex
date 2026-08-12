#!/usr/bin/env python3

import json
import os
import sys
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import requests
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

# ============================================================
# Import AskPlex configuration
# ============================================================

sys.path.append(
    os.path.abspath("../lambda")
)

from askplex.config import PMS_SERVER_URL

# ============================================================
# Configuration
# ============================================================

PLEX_URL = PMS_SERVER_URL

SESSION_FILE = "plex_session.json"

CLIENT_IDENTIFIER = str(uuid.uuid4())

PLEX_PRODUCT = "AskPlex Client"
PLEX_VERSION = "0.1"

# Interval (seconds) at which the background worker refreshes
# the Plex timeline for a playing/paused stream. Plex drops a
# session from "Now Playing" if it is not refreshed regularly.
TIMELINE_INTERVAL = 10

# How long a paused Plex session is kept alive
# before timeline updates stop completely.
PAUSE_HOLD_SECONDS = 10 * 60

# ============================================================
# FastAPI
# ============================================================

app = FastAPI(
    title="AskPlex Client Service"
)


# ============================================================
# Data models
# ============================================================

class PlayRequest(BaseModel):
    ratingKey: str | None = None
    title: str | None = None
    artist: str | None = None

    # Position (ms) reported by the controller. For a fresh
    # track this is 0.
    position: int = 0

    # Optional identifier for parallel playback streams.
    #
    # Example:
    #   Alexa device A -> "alexa-device-a"
    #   Alexa device B -> "alexa-device-b"
    #
    # If omitted, a default stream is used.
    streamId: str | None = None


class ControlRequest(BaseModel):
    """Payload for /pause, /resume and /stop."""

    streamId: str | None = None

    # Actual Alexa playback position (ms). The controller
    # reports this from the Alexa playback events, which is the
    # authoritative source of the real position.
    position: int | None = None

    # Present but unused for control actions.
    ratingKey: str | None = None


class StateRequest(BaseModel):
    streamId: str | None = None

    position: int | None = None

    # Supported:
    #   playing
    #   paused
    #   stopped
    #   ended
    state: str


# ============================================================
# Playback state
# ============================================================

@dataclass
class PlaybackState:
    stream_id: str
    track: dict

    # Plex session remains stable for this stream so Plex keeps
    # showing a single "Now Playing" entry per stream.
    session_id: str = field(
        default_factory=lambda: str(uuid.uuid4())
    )

    stop_event: threading.Event = field(
        default_factory=threading.Event
    )

    thread: threading.Thread | None = None

    # Last known playback position (ms). While playing, the live
    # position is this value plus the elapsed time since
    # playing_started_at.
    position: int = 0

    # Monotonic timestamp at which the current "playing" interval
    # started. None while paused/stopped.
    playing_started_at: float | None = None

    # Current Plex state.
    state: str = "stopped"

    # Incremented whenever the track changes. A worker exits as
    # soon as its captured generation no longer matches, so a new
    # worker cleanly supersedes the old one.
    generation: int = 0

    # Monotonic timestamp until which a paused/stopped session
    # should continue receiving Plex timeline updates.
    hold_until: float | None = None

# ============================================================
# All active playback streams
# ============================================================

#
# Key:
#   stream_id
#
# Value:
#   PlaybackState
#
# This allows multiple Alexa devices to play/update
# independently.
#


playbacks: dict[str, PlaybackState] = {}
playbacks_lock = threading.RLock()


# ============================================================
# Plex authentication
# ============================================================

# Cached Plex session so the worker loop does not hit disk on
# every timeline update.
_session_cache: dict | None = None
_session_lock = threading.Lock()


def authenticate():

    client_identifier = str(uuid.uuid4())

    headers = {
        "X-Plex-Product": PLEX_PRODUCT,
        "X-Plex-Version": PLEX_VERSION,
        "X-Plex-Client-Identifier": client_identifier,
        "Accept": "application/json",
    }

    # Create Plex PIN
    r = requests.post(
        "https://plex.tv/api/v2/pins",
        headers=headers,
        timeout=10,
    )

    r.raise_for_status()

    pin = r.json()

    print()
    print("==============================")
    print("Plex Login")
    print("==============================")
    print()
    print("Open:")
    print()
    print("https://plex.tv/link")
    print()
    print("Code:")
    print()
    print(pin["code"])
    print()

    input(
        "Press ENTER after you linked your account..."
    )

    while True:

        r = requests.get(
            f"https://plex.tv/api/v2/pins/{pin['id']}",
            headers=headers,
            params={
                "code": pin["code"]
            },
            timeout=10,
        )

        r.raise_for_status()

        data = r.json()

        if data.get("authToken"):

            session = {
                "token": data["authToken"],
                "client_identifier": client_identifier,
            }

            with open(
                SESSION_FILE,
                "w"
            ) as f:

                json.dump(
                    session,
                    f,
                    indent=2
                )

            print(
                "Plex Session saved:",
                SESSION_FILE
            )

            return session

        time.sleep(2)


def load_session():
    """
    Return the Plex session, loading it from disk (or running
    authentication) on first use and caching it afterwards.
    """

    global _session_cache

    with _session_lock:

        if _session_cache is not None:
            return _session_cache

        if os.path.exists(SESSION_FILE):

            with open(SESSION_FILE) as f:
                _session_cache = json.load(f)

            return _session_cache

        print("No Plex session found.")
        print("Start Authentication...")

        _session_cache = authenticate()

        return _session_cache


# ============================================================
# Plex helpers
# ============================================================

def get_current_position(playback: PlaybackState) -> int:
    """
    Return the current playback position in milliseconds,
    clamped to the track duration.

    While playing, the elapsed time since the current playing
    interval started is added to the stored position. While
    paused/stopped, the stored position is returned as-is.
    """

    with playbacks_lock:

        position = playback.position

        if (
            playback.state == "playing"
            and playback.playing_started_at is not None
        ):
            position += int(
                (
                    time.monotonic()
                    - playback.playing_started_at
                ) * 1000
            )

        return max(
            0,
            min(
                position,
                int(playback.track["duration"]),
            ),
        )


def get_track_by_rating_key(rating_key):

    session = load_session()

    r = requests.get(
        f"{PLEX_URL}/library/metadata/{rating_key}",
        headers={
            "X-Plex-Token": session["token"]
        },
        timeout=10,
    )

    r.raise_for_status()

    root = ET.fromstring(r.text)

    track = root.find("./Track")

    if track is None:
        track = root.find(".//Track")

    if track is None:
        raise RuntimeError(
            "Track not found"
        )

    return {
        "ratingKey": track.attrib["ratingKey"],
        "key": track.attrib["key"],
        "duration": int(track.attrib["duration"]),
        "title": track.attrib.get("title"),
        "artist": track.attrib.get("grandparentTitle"),
    }


def find_track(title, artist=None):

    session = load_session()

    url = PLEX_URL + "/library/all"

    r = requests.get(
        url,
        headers={
            "X-Plex-Token": session["token"]
        },
        params={
            "type": 10,
            "title": title,
            "limit": 20,
        },
        timeout=10,
    )

    r.raise_for_status()

    root = ET.fromstring(r.text)

    for track in root.findall("./Track"):

        track_title = track.attrib.get(
            "title"
        )

        track_artist = track.attrib.get(
            "grandparentTitle"
        )

        if not track_title:
            continue

        if track_title.lower() != title.lower():
            continue

        if artist:

            if not track_artist:
                continue

            if track_artist.lower() != artist.lower():
                continue

        return {
            "ratingKey": track.attrib["ratingKey"],
            "key": track.attrib["key"],
            "duration": int(track.attrib["duration"]),
            "title": track_title,
            "artist": track_artist,
        }

    raise RuntimeError(
        "Track not found"
    )


# ============================================================
# Plex Timeline
# ============================================================

def send_timeline(
    playback: PlaybackState,
    state: str,
    position: int | None = None,
):
    """
    Send a Plex timeline update.

    The Plex session identifier stays stable for the complete
    playback session of one stream, so each parallel stream shows
    up as its own "Now Playing" entry.
    """

    try:
        session = load_session()

        track = playback.track

        if position is None:
            position = get_current_position(
                playback
            )

        position = max(
            0,
            min(
                int(position),
                int(track["duration"]),
            )
        )

        params = {
            "key": track["key"],
            "ratingKey": track["ratingKey"],
            "state": state,
            "time": position,
            "duration": track["duration"],
            "viewOffset": position,
            "type": "music",
        }

        headers = {
            "X-Plex-Token": session["token"],

            "X-Plex-Client-Identifier":
                session["client_identifier"],

            "X-Plex-Session-Identifier":
                playback.session_id,
        }

        r = requests.get(
            PLEX_URL + "/:/timeline",
            headers=headers,
            params=params,
            timeout=10,
        )

        with playbacks_lock:
            playback.position = position
            playback.state = state
            # Keep the interpolation base in sync with what we
            # just reported to Plex.
            if state == "playing":
                playback.playing_started_at = time.monotonic()
            else:
                playback.playing_started_at = None

        print(
            f"Timeline "
            f"stream={playback.stream_id} "
            f"session={playback.session_id} "
            f"state={state} "
            f"position={position}/"
            f"{track['duration']} "
            f"status={r.status_code}"
        )

        if not r.ok:
            print(
                "Plex timeline response:",
                r.text
            )

    except Exception as exc:

        print(
            f"Timeline update failed "
            f"stream={playback.stream_id}:",
            repr(exc)
        )


# ============================================================
# Playback worker
# ============================================================

def playback_worker(playback: PlaybackState):
    """
    Background worker for a single stream.

    Periodically refreshes the Plex timeline so Plex keeps
    showing the stream in "Now Playing", and stops the stream
    once the track has fully played.

    The worker captures the stream's generation on start and
    exits as soon as the generation changes (i.e. a new track /
    worker superseded it), which keeps parallel streams and
    track switches race-free.
    """

    generation = playback.generation

    # Report the initial state to Plex immediately instead of
    # waiting a full interval.
    send_timeline(playback, state=playback.state)

    while not playback.stop_event.wait(TIMELINE_INTERVAL):

        with playbacks_lock:

            # A newer worker for this stream has taken over.
            if playback.generation != generation:
                return

            state = playback.state
            hold_until = playback.hold_until

        # ----------------------------------------------------
        # Paused hold period expired
        # ----------------------------------------------------

        if (
            state == "paused"
            and hold_until is not None
            and time.monotonic() >= hold_until
        ):

            with playbacks_lock:

                if playback.generation != generation:
                    return

                if playbacks.get(playback.stream_id) is playback:
                    del playbacks[playback.stream_id]

            print(
                "Plex session hold expired:",
                f"stream={playback.stream_id}"
            )

            return

        position = get_current_position(playback)

        # Track finished while playing -> stop and clean up.
        if (
            state == "playing"
            and position >= int(playback.track["duration"])
        ):
            send_timeline(
                playback,
                state="stopped",
                position=int(playback.track["duration"]),
            )

            with playbacks_lock:
                if playback.generation != generation:
                    return
                if playbacks.get(playback.stream_id) is playback:
                    del playbacks[playback.stream_id]

            print(
                "Playback finished:",
                f"stream={playback.stream_id}",
            )

            return

        # Refresh Plex with the current state (playing/paused).
        send_timeline(
            playback,
            state=state,
            position=position,
        )


def start_worker(playback: PlaybackState):
    """Spawn a fresh worker thread for a stream."""

    playback.stop_event.clear()

    playback.thread = threading.Thread(
        target=playback_worker,
        args=(playback,),
        daemon=True,
        name=f"playback-{playback.stream_id}",
    )

    playback.thread.start()


def stop_worker(playback: PlaybackState):
    """
    Signal a stream's worker to exit and wait for it (unless we
    are called from within that worker itself).
    """

    playback.stop_event.set()

    thread = playback.thread

    if (
        thread
        and thread.is_alive()
        and thread is not threading.current_thread()
    ):
        thread.join(timeout=2)


# ============================================================
# Stop one playback
# ============================================================

def stop_playback(
    stream_id: str,
    send_stopped=True,
):
    """
    Stop one playback stream.

    The current position is sent to Plex before the worker is
    terminated.
    """

    with playbacks_lock:

        playback = playbacks.get(
            stream_id
        )

        if playback is None:
            return False

        # Calculate the exact current position before changing
        # the state.
        current_position = get_current_position(
            playback
        )

        playback.position = current_position
        playback.playing_started_at = None
        playback.state = "stopped"

    # Send stopped BEFORE waiting for the worker.
    if send_stopped:

        send_timeline(
            playback,
            state="stopped",
            position=current_position,
        )

    stop_worker(playback)

    with playbacks_lock:

        # Only remove this exact playback object.
        if playbacks.get(
            stream_id
        ) is playback:

            del playbacks[
                stream_id
            ]

    print(
        "Stopped playback:",
        stream_id,
    )

    return True


# ============================================================
# Pause one playback
# ============================================================

def pause_playback(
    stream_id: str,
    position: int | None = None,
):
    """
    Pause an existing playback.

    The current position is stored and sent to Plex. The worker
    stays alive so it keeps refreshing the paused session in
    Plex and the playback can later be resumed.
    """

    with playbacks_lock:

        playback = playbacks.get(
            stream_id
        )

        if playback is None:
            return None

        # Prefer the position reported by the controller (the
        # real Alexa offset); otherwise interpolate.
        if position is None:
            position = get_current_position(playback)

        position = max(
            0,
            min(
                int(position),
                int(playback.track["duration"]),
            ),
        )

        playback.position = position
        playback.playing_started_at = None
        playback.state = "paused"
        playback.hold_until = (
            time.monotonic() + PAUSE_HOLD_SECONDS
        )

    # Tell Plex immediately.
    send_timeline(
        playback,
        state="paused",
        position=position,
    )

    print(
        "Paused playback:",
        f"stream={stream_id}",
        f"position={position}",
    )

    return playback


# ============================================================
# Resume one playback
# ============================================================

def resume_playback(
    stream_id: str,
    position: int | None = None,
):
    """
    Resume an existing paused playback.

    The existing Plex session_id is reused, so playback continues
    as the same session instead of creating a new one.
    """

    with playbacks_lock:

        playback = playbacks.get(
            stream_id
        )

        if playback is None:
            return None

        # Use the controller-reported position if present.
        if position is not None:
            playback.position = max(
                0,
                min(
                    int(position),
                    int(playback.track["duration"]),
                ),
            )

        playback.playing_started_at = time.monotonic()
        playback.state = "playing"
        playback.hold_until = None

        base_position = playback.position

        # If the worker died for any reason, revive it.
        worker_alive = (
            playback.thread is not None
            and playback.thread.is_alive()
        )

        if not worker_alive:
            playback.generation += 1
            start_worker(playback)

    send_timeline(
        playback,
        state="playing",
        position=base_position,
    )

    print(
        "Resumed playback:",
        f"stream={stream_id}",
        f"position={base_position}",
    )

    return playback


# ============================================================
# API: Play
# ============================================================

@app.post("/play")
def play(req: PlayRequest):

    if (
        not req.ratingKey
        and not req.title
    ):
        return {
            "status": "error",
            "message":
                "ratingKey or title must be given as input",
        }

    stream_id = (
        req.streamId
        or "default"
    )

    # --------------------------------------------------------
    # Resolve track
    # --------------------------------------------------------

    try:

        if req.ratingKey:

            track = get_track_by_rating_key(
                req.ratingKey
            )

        else:

            track = find_track(
                req.title,
                req.artist
            )

    except Exception as exc:

        print(
            "Unable to resolve track:",
            repr(exc)
        )

        return {
            "status": "error",
            "message": str(exc),
        }

    start_position = max(
        0,
        min(
            int(req.position or 0),
            int(track["duration"]),
        ),
    )

    # --------------------------------------------------------
    # Existing stream?
    # --------------------------------------------------------

    with playbacks_lock:

        playback = playbacks.get(
            stream_id
        )

    # ========================================================
    # Existing stream -> reuse the Plex session
    # ========================================================

    if playback is not None:

        print(
            "Updating existing playback:",
            f"stream={stream_id}",
            f"session={playback.session_id}",
            f"old={playback.track['title']}",
            f"new={track['title']}",
        )

        # Retire the old worker (generation bump makes it exit).
        with playbacks_lock:
            playback.generation += 1

        stop_worker(playback)

        # IMPORTANT: keep the SAME Plex session_id.
        with playbacks_lock:
            playback.track = track
            playback.position = start_position
            playback.playing_started_at = time.monotonic()
            playback.state = "playing"

        start_worker(playback)

        return {
            "status": "playing",
            "streamId": stream_id,
            "sessionId": playback.session_id,
            "track": track,
        }

    # ========================================================
    # New stream
    # ========================================================

    playback = PlaybackState(
        stream_id=stream_id,
        track=track,
    )

    playback.position = start_position
    playback.state = "playing"
    playback.playing_started_at = time.monotonic()

    with playbacks_lock:

        playbacks[stream_id] = playback

    start_worker(playback)

    print(
        "Playback created:",
        f"stream={stream_id}",
        f"session={playback.session_id}",
        f"title={track['title']}",
    )

    return {
        "status": "playing",
        "streamId": stream_id,
        "sessionId": playback.session_id,
        "track": track,
    }


# ============================================================
# API: Pause
# ============================================================

@app.post("/pause")
def pause(req: ControlRequest):

    stream_id = req.streamId or "default"

    playback = pause_playback(
        stream_id,
        position=req.position,
    )

    if playback is None:
        return {
            "status": "not_found",
            "streamId": stream_id,
        }

    return {
        "status": "paused",
        "streamId": stream_id,
        "sessionId": playback.session_id,
        "position": playback.position,
        "track": playback.track,
    }


# ============================================================
# API: Resume
# ============================================================

@app.post("/resume")
def resume(req: ControlRequest):

    stream_id = req.streamId or "default"

    playback = resume_playback(
        stream_id,
        position=req.position,
    )

    if playback is None:
        return {
            "status": "not_found",
            "streamId": stream_id,
        }

    return {
        "status": "playing",
        "streamId": stream_id,
        "sessionId": playback.session_id,
        "position": get_current_position(playback),
        "track": playback.track,
    }


# ============================================================
# API: Stop
# ============================================================

@app.post("/stop")
def stop(req: ControlRequest):

    # --------------------------------------------------------
    # Stop one stream
    # --------------------------------------------------------

    if req.streamId:

        stopped = stop_playback(
            req.streamId
        )

        return {
            "status": (
                "stopped"
                if stopped
                else "not_found"
            ),

            "streamId":
                req.streamId,
        }

    # --------------------------------------------------------
    # No streamId:
    # Stop all streams.
    # --------------------------------------------------------

    with playbacks_lock:

        stream_ids = list(
            playbacks.keys()
        )

    stopped_streams = []

    for stream_id in stream_ids:

        if stop_playback(
            stream_id
        ):

            stopped_streams.append(
                stream_id
            )

    return {
        "status": "stopped",
        "streams": stopped_streams,
    }


# ============================================================
# API: Generic playback state
# ============================================================

@app.post("/state")
def set_state(req: StateRequest):
    """
    Generic controller endpoint.

    Supported states:

        playing
        paused
        stopped
        ended

    This is useful if your controller sends a state directly
    instead of calling /pause or /resume.
    """

    stream_id = (
        req.streamId
        or "default"
    )

    state = req.state.lower().strip()

    if state not in {
        "playing",
        "paused",
        "stopped",
        "ended",
    }:

        return {
            "status": "error",
            "message":
                "state must be one of: "
                "playing, paused, stopped, ended",
        }

    # --------------------------------------------------------
    # PAUSED
    # --------------------------------------------------------

    if state == "paused":

        playback = pause_playback(
            stream_id,
            position=req.position,
        )

        if playback is None:

            return {
                "status": "not_found",
                "streamId": stream_id,
            }

        return {
            "status": "paused",
            "streamId": playback.stream_id,
            "sessionId": playback.session_id,
            "state": playback.state,
            "position": playback.position,
        }

    # --------------------------------------------------------
    # PLAYING
    # --------------------------------------------------------

    if state == "playing":

        playback = resume_playback(
            stream_id,
            position=req.position,
        )

        if playback is None:

            return {
                "status": "not_found",
                "streamId": stream_id,
            }

        return {
            "status": "playing",
            "streamId": playback.stream_id,
            "sessionId": playback.session_id,
            "state": playback.state,
            "position": get_current_position(playback),
        }

    # --------------------------------------------------------
    # STOPPED
    # --------------------------------------------------------

    if state == "stopped":

        stopped = stop_playback(
            stream_id
        )

        return {
            "status": (
                "stopped"
                if stopped
                else "not_found"
            ),
            "streamId": stream_id,
        }

    # --------------------------------------------------------
    # ENDED
    # --------------------------------------------------------

    if state == "ended":

        with playbacks_lock:

            playback = playbacks.get(
                stream_id
            )

            if playback is None:

                return {
                    "status": "not_found",
                    "streamId": stream_id,
                }

            position = int(playback.track["duration"])

            playback.position = position
            playback.playing_started_at = None
            playback.state = "ended"

        send_timeline(
            playback,
            state="stopped",
            position=position,
        )

        stop_worker(playback)

        with playbacks_lock:

            if playbacks.get(
                stream_id
            ) is playback:

                del playbacks[
                    stream_id
                ]

        return {
            "status": "ended",
            "streamId": stream_id,
            "sessionId": playback.session_id,
            "position": position,
        }


# ============================================================
# API: Status
# ============================================================

@app.get("/status")
def status():

    with playbacks_lock:

        result = {}

        for stream_id, playback in playbacks.items():

            position = get_current_position(
                playback
            )

            result[stream_id] = {

                "streamId":
                    playback.stream_id,

                "sessionId":
                    playback.session_id,

                "state":
                    playback.state,

                # Backwards-compatible boolean.
                "playing":
                    playback.state == "playing",

                "paused":
                    playback.state == "paused",

                "position":
                    position,

                "duration":
                    playback.track["duration"],

                "track":
                    playback.track,
            }

    return {
        "playbacks": result
    }


# ============================================================
# Start
# ============================================================

if __name__ == "__main__":

    load_session()

    print(
        "Plex URL:",
        PLEX_URL
    )

    print(
        "Client Identifier:",
        CLIENT_IDENTIFIER
    )

    print(
        "Timeline interval:",
        TIMELINE_INTERVAL,
        "seconds"
    )

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8080,
    )
