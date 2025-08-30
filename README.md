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
