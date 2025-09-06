scan_api – unified motion + camera control on Raspberry Pi

Overview
- Single Flask app that directly drives your Ender 3 V3 SE over serial and controls the Raspberry Pi Camera Module v3 via Picamera2.
- Provides absolute-position G-code moves, set-center via G92, camera controls, live MJPEG preview (full or cropped), and capture-time crop/flip to match your ImageMagick workflow.

Defaults
- Serial: `/dev/ttyUSB0` at `115200` baud.
- Feeds: XY = 1000 mm/min, Z = 100 mm/min.
- Settle time: 1.0 s (configurable).
- Anchor: `G92 X100 Y100 Z100` (configurable via API).
- Crop defaults: 1400x1400, offset (ox=0, oy=200), vertical flip.

Run
1) On Raspberry Pi OS (Bookworm), ensure camera stack is enabled and Picamera2 installed:
   sudo apt update
   sudo apt install -y python3-picamera2 python3-flask python3-pil python3-serial

2) From repo root on the Pi:
   python3 -m rpi.scan_api.app

   The service listens on port 8500 by default (override with `PORT` env var).

Key Endpoints
- GET `/health`: basic status.
- POST `/printer/connect`: open serial, init G-code (mm + absolute).
- POST `/printer/home`: optional `{"axes":"XY"}`.
- POST `/printer/set_center`: `{"x":100,"y":100,"z":100}` (uses `G92`).
- POST `/printer/move`: `{"x":..,"y":..,"z":.., "feed_xy":1000, "feed_z":100, "wait":true}` (absolute; splits XY/Z for feeds).
- GET `/printer/position`: placeholder; anchor/feeds returned (M114 capture can be added if needed).
- POST `/printer/stop`: emergency stop (`M112`).

- GET `/camera/metadata`: latest Picamera2 metadata.
- POST `/camera/controls`: set controls (ae_enable, awb_enable, exposure_time, analogue_gain, ev, af_mode, af_trigger, lens_position, brightness, contrast, saturation, sharpness, noise_reduction_mode, awb_mode).
 - GET `/camera/caps`: supported control keys + current metadata snapshot.
 - GET `/camera/defaults`: return persisted default controls (applied at startup if present).
 - POST `/camera/defaults`: save default controls (accepts either `{...}` or `{defaults:{...}}`, `apply` flag default true).

- GET `/preview.mjpg`: full-frame MJPEG (low-res for responsiveness).
- GET `/preview_crop.mjpg`: cropped MJPEG stream with params: `cw`, `ch`, `ox`, `oy`, `flip`, `fps`, `quality`.

- GET `/capture`: still capture; query `mode=full|crop|both` (default crop), `cw`, `ch`, `ox`, `oy`, `flip`, `quality`, `save=0|1`, `session=YYYYMMDD`. Returns JPEG.

- POST `/macro/move_and_capture`: one-shot move + camera controls + capture. JSON body:
  {
    "x": 100.0, "y": 100.0, "z": 100.0,
    "feed_xy": 1000, "feed_z": 100, "wait": true, "settle_sec": 1.0,
    "camera_controls": { "ae_enable": false, "exposure_time": 2000, "analogue_gain": 2.0 },
    "capture": { "mode": "crop", "cw": 1400, "ch": 1400, "ox": 0, "oy": 200, "flip": true, "quality": 85, "save": true, "return": "path" }
  }

Notes
- The app is intentionally not generic: it targets your Ender 3 V3 SE and Pi Camera v3.
- If you want exact `M114` position parsing returned, we can extend `SerialManager` to read the response line and expose it.
- For best preview performance, keep `/preview_crop.mjpg` fps modest (5–10) due to per-frame JPEG decode/encode overhead.
