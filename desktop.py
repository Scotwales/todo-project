import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8765/"


def main():
    try:
        import webview
    except ImportError as exc:
        raise SystemExit("PyWebView is required. Install dependencies with: python -m pip install -r requirements.txt") from exc

    env = os.environ.copy()
    env.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    subprocess.run([sys.executable, str(BASE_DIR / "manage.py"), "migrate", "--noinput"], cwd=BASE_DIR, env=env, check=True)
    server = subprocess.Popen(
        [sys.executable, str(BASE_DIR / "manage.py"), "runserver", "127.0.0.1:8765", "--noreload"],
        cwd=BASE_DIR, env=env,
    )
    try:
        for _ in range(100):
            if server.poll() is not None:
                raise RuntimeError("Django server stopped before the desktop window became available.")
            try:
                urllib.request.urlopen(URL, timeout=1).close()
                break
            except (urllib.error.URLError, TimeoutError):
                time.sleep(0.2)
        else:
            raise RuntimeError("Timed out waiting for the local Django server.")
        webview.create_window("Daily", URL, width=1120, height=800, min_size=(760, 560))
        webview.start()
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()


if __name__ == "__main__":
    main()
