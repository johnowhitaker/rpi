import json
import os
import signal
import threading
from datetime import datetime
from typing import Generator

from flask import Flask, Response, jsonify, render_template, request, send_from_directory

from .camera_manager import CameraManager


APP_PORT = int(os.environ.get("PORT", "8000"))
CAPTURES_DIR = os.path.join(os.path.dirname(__file__), "captures")

app = Flask(__name__)
manager = CameraManager()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/cameras")
def api_cameras():
    return jsonify({"cameras": manager.list_cameras()})


def mjpeg_generator(cam_id: str) -> Generator[bytes, None, None]:
    boundary = b"--frame"
    ctrl = manager.get(cam_id)
    output = ctrl.output
    while True:
        with output.condition:
            output.condition.wait()
            frame = output.frame
        if frame is None:
            continue
        yield (
            boundary
            + b"\r\nContent-Type: image/jpeg\r\nContent-Length: "
            + str(len(frame)).encode()
            + b"\r\n\r\n"
            + frame
            + b"\r\n"
        )


@app.route("/stream/<cam_id>.mjpg")
def stream(cam_id: str):
    if cam_id not in {c["id"] for c in manager.list_cameras()}:
        return "Camera not found", 404
    headers = {"Age": "0", "Cache-Control": "no-cache, private", "Pragma": "no-cache"}
    return Response(
        mjpeg_generator(cam_id),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers=headers,
        direct_passthrough=True,
    )


@app.route("/api/<cam_id>/controls", methods=["GET", "POST"])
def controls_endpoint(cam_id: str):
    if cam_id not in {c["id"] for c in manager.list_cameras()}:
        return "Camera not found", 404
    ctrl = manager.get(cam_id)
    if request.method == "POST":
        try:
            data = request.get_json(force=True, silent=True) or {}
        except Exception:
            data = {}
        ctrl.set_controls(data)
        return jsonify({"status": "ok"})
    else:
        md = ctrl.get_metadata()
        return jsonify({"metadata": md})


@app.route("/api/<cam_id>/af_trigger", methods=["POST"])
def af_trigger(cam_id: str):
    if cam_id not in {c["id"] for c in manager.list_cameras()}:
        return "Camera not found", 404
    ctrl = manager.get(cam_id)
    data = request.get_json(force=True, silent=True) or {}
    trigger = data.get("trigger", "start")
    ctrl.set_controls({"af_trigger": trigger})
    return jsonify({"status": "ok"})


@app.route("/api/<cam_id>/capture", methods=["POST"])
def capture(cam_id: str):
    if cam_id not in {c["id"] for c in manager.list_cameras()}:
        return "Camera not found", 404
    ctrl = manager.get(cam_id)
    path = ctrl.capture_still(CAPTURES_DIR)
    filename = os.path.basename(path)
    return jsonify({
        "status": "ok",
        "filename": filename,
        "path": path,
        "url": f"/captures/{filename}",
    })


@app.route("/captures/<path:filename>")
def captures(filename: str):
    return send_from_directory(CAPTURES_DIR, filename, as_attachment=False)


@app.route("/api/presets", methods=["GET", "POST"])
def presets():
    presets_path = os.path.join(os.path.dirname(__file__), "presets.json")
    if request.method == "GET":
        if os.path.exists(presets_path):
            with open(presets_path, "r", encoding="utf-8") as f:
                return jsonify(json.load(f))
        return jsonify({"presets": {}})
    else:
        data = request.get_json(force=True, silent=True) or {}
        with open(presets_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return jsonify({"status": "ok"})


def _shutdown(*_):  # pragma: no cover
    try:
        manager.stop()
    finally:
        os._exit(0)


signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)


def run():  # pragma: no cover
    app.run(host="0.0.0.0", port=APP_PORT, threaded=True)


if __name__ == "__main__":  # pragma: no cover
    run()

