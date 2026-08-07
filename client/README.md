# AskPlex Client Service

The **AskPlex Client Service** is a small companion service for AskPlex that keeps the playback information in Plex up to date.

It is used to ensure that Plex correctly displays the currently playing track, for example:

> **Currently playing „song“ from „artist“**

When AskPlex starts a track through Alexa, the AskPlex Lambda function notifies this service. 
The client then communicates with the Plex Media Server and updates the active playback session.

Without the client service, playback through AskPlex may work, but Plex may not correctly show the currently playing title.

## Installation

The client requires **Python 3.10+**.

From the `client` directory, create and activate a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

Install the dependencies:

```bash
pip install -r requirements.txt
```

Start the service:

```bash
python3 plex_client_service.py
```

If the service starts successfully, you should see:

```text
INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
```

The client service is now running on port `8080`.

## Configure AskPlex

The AskPlex Lambda function needs to know where the client service can be reached.

Edit:

```text
lambda/askplex/config.py
```

and configure:

```python
PMS_CLIENT_ACTIVE = True
PMS_CLIENT_URL = "https://<your-url>"
PMS_CLIENT_TIMEOUT = 3
```

`PMS_CLIENT_URL` must be a URL that is reachable by the AskPlex Lambda function.

For example:

```python
PMS_CLIENT_ACTIVE = True
PMS_CLIENT_URL = "https://plex-client.example.com"
PMS_CLIENT_TIMEOUT = 3
```

### Important

The client service must be reachable from the internet because the AskPlex Lambda function runs outside your local network.

For a public installation, **HTTPS is strongly recommended**. A reverse proxy such as Nginx, Caddy or Traefik can be used to expose the service securely.

## Plex Authentication

On the first startup, the client may ask you to authenticate with Plex.

Open:

[Plex Link](https://plex.tv/link?utm_source=chatgpt.com)

Enter the PIN displayed by the service and confirm with **Enter**.

After successful authentication, the Plex session is stored locally for subsequent use.

Do **not** commit the generated `plex_session.json` file to Git.

## Verify

Once the service is running, AskPlex can notify it whenever playback starts.

The expected flow is:

```text
Alexa
  │
  ▼
AskPlex Lambda
  │
  │  playback information
  ▼
AskPlex Client Service
  │
  │  Plex API
  ▼
Plex Media Server
  │
  ▼
Currently playing:
"Song Name" – Artist
```

The client service does **not** play the music itself. 
Its main purpose is to make sure Plex knows which track AskPlex is currently playing.

## Optional: Docker setup
If you prefer to start the service as docker container, you can use this command template:
```
docker run -d \
  --name askplex-client \
  -p 8080:8080 \
  -v /opt/askplex:/opt/askplex \
  python:3.12 \
  bash -c "cd /opt/askplex/client && pip install -r requirements.txt && python3 plex_client_service.py"
``