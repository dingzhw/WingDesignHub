"""Stops only the recorded WingDesignHub server for this checkout."""
import ctypes
import json
from pathlib import Path
import psutil

root = Path(__file__).resolve().parents[1]
state = root/"local/server.json"
try:
    if state.exists():
        info = json.loads(state.read_text())
        try:
            process = psutil.Process(info["pid"])
            if str(root/"app.py") in process.cmdline():
                for child in process.children(recursive=True):
                    child.terminate()
                process.terminate()
                process.wait(timeout=10)
                state.unlink()
        except psutil.NoSuchProcess:
            state.unlink()
except Exception as exc:
    ctypes.windll.user32.MessageBoxW(0, str(exc), "WingDesignHub 关闭提示", 0x10)
