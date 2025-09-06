import threading
import time
from typing import Iterable, Optional


try:
    import serial  # type: ignore
except Exception:  # pragma: no cover
    serial = None  # type: ignore


class SerialManager:
    """Minimal pyserial wrapper for Marlin/RepRap style 'ok' protocol."""

    def __init__(self):
        self._ser: Optional[serial.Serial] = None  # type: ignore
        self._lock = threading.Lock()

    def connect(self, port: str, baud: int = 115200, timeout: float = 1.0):
        if serial is None:
            raise RuntimeError("pyserial not available")
        ser = serial.Serial(port, baudrate=baud, timeout=timeout)
        # Some controllers reset on open; wait briefly
        time.sleep(2.0)
        with self._lock:
            self._ser = ser

    def disconnect(self):
        with self._lock:
            if self._ser is not None:
                try:
                    self._ser.flush()
                except Exception:
                    pass
                self._ser.close()
            self._ser = None

    def is_connected(self) -> bool:
        with self._lock:
            return bool(self._ser and self._ser.is_open)

    def _write_line(self, line: str):
        if self._ser is None:
            raise RuntimeError("serial not connected")
        payload = (line.strip() + "\n").encode("ascii")
        self._ser.write(payload)
        self._ser.flush()

    def _read_until_ok(self, timeout: float = 5.0):
        if self._ser is None:
            raise RuntimeError("serial not connected")
        ser = self._ser
        start = time.time()
        while time.time() - start < timeout:
            line = ser.readline()
            if not line:
                continue
            low = line.strip().lower()
            if low == b"ok" or low.endswith(b" ok"):
                return
            # ignore informational lines
        raise TimeoutError("Timeout waiting for ok from printer")

    def send_commands(self, commands: Iterable[str], wait_ok: bool = True):
        with self._lock:
            for cmd in commands:
                self._write_line(cmd)
                if wait_ok:
                    self._read_until_ok()

