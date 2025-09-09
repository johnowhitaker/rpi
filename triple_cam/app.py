import os
import signal
import threading
from datetime import datetime
from typing import Generator

from flask import Flask, Response, jsonify, render_template, request, send_from_directory
from flask import send_file
from flask import after_this_request
import io as _io
import re
import zipfile
import tempfile

from .camera_manager import CameraManager


APP_PORT = int(os.environ.get("PORT", "8010"))
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


@app.route("/api/<cam_id>/capture", methods=["POST"])  # capture and save still from a single Pi cam
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


@app.route("/api/triple_snap", methods=["POST"])  # receive phone image and capture both Pi cams
def triple_snap():
    # Expect multipart/form-data with field name 'phone' (image/jpeg or image/png)
    if "phone" not in request.files:
        return jsonify({"error": "Missing 'phone' file field"}), 400

    phone_file = request.files["phone"]
    # Common timestamp to correlate the trio
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    os.makedirs(CAPTURES_DIR, exist_ok=True)
    # Normalize phone extension
    ext = ".jpg"
    if phone_file.mimetype == "image/png" or (phone_file.filename and phone_file.filename.lower().endswith(".png")):
        ext = ".png"
    phone_name = f"phone_{ts}{ext}"
    phone_path = os.path.join(CAPTURES_DIR, phone_name)
    phone_file.save(phone_path)

    # Capture both Pi cameras concurrently for minimal skew
    cam_ids = [c["id"] for c in manager.list_cameras()]
    results: list[dict] = []
    threads: list[threading.Thread] = []
    captured: dict[str, str] = {}

    def do_cap(cid: str):
        ctrl = manager.get(cid)
        path = ctrl.capture_still(CAPTURES_DIR)
        captured[cid] = path

    for cid in cam_ids:
        t = threading.Thread(target=do_cap, args=(cid,), daemon=True)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

    for cid, path in captured.items():
        results.append({
            "cam_id": cid,
            "filename": os.path.basename(path),
            "url": f"/captures/{os.path.basename(path)}",
            "path": path,
        })

    return jsonify({
        "status": "ok",
        "timestamp": ts,
        "phone": {"filename": phone_name, "url": f"/captures/{phone_name}", "path": phone_path},
        "pi": results,
    })


@app.route("/api/history")
def history():
    os.makedirs(CAPTURES_DIR, exist_ok=True)
    files = []
    try:
        for name in os.listdir(CAPTURES_DIR):
            if not (name.lower().endswith('.jpg') or name.lower().endswith('.png')):
                continue
            files.append(name)
    except FileNotFoundError:
        pass
    # Group by timestamp pattern _YYYYmmdd_HHMMSS_mmmuuu
    pat = re.compile(r"_(\d{8}_\d{6}_\d{6})\.(jpg|png)$", re.IGNORECASE)
    groups: dict[str, list[dict]] = {}
    for fn in files:
        m = pat.search(fn)
        if not m:
            # Skip non-conforming names
            continue
        ts = m.group(1)
        kind = 'phone' if fn.startswith('phone_') else 'pi'
        label = None
        if kind == 'pi':
            label = fn.rsplit('_' + ts, 1)[0]
        groups.setdefault(ts, []).append({
            'name': fn,
            'url': f'/captures/{fn}',
            'type': kind,
            'label': label,
        })
    # Sort groups by timestamp desc
    out = []
    for ts in sorted(groups.keys(), reverse=True):
        out.append({'timestamp': ts, 'files': groups[ts]})
    return jsonify({'groups': out})


def _zip_files_response(filepaths: list[str], zip_basename: str):
    # Write to temporary file to avoid high memory usage
    tmp = tempfile.NamedTemporaryFile(suffix='.zip', delete=False)
    tmp_path = tmp.name
    tmp.close()
    with zipfile.ZipFile(tmp_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for fp in filepaths:
            if not os.path.isfile(fp):
                continue
            arcname = os.path.basename(fp)
            zf.write(fp, arcname)

    @after_this_request
    def _cleanup(response):  # pragma: no cover
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        return response

    return send_file(tmp_path, mimetype='application/zip', as_attachment=True,
                     download_name=f'{zip_basename}.zip')


@app.route('/api/zip_all')
def zip_all():
    os.makedirs(CAPTURES_DIR, exist_ok=True)
    fpaths = [os.path.join(CAPTURES_DIR, f) for f in os.listdir(CAPTURES_DIR)
              if f.lower().endswith(('.jpg', '.png'))]
    base = 'captures_all_' + datetime.now().strftime('%Y%m%d_%H%M%S')
    return _zip_files_response(fpaths, base)


@app.route('/api/zip_set/<ts>')
def zip_set(ts: str):
    # Basic validation of ts format
    if not re.match(r"^\d{8}_\d{6}_\d{6}$", ts):
        return 'Bad timestamp', 400
    os.makedirs(CAPTURES_DIR, exist_ok=True)
    fpaths = []
    for f in os.listdir(CAPTURES_DIR):
        if f.endswith(f'_{ts}.jpg') or f.endswith(f'_{ts}.png'):
            fpaths.append(os.path.join(CAPTURES_DIR, f))
    if not fpaths:
        return 'Not found', 404
    base = f'captures_{ts}'
    return _zip_files_response(fpaths, base)


def _shutdown(*_):  # pragma: no cover
    try:
        manager.stop()
    finally:
        os._exit(0)


signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)


def run():  # pragma: no cover
    ssl_ctx = None
    cert = os.environ.get("SSL_CERT")
    key = os.environ.get("SSL_KEY")
    if cert and key and os.path.exists(cert) and os.path.exists(key):
        ssl_ctx = (cert, key)
    app.run(host="0.0.0.0", port=APP_PORT, threaded=True, ssl_context=ssl_ctx)


if __name__ == "__main__":  # pragma: no cover
    run()
