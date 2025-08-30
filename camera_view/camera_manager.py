import io
import os
import threading
import time
from datetime import datetime

from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput

try:
    # Optional but preferred for AF/controls enums
    from libcamera import controls  # type: ignore
except Exception:  # pragma: no cover
    controls = None  # Fallback to raw values if enums unavailable


class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None  # type: bytes | None
        self.condition = threading.Condition()

    def writable(self) -> bool:  # type: ignore[override]
        return True

    def write(self, buf: bytes) -> int:  # type: ignore[override]
        # For MJPEGEncoder, each call to write is a complete JPEG frame
        with self.condition:
            self.frame = bytes(buf)
            self.condition.notify_all()
        return len(buf)


class CameraController:
    def __init__(self, index: int, label: str | None = None,
                 preview_size: tuple[int, int] = (640, 480)):
        self.index = index
        self.label = label or f"camera_{index}"
        self.lock = threading.RLock()
        self.picam2 = Picamera2(camera_num=index)

        # Create configurations
        self.preview_config = self.picam2.create_video_configuration(
            main={"size": preview_size}
        )
        self.still_config = self.picam2.create_still_configuration()

        self.picam2.configure(self.preview_config)

        # Streaming output for MJPEG
        self.output = StreamingOutput()
        self.encoder = MJPEGEncoder()

        # Start camera and MJPEG recording
        self.picam2.start()
        # Send encoded frames to our in-memory output
        self.picam2.start_recording(self.encoder, FileOutput(self.output))

    def get_metadata(self) -> dict:
        # Latest metadata snapshot (exposure, gains, etc.)
        try:
            md = self.picam2.capture_metadata()
            return md or {}
        except Exception:
            return {}

    def set_controls(self, ctrl: dict):
        # Translate some friendly keys if present
        m = {}
        for k, v in ctrl.items():
            if v is None:
                continue
            # Map common aliases
            if k == "exposure_time":
                m["ExposureTime"] = int(v)
            elif k == "analogue_gain" or k == "analog_gain":
                m["AnalogueGain"] = float(v)
            elif k == "ae_enable":
                m["AeEnable"] = bool(v)
            elif k == "awb_enable":
                m["AwbEnable"] = bool(v)
            elif k == "ev" or k == "exposure_value":
                m["ExposureValue"] = float(v)
            elif k == "lens_position":
                m["LensPosition"] = float(v)
            elif k == "awb_mode":
                # Allow string names (e.g., Auto, Tungsten, Daylight) or ints
                m["AwbMode"] = v
            elif k == "af_mode":
                m["AfMode"] = self._af_mode_value(v)
            elif k == "af_trigger":
                m["AfTrigger"] = self._af_trigger_value(v)
            elif k in ("brightness", "contrast", "saturation", "sharpness"):
                key = k.capitalize()
                m[key] = float(v)
            elif k == "noise_reduction_mode":
                m["NoiseReductionMode"] = v
            else:
                # Pass through raw control name
                m[k] = v

        if not m:
            return
        with self.lock:
            self.picam2.set_controls(m)

    def _af_mode_value(self, v):
        if controls is None:
            return v
        if isinstance(v, str):
            name = v.strip().lower()
            mapping = {
                "manual": controls.AfModeEnum.Manual,
                "auto": controls.AfModeEnum.Auto,
                "continuous": controls.AfModeEnum.Continuous,
            }
            return mapping.get(name, v)
        return v

    def _af_trigger_value(self, v):
        if controls is None:
            return v
        if isinstance(v, str):
            name = v.strip().lower()
            mapping = {
                "start": controls.AfTriggerEnum.Start,
                "cancel": controls.AfTriggerEnum.Cancel,
            }
            return mapping.get(name, v)
        return v

    def capture_still(self, dir_path: str) -> str:
        os.makedirs(dir_path, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{self.label}_{ts}.jpg"
        path = os.path.join(dir_path, filename)
        with self.lock:
            # Switch to still mode for full-res capture, then return to preview
            self.picam2.switch_mode_and_capture_file(self.still_config, path)
            # Back to preview automatically handled by switch_mode_and_capture_file
            self.picam2.set_controls({})
        return path

    def stop(self):
        with self.lock:
            try:
                self.picam2.stop_recording()
            except Exception:
                pass
            try:
                self.picam2.stop()
            except Exception:
                pass


class CameraManager:
    def __init__(self):
        self.controllers: dict[str, CameraController] = {}
        info = Picamera2.global_camera_info() or []
        for idx, cam in enumerate(info):
            label = cam.get("Model") or cam.get("Id") or f"cam{idx}"
            controller = CameraController(index=idx, label=label)
            self.controllers[str(idx)] = controller

    def list_cameras(self):
        cams = []
        for cam_id, ctrl in self.controllers.items():
            cams.append({
                "id": cam_id,
                "label": ctrl.label,
                "index": ctrl.index,
            })
        return cams

    def get(self, cam_id: str) -> CameraController:
        return self.controllers[cam_id]

    def stop(self):
        for ctrl in self.controllers.values():
            ctrl.stop()
