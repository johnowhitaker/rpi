# rpi
Raspberry Pi Tinkering - Ignore

## Setup

Raspberry Pi 5, with 2 camera modules (v3)

I used Raspberry Pi Imager to set up default image, set hostname + password, wifi settings and enable SSH.

apt update and upgrade, installed npm, installed codex. We're vibe-coding this - I take no responsibility for the code in this repo, a lot of it will be disposable software :)

## camera_view

A minimal Flask web app to preview two Raspberry Pi v3 camera modules and control still-image settings (exposure time, analogue gain/ISO, AE/AWB toggles, exposure compensation, autofocus modes/triggers, manual lens position, and basic image tuning). Supports full‑resolution still capture while keeping a low‑CPU MJPEG preview.

### Requirements

- Raspberry Pi OS Bookworm with camera stack enabled
- Python packages: `python3-picamera2` and `python3-flask`

On a fresh Pi OS, Picamera2 is typically preinstalled. If needed:

```bash
sudo apt update
sudo apt install -y python3-picamera2 python3-flask
```

### Run

From the repo root:

```bash
python3 -m camera_view.app
```

Open the UI in a browser on the same network:

```
http://<pi-hostname-or-ip>:8000/
```

- Live preview for both cameras appears with per‑camera controls.
- Click “Capture Still” to save a full‑res JPEG to `camera_view/captures/` (also accessible via a link shown after capture).

Notes:

- If manual exposure/ISO doesn’t take effect, disable “Auto Exposure” first.
- For manual focus, set AF Mode to “Manual”, then adjust Lens Position.

### HTTP API

All endpoints are available on the local network once the app is running (default port `8000`). Camera IDs are the strings listed by `GET /api/cameras` (typically `"0"`, `"1"`).

- `GET /api/cameras`: List detected cameras.
- `GET /stream/<cam_id>.mjpg`: MJPEG preview stream for a camera.
- `GET /api/<cam_id>/controls`: Current metadata snapshot for the camera.
- `POST /api/<cam_id>/controls`: Set one or more controls. Body is JSON; examples:
  - `{ "ae_enable": false }` — disable auto exposure
  - `{ "exposure_time": 2000 }` — manual exposure in microseconds
  - `{ "analogue_gain": 2.0 }` — manual analogue gain (ISO-ish)
  - `{ "awb_enable": false }` — disable auto white balance
  - `{ "contrast": 1.2, "saturation": 1.1, "sharpness": 1.0 }`
- `POST /api/<cam_id>/af_trigger`: Autofocus trigger. Body: `{ "trigger": "start" | "cancel" }`.

#### Stills Capture

Two capture modes are exposed at the same path based on HTTP method:

- `GET /api/<cam_id>/capture`
  - Returns the captured JPEG bytes directly (default: does not save to disk).
  - Response headers: `Content-Type: image/jpeg`, `Cache-Control: no-store`.
  - Query parameters:
    - `save=1` — also persist a copy to `camera_view/captures/` and include headers:
      - `X-Saved-Filename: <filename>`
      - `X-Saved-Url: /captures/<filename>`
    - `download=1` — set `Content-Disposition: attachment` so browsers download the file.
  - Examples:
    - `curl -s http://<host>:8000/api/0/capture -o snap.jpg`
    - `curl -s 'http://<host>:8000/api/0/capture?save=1' -o snap.jpg`
    - `curl -OJ 'http://<host>:8000/api/0/capture?download=1'`

- `POST /api/<cam_id>/capture`
  - Captures a still, saves it to disk, and returns JSON:
    ```json
    {
      "status": "ok",
      "filename": "<name>.jpg",
      "path": "/full/path/to/file.jpg",
      "url": "/captures/<name>.jpg"
    }
    ```

Saved images are served at `GET /captures/<filename>`.
