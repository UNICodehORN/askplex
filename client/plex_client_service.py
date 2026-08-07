#!/usr/bin/env python3

import requests
import threading
import time
import uuid
import json
import os
import xml.etree.ElementTree as ET

from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn

import sys
import os

sys.path.append(
    os.path.abspath(
        "../lambda"
    )
)

from askplex.config import PMS_SERVER_URL

# -------------------------
# Configuration
# -------------------------

PLEX_URL = PMS_SERVER_URL

SESSION_FILE = "plex_session.json"

CLIENT_IDENTIFIER = str(uuid.uuid4())

PLEX_PRODUCT = "AskPlex Client"
PLEX_VERSION = "0.1"

TIMELINE_INTERVAL = 10


# -------------------------
# Global Playback-State
# -------------------------

current_playback = None
playback_thread = None
stop_event = threading.Event()


app = FastAPI(
    title="AskPlex Client Service"
)


# -------------------------
# Datamodel
# -------------------------

class PlayRequest(BaseModel):
    ratingKey: str | None = None
    title: str | None = None
    artist: str | None = None



# -------------------------
# Plex Auth
# -------------------------

def authenticate():

    client_identifier = str(uuid.uuid4())


    headers = {
        "X-Plex-Product": PLEX_PRODUCT,
        "X-Plex-Version": PLEX_VERSION,
        "X-Plex-Client-Identifier": client_identifier,
        "Accept": "application/json"
    }


    # PIN erzeugen

    r = requests.post(
        "https://plex.tv/api/v2/pins",
        headers=headers
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
            }
        )

        r.raise_for_status()

        data = r.json()


        if data.get("authToken"):

            session = {

                "token":
                    data["authToken"],

                "client_identifier":
                    client_identifier

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
                "Plex Session saved:"
            )

            print(
                SESSION_FILE
            )


            return session


        time.sleep(2)

def load_session():

    if os.path.exists(SESSION_FILE):

        with open(SESSION_FILE) as f:
            return json.load(f)


    print("No Plex session found.")
    print("Start Authentication...")


    return authenticate()



# -------------------------
# Search Track
# -------------------------

def get_track_by_rating_key(rating_key):

    session = load_session()

    r = requests.get(
        f"{PLEX_URL}/library/metadata/{rating_key}",
        headers={
            "X-Plex-Token": session["token"]
        }
    )

    r.raise_for_status()

    root = ET.fromstring(r.text)

    track = root.find("./Track")

    if track is None:
        track = root.find(".//Track")

    if track is None:
        raise RuntimeError("Track not found")

    return {
        "ratingKey": track.attrib["ratingKey"],
        "key": track.attrib["key"],
        "duration": int(track.attrib["duration"]),
        "title": track.attrib.get("title"),
        "artist": track.attrib.get("grandparentTitle")
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
            "limit": 20
        }
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


        if track_title.lower() == title.lower():

            if artist:

                if track_artist.lower() != artist.lower():
                    continue


            return {
                "ratingKey": track.attrib["ratingKey"],
                "key": track.attrib["key"],
                "duration": int(track.attrib["duration"]),
                "title": track_title,
                "artist": track_artist
            }


    raise RuntimeError(
        "Track not found"
    )



# -------------------------
# Timeline
# -------------------------

def send_timeline(track, state="playing", position=0):

    session = load_session()


    params = {

        "key": track["key"],
        "ratingKey": track["ratingKey"],

        "state": state,

        "time": position,
        "duration": track["duration"],

        "viewOffset": position,

    }


    headers = {

        "X-Plex-Token":
            session["token"],

        "X-Plex-Client-Identifier":
            session["client_identifier"],

        "X-Plex-Session-Identifier":
            playback_session_id,

    }


    r = requests.get(
        PLEX_URL + "/:/timeline",
        headers=headers,
        params=params
    )


    print(
        "Timeline",
        state,
        position,
        r.status_code
    )



# -------------------------
# Playback Thread
# -------------------------

playback_session_id = None


def playback_worker(track):

    global playback_session_id


    playback_session_id = str(
        uuid.uuid4()
    )


    start = time.time()


    print(
        "Starte:",
        track["title"]
    )


    while not stop_event.is_set():

        elapsed = int(
            (time.time() - start)
            * 1000
        )


        if elapsed >= track["duration"]:
            break


        send_timeline(
            track,
            "playing",
            elapsed
        )


        time.sleep(
            TIMELINE_INTERVAL
        )


    send_timeline(
        track,
        "stopped",
        track["duration"]
    )


    print(
        "Finished:",
        track["title"]
    )



# -------------------------
# API
# -------------------------

@app.post("/play")
def play(req: PlayRequest):

    global playback_thread
    global current_playback


    stop_event.set()


    if playback_thread:
        playback_thread.join(
            timeout=2
        )


    stop_event.clear()

    if not req.ratingKey and not req.title:
        return {
            "status": "error",
            "message": "ratingKey or title must be given as input"
        }

    if req.ratingKey:
        track = get_track_by_rating_key(req.ratingKey)
    else:
        track = find_track(
            req.title,
            req.artist
        )


    current_playback = track


    playback_thread = threading.Thread(
        target=playback_worker,
        args=(track,),
        daemon=True
    )


    playback_thread.start()


    return {
        "status": "playing",
        "track": track
    }



@app.post("/stop")
def stop():

    stop_event.set()

    return {
        "status": "stopped"
    }



@app.get("/status")
def status():

    return {
        "playing": current_playback
    }



# -------------------------
# Start
# -------------------------

if __name__ == "__main__":

    load_session()
    print(PLEX_URL)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8080
    )