import base64
import io
import os
import signal
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

from flask import Flask, Response, jsonify, request, send_from_directory

from .serial_io import SerialManager
from .camera import CameraController, mjpeg_stream, transform_jpeg


# Defaults tailored to your setup
SERIAL_PORT = os.environ.get("PRINTER_PORT", "/dev/ttyUSB0")
SERIAL_BAUD = int(os.environ.get("PRINTER_BAUD", "115200"))
FEED_XY_DEFAULT = int(os.environ.get("FEED_XY", "1000"))
FEED_Z_DEFAULT = int(os.environ.get("FEED_Z", "100"))
SETTLE_DEFAULT = float(os.environ.get("SETTLE_SEC", "1.0"))
ANCHOR_X = float(os.environ.get("ANCHOR_X", "100"))
ANCHOR_Y = float(os.environ.get("ANCHOR_Y", "100"))
ANCHOR_Z = float(os.environ.get("ANCHOR_Z", "100"))

CAPTURES_DIR = os.path.join(os.path.dirname(__file__), "captures")


app = Flask(__name__)


class State:
    def __init__(self):
        self.serial: Optional[SerialManager] = None
        self.serial_lock = threading.Lock()
        self.camera = CameraController(index=0, label="rpi_cam0")
        self.settle_sec: float = SETTLE_DEFAULT
        self.feed_xy: int = FEED_XY_DEFAULT
        self.feed_z: int = FEED_Z_DEFAULT
        self.anchor = {"x": ANCHOR_X, "y": ANCHOR_Y, "z": ANCHOR_Z}


STATE = State()


def _ensure_serial() -> SerialManager:
    with STATE.serial_lock:
        if STATE.serial and STATE.serial.is_connected():
            return STATE.serial
        sm = SerialManager()
        sm.connect(SERIAL_PORT, SERIAL_BAUD)
        # Basic init: mm units, absolute mode
        sm.send_commands(["M115", "G21", "G90"], wait_ok=True)
        STATE.serial = sm
        return sm


def _parse_m114(line_bytes: bytes) -> Dict[str, float]:
    try:
        text = line_bytes.decode("ascii", errors="ignore")
    except Exception:
        text = ""
    # Typical: "X:0.000 Y:0.000 Z:0.000 E:0.000 Count X:0 Y:0 Z:0"
    vals: Dict[str, float] = {}
    for part in text.replace("\n", " ").split():
        if ":" in part:
            k, v = part.split(":", 1)
            try:
                vals[k] = float(v)
            except Exception:
                pass
    return {k.lower(): v for k, v in vals.items()}


@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "version": 1,
        "serial_connected": bool(STATE.serial and STATE.serial.is_connected()),
        "feed_xy": STATE.feed_xy,
        "feed_z": STATE.feed_z,
        "settle_sec": STATE.settle_sec,
    })


# -------------------- Printer endpoints --------------------


@app.post("/printer/connect")
def printer_connect():
    try:
        _ensure_serial()
        return jsonify({"ok": True, "port": SERIAL_PORT, "baud": SERIAL_BAUD})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/printer/home")
def printer_home():
    axes = (request.json or {}).get("axes", "XYZ")
    axes = "".join(ch for ch in str(axes).upper() if ch in "XYZ") or "XYZ"
    sm = _ensure_serial()
    sm.send_commands([f"G28 {axes}", "G90"], wait_ok=True)
    return jsonify({"ok": True})


@app.post("/printer/set_center")
def printer_set_center():
    data = request.get_json(force=True, silent=True) or {}
    x = float(data.get("x", STATE.anchor["x"]))
    y = float(data.get("y", STATE.anchor["y"]))
    z = float(data.get("z", STATE.anchor["z"]))
    STATE.anchor = {"x": x, "y": y, "z": z}
    sm = _ensure_serial()
    sm.send_commands([f"G92 X{x:.3f} Y{y:.3f} Z{z:.3f}", "G90"], wait_ok=True)
    return jsonify({"ok": True, "anchor": STATE.anchor})


@app.post("/printer/move")
def printer_move():
    data = request.get_json(force=True, silent=True) or {}
    x = data.get("x")
    y = data.get("y")
    z = data.get("z")
    feed_xy = int(data.get("feed_xy", STATE.feed_xy))
    feed_z = int(data.get("feed_z", STATE.feed_z))
    wait = bool(data.get("wait", True))
    safe = bool(data.get("safe", False))

    sm = _ensure_serial()
    cmds: list[str] = ["G90"]  # absolute moves

    # Simple strategy: split XY vs Z so we can use different feedrates
    def add_xy():
        parts = ["G0", f"F{feed_xy}"]
        if x is not None:
            parts.append(f"X{float(x):.4f}")
        if y is not None:
            parts.append(f"Y{float(y):.4f}")
        if len(parts) > 2:
            cmds.append(" ".join(parts))

    def add_z():
        if z is not None:
            cmds.append(f"G0 F{feed_z} Z{float(z):.4f}")

    if safe and z is not None and (x is not None or y is not None):
        # Raise first to target Z (or leave Z unchanged if target higher)
        add_z()
        add_xy()
    else:
        add_xy()
        add_z()

    if wait:
        cmds.append("M400")
    sm.send_commands(cmds, wait_ok=True)
    return jsonify({"ok": True})


@app.get("/printer/position")
def printer_position():
    sm = _ensure_serial()
    # Request a position report and read until ok; capture the last line with coords
    # Using a small hack: send M114 and immediately read one line from serial
    # via private method by sending commands individually.
    try:
        sm.send_commands(["M114"], wait_ok=True)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    # Position will have been printed before the ok; we cannot easily grab it
    # without modifying SerialManager to expose reads. Return anchor and feeds.
    # If needed, we can later extend SerialManager to read the line.
    return jsonify({
        "ok": True,
        "note": "For exact coords, extend SerialManager to read M114 response.",
        "anchor": STATE.anchor,
        "feed_xy": STATE.feed_xy,
        "feed_z": STATE.feed_z,
    })


@app.post("/printer/stop")
def printer_stop():
    sm = _ensure_serial()
    sm.send_commands(["M112"], wait_ok=False)
    return jsonify({"ok": True})


@app.post("/config")
def update_config():
    data = request.get_json(force=True, silent=True) or {}
    if "feed_xy" in data:
        try:
            STATE.feed_xy = max(1, int(data["feed_xy"]))
        except Exception:
            pass
    if "feed_z" in data:
        try:
            STATE.feed_z = max(1, int(data["feed_z"]))
        except Exception:
            pass
    if "settle_sec" in data:
        try:
            STATE.settle_sec = max(0.0, float(data["settle_sec"]))
        except Exception:
            pass
    return jsonify({"ok": True, "feed_xy": STATE.feed_xy, "feed_z": STATE.feed_z, "settle_sec": STATE.settle_sec})


# -------------------- Camera endpoints --------------------


@app.get("/camera/metadata")
def camera_metadata():
    return jsonify({"metadata": STATE.camera.get_metadata()})


@app.post("/camera/controls")
def camera_controls():
    data = request.get_json(force=True, silent=True) or {}
    STATE.camera.set_controls(data)
    return jsonify({"ok": True})


@app.get("/camera/caps")
def camera_caps():
    # Expose a list of control keys we accept plus current metadata snapshot
    controls_supported = [
        "ae_enable",
        "awb_enable",
        "exposure_time",
        "analogue_gain",
        "ev",
        "af_mode",
        "af_trigger",
        "lens_position",
        "awb_mode",
        "noise_reduction_mode",
        "brightness",
        "contrast",
        "saturation",
        "sharpness",
    ]
    return jsonify({
        "controls_supported": controls_supported,
        "metadata": STATE.camera.get_metadata(),
    })


@app.get("/preview.mjpg")
def preview_full():
    headers = {"Age": "0", "Cache-Control": "no-cache, private", "Pragma": "no-cache"}
    return Response(
        mjpeg_stream(STATE.camera.output, transform=False),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers=headers,
        direct_passthrough=True,
    )


@app.get("/preview_crop.mjpg")
def preview_crop():
    args = request.args
    cw = int(args.get("cw", 1400))
    ch = int(args.get("ch", 1400))
    ox = int(args.get("ox", 0))
    oy = int(args.get("oy", 200))
    flip = str(args.get("flip", "0")).lower() in ("1", "true", "yes")
    fps = int(args.get("fps", 8))
    quality = int(args.get("quality", 75))
    headers = {"Age": "0", "Cache-Control": "no-cache, private", "Pragma": "no-cache"}
    return Response(
        mjpeg_stream(
            STATE.camera.output, transform=True, cw=cw, ch=ch, ox=ox, oy=oy, flip=flip, quality=quality, fps=fps
        ),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers=headers,
        direct_passthrough=True,
    )


@app.get("/capture")
def capture():
    args = request.args
    mode = str(args.get("mode", "crop")).lower()  # full|crop|both
    cw = int(args.get("cw", 1400))
    ch = int(args.get("ch", 1400))
    ox = int(args.get("ox", 0))
    oy = int(args.get("oy", 200))
    flip = str(args.get("flip", "1")).lower() in ("1", "true", "yes")
    quality = int(args.get("quality", 85))
    save = str(args.get("save", "0")).lower() in ("1", "true", "yes")
    session = args.get("session") or datetime.now().strftime("%Y%m%d")

    img = STATE.camera.capture_jpeg_bytes()
    payload = transform_jpeg(img, mode=mode, cw=cw, ch=ch, ox=ox, oy=oy, flip=flip, quality=quality)

    headers = {"Cache-Control": "no-store", "Content-Disposition": 'inline; filename="capture.jpg"'}
    if save:
        dir_path = os.path.join(CAPTURES_DIR, session)
        os.makedirs(dir_path, exist_ok=True)
        ts = datetime.now().strftime("%H%M%S_%f")
        name = f"img_{ts}.jpg"
        out_path = os.path.join(dir_path, name)
        with open(out_path, "wb") as f:
            f.write(payload)
        headers["X-Saved-Filename"] = name
        headers["X-Saved-Url"] = f"/captures/{session}/{name}"
    return Response(payload, mimetype="image/jpeg", headers=headers)


@app.get("/captures/<path:subpath>")
def serve_captures(subpath: str):
    return send_from_directory(CAPTURES_DIR, subpath)


@app.post("/macro/move_and_capture")
def macro_move_and_capture():
    data = request.get_json(force=True, silent=True) or {}
    # Motion
    x = data.get("x")
    y = data.get("y")
    z = data.get("z")
    feed_xy = int(data.get("feed_xy", STATE.feed_xy))
    feed_z = int(data.get("feed_z", STATE.feed_z))
    wait = bool(data.get("wait", True))
    settle = float(data.get("settle_sec", STATE.settle_sec))
    # Camera controls (optional)
    cam_ctrl = data.get("camera_controls") or {}
    cap = data.get("capture") or {}
    mode = str(cap.get("mode", "crop")).lower()
    cw = int(cap.get("cw", 1400))
    ch = int(cap.get("ch", 1400))
    ox = int(cap.get("ox", 0))
    oy = int(cap.get("oy", 200))
    flip = bool(cap.get("flip", True))
    quality = int(cap.get("quality", 85))
    ret_mode = str(cap.get("return", "path")).lower()  # path|inline_base64
    save = bool(cap.get("save", True))
    session = cap.get("session") or datetime.now().strftime("%Y%m%d")

    # Ensure serial + move
    sm = _ensure_serial()
    cmds = ["G90"]
    if x is not None or y is not None:
        parts = ["G0", f"F{feed_xy}"]
        if x is not None:
            parts.append(f"X{float(x):.4f}")
        if y is not None:
            parts.append(f"Y{float(y):.4f}")
        cmds.append(" ".join(parts))
    if z is not None:
        cmds.append(f"G0 F{feed_z} Z{float(z):.4f}")
    if wait:
        cmds.append("M400")
    sm.send_commands(cmds, wait_ok=True)

    # Apply camera controls + settle
    if cam_ctrl:
        STATE.camera.set_controls(cam_ctrl)
    if settle > 0:
        time.sleep(settle)

    # Capture
    img = STATE.camera.capture_jpeg_bytes()
    payload = transform_jpeg(img, mode=mode, cw=cw, ch=ch, ox=ox, oy=oy, flip=flip, quality=quality)

    # Save if requested
    saved_path = None
    if save:
        dir_path = os.path.join(CAPTURES_DIR, session)
        os.makedirs(dir_path, exist_ok=True)
        ts = datetime.now().strftime("%H%M%S_%f")
        name = f"img_{ts}.jpg"
        saved_path = os.path.join(dir_path, name)
        with open(saved_path, "wb") as f:
            f.write(payload)

    if ret_mode == "inline_base64":
        b64 = base64.b64encode(payload).decode("ascii")
        return jsonify({"ok": True, "image_base64": b64, "path": saved_path})
    else:
        return jsonify({"ok": True, "path": saved_path})


def run():  # pragma: no cover
    port = int(os.environ.get("PORT", "8500"))
    app.run(host="0.0.0.0", port=port, threaded=True)


def _shutdown(*_):  # pragma: no cover
    try:
        with STATE.serial_lock:
            if STATE.serial:
                try:
                    STATE.serial.disconnect()
                except Exception:
                    pass
    finally:
        os._exit(0)


signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)


if __name__ == "__main__":  # pragma: no cover
    run()
