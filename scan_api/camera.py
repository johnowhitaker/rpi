import io
import os
import threading
import time
from datetime import datetime
from typing import Generator, Optional, Tuple

from PIL import Image, ImageOps

from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput

try:
    from libcamera import controls  # type: ignore
except Exception:  # pragma: no cover
    controls = None


class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame: Optional[bytes] = None
        self.condition = threading.Condition()

    def writable(self) -> bool:  # type: ignore[override]
        return True

    def write(self, buf: bytes) -> int:  # type: ignore[override]
        with self.condition:
            self.frame = bytes(buf)
            self.condition.notify_all()
        return len(buf)


class CameraController:
    def __init__(self, index: int = 0, label: Optional[str] = None,
                 preview_size: Tuple[int, int] = (640, 480)):
        self.index = index
        self.label = label or f"camera_{index}"
        self.lock = threading.RLock()
        self.picam2 = Picamera2(camera_num=index)

        # Simple configurations: low-res preview + still mode
        self.preview_config = self.picam2.create_video_configuration(
            main={"size": preview_size}
        )
        # Use still configuration; Picamera2 will JPEG-encode capture_file
        self.still_config = self.picam2.create_still_configuration(
            main={"size": self.picam2.sensor_resolution or preview_size}
        )

        self.picam2.configure(self.preview_config)

        self.output = StreamingOutput()
        self.encoder = MJPEGEncoder()

        self.picam2.start()
        self.picam2.start_recording(self.encoder, FileOutput(self.output))

    def get_metadata(self) -> dict:
        try:
            md = self.picam2.capture_metadata()
            return md or {}
        except Exception:
            return {}

    def set_controls(self, ctrl: dict):
        m = {}
        for k, v in (ctrl or {}).items():
            if v is None:
                continue
            if k == "exposure_time":
                m["ExposureTime"] = int(v)
            elif k in ("analogue_gain", "analog_gain"):
                m["AnalogueGain"] = float(v)
            elif k == "ae_enable":
                m["AeEnable"] = bool(v)
            elif k == "awb_enable":
                m["AwbEnable"] = bool(v)
            elif k in ("ev", "exposure_value"):
                m["ExposureValue"] = float(v)
            elif k == "lens_position":
                m["LensPosition"] = float(v)
            elif k == "awb_mode":
                awb = self._awb_mode_value(v)
                if awb is not None:
                    m["AwbMode"] = awb
            elif k == "noise_reduction_mode":
                nr = self._nr_mode_value(v)
                if nr is not None:
                    m["NoiseReductionMode"] = nr
            elif k == "af_mode":
                m["AfMode"] = self._af_mode_value(v)
            elif k == "af_trigger":
                m["AfTrigger"] = self._af_trigger_value(v)
            elif k in ("brightness", "contrast", "saturation", "sharpness"):
                m[k.capitalize()] = float(v)
            else:
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

    def _awb_mode_value(self, v):
        # Map string names to libcamera enums; skip if unknown to avoid type errors
        if isinstance(v, int):
            return v
        if controls is None:
            return None if isinstance(v, str) else v
        if isinstance(v, str):
            name = v.strip().lower()
            mapping = {
                "auto": getattr(controls.AwbModeEnum, "Auto", None),
                "incandescent": getattr(controls.AwbModeEnum, "Incandescent", None),
                "tungsten": getattr(controls.AwbModeEnum, "Tungsten", None),
                "fluorescent": getattr(controls.AwbModeEnum, "Fluorescent", None),
                "indoor": getattr(controls.AwbModeEnum, "Indoor", None),
                "daylight": getattr(controls.AwbModeEnum, "Daylight", None),
                "cloudy": getattr(controls.AwbModeEnum, "Cloudy", None),
                "shade": getattr(controls.AwbModeEnum, "Shade", None),
            }
            return mapping.get(name)
        return v

    def _nr_mode_value(self, v):
        # Map string names to libcamera draft enums; skip if unknown
        if isinstance(v, int):
            return v
        if controls is None:
            return None if isinstance(v, str) else v
        enum_cls = None
        try:
            enum_cls = getattr(getattr(controls, "draft"), "NoiseReductionModeEnum")  # type: ignore[attr-defined]
        except Exception:
            try:
                enum_cls = getattr(controls, "NoiseReductionModeEnum")
            except Exception:
                enum_cls = None
        if enum_cls is None:
            return None if isinstance(v, str) else v
        if isinstance(v, str):
            name = v.strip().lower()
            mapping = {
                "off": getattr(enum_cls, "Off", None),
                "fast": getattr(enum_cls, "Fast", None),
                "high_quality": getattr(enum_cls, "HighQuality", None),
                "minimal": getattr(enum_cls, "Minimal", None),
                "zsl": getattr(enum_cls, "ZSL", None),
                # 'auto' often isn't a valid enum; skip to avoid type error
            }
            return mapping.get(name)
        return v

    # -----------------
    # Capture utilities

    def capture_jpeg_bytes(self) -> bytes:
        import tempfile
        with self.lock:
            try:
                self.picam2.stop_recording()
            except Exception:
                pass
            self.picam2.switch_mode(self.still_config)
            buf = io.BytesIO()
            data: Optional[bytes] = None
            try:
                try:
                    self.picam2.capture_file(buf, format='jpeg')  # type: ignore[arg-type]
                    data = buf.getvalue()
                except TypeError:
                    buf.seek(0)
                    self.picam2.capture_file(buf)  # type: ignore[arg-type]
                    data = buf.getvalue()
            except Exception:
                tmp = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
                tmp_path = tmp.name
                tmp.close()
                try:
                    self.picam2.capture_file(tmp_path)
                    with open(tmp_path, 'rb') as f:
                        data = f.read()
                finally:
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass
            finally:
                self.picam2.switch_mode(self.preview_config)
                try:
                    self.picam2.start_recording(self.encoder, FileOutput(self.output))
                except Exception:
                    pass
        return data or b''

    def capture_file(self, dir_path: str) -> str:
        os.makedirs(dir_path, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{self.label}_{ts}.jpg"
        path = os.path.join(dir_path, filename)
        with self.lock:
            try:
                self.picam2.stop_recording()
            except Exception:
                pass
            self.picam2.switch_mode(self.still_config)
            self.picam2.capture_file(path)
            self.picam2.switch_mode(self.preview_config)
            try:
                self.picam2.start_recording(self.encoder, FileOutput(self.output))
            except Exception:
                pass
        return path


def crop_from_center(img: Image.Image, cw: int, ch: int, ox: int = 0, oy: int = 0) -> Image.Image:
    w, h = img.size
    cx = w // 2
    cy = h // 2
    left = int(cx - cw / 2 + ox)
    top = int(cy - ch / 2 + oy)
    right = left + int(cw)
    bottom = top + int(ch)
    # Clamp to image bounds
    left = max(0, min(left, w))
    top = max(0, min(top, h))
    right = max(0, min(right, w))
    bottom = max(0, min(bottom, h))
    if right <= left or bottom <= top:
        return img.copy()
    return img.crop((left, top, right, bottom))


def transform_jpeg(jpeg_bytes: bytes, *, mode: str = "crop",
                   cw: int = 1400, ch: int = 1400, ox: int = 0, oy: int = 200,
                   flip: bool = True, quality: int = 85) -> bytes:
    with Image.open(io.BytesIO(jpeg_bytes)) as im:
        im.load()
        out: Image.Image
        if mode == "full":
            out = im
        elif mode == "both":
            # Return crop; caller should request full separately if needed
            out = crop_from_center(im, cw, ch, ox, oy)
        else:  # "crop"
            out = crop_from_center(im, cw, ch, ox, oy)
        if flip:
            out = ImageOps.flip(out)
        buf = io.BytesIO()
        out.save(buf, format="JPEG", quality=max(1, min(100, int(quality))))
        return buf.getvalue()


def mjpeg_stream(output: StreamingOutput, *,
                 transform: bool = False,
                 cw: int = 1400, ch: int = 1400, ox: int = 0, oy: int = 200,
                 flip: bool = False, quality: int = 75, fps: int = 8) -> Generator[bytes, None, None]:
    boundary = b"--frame"
    min_interval = 1.0 / max(1, int(fps))
    last = 0.0
    while True:
        with output.condition:
            output.condition.wait()
            frame = output.frame
        if frame is None:
            continue
        now = time.time()
        if now - last < min_interval:
            continue
        last = now
        data = frame
        if transform:
            try:
                data = transform_jpeg(
                    frame, mode="crop", cw=cw, ch=ch, ox=ox, oy=oy, flip=flip, quality=quality
                )
            except Exception:
                data = frame
        yield (
            boundary
            + b"\r\nContent-Type: image/jpeg\r\nContent-Length: "
            + str(len(data)).encode()
            + b"\r\n\r\n"
            + data
            + b"\r\n"
        )
