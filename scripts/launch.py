"""Double-click entry: starts a loopback-only server and opens a browser."""
import ctypes
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]


def main():
    local = ROOT/"local"; local.mkdir(exist_ok=True)
    import psutil
    state_file = local/"server.json"
    if state_file.exists():
        try:
            previous = json.loads(state_file.read_text())
            process = psutil.Process(previous["pid"])
            if str(ROOT/"app.py") in process.cmdline():
                webbrowser.open(previous["url"])
                return
        except (ValueError, KeyError, OSError, psutil.Error):
            pass
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    python = ROOT/".venv/Scripts/python.exe"
    with (local/"server.log").open("ab") as log:
        child = subprocess.Popen([str(python), "-m", "streamlit", "run", str(ROOT/"app.py"),
            "--server.address=127.0.0.1", f"--server.port={port}", "--server.headless=true",
            "--browser.gatherUsageStats=false"], cwd=ROOT, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(120):
        if child.poll() is not None:
            raise RuntimeError("界面启动失败，请查看 local/server.log")
        try:
            with opener.open(url+"/_stcore/health", timeout=1) as response:
                if response.status == 200:
                    state_file.write_text(json.dumps({"pid": child.pid, "url": url}))
                    webbrowser.open(url)
                    return
        except OSError:
            time.sleep(.25)
    child.terminate()
    raise RuntimeError("启动超时，请查看 local/server.log")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        ctypes.windll.user32.MessageBoxW(0, str(exc), "WingDesignHub 启动提示", 0x10)
