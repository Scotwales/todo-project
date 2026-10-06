import logging
import os
import sys
import threading
import time
from socketserver import ThreadingMixIn
from urllib.error import URLError
from urllib.request import urlopen
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.conf import settings
from django.core.wsgi import get_wsgi_application
from config.startup import run_startup_migrations
from tasks.planning import stop_active_timers
from tasks.scheduler import scheduler, start_scheduler

HOST = "127.0.0.1"
WINDOW_TITLE = "Daily"


class ThreadingLocalServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class LocalRequestHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        logging.getLogger("daily.http").info(format, *args)


def _show_startup_error(error):
    message = f"Daily could not start.\n\n{error}"
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, WINDOW_TITLE, 0x10)
    else:
        print(message, file=sys.stderr)


def main():
    logging.basicConfig(
        filename=settings.LOG_DIR / "daily.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    server = None
    server_thread = None
    try:
        run_startup_migrations(
            settings.DATA_DIR,
            settings.BACKUP_DIR,
            settings.LEGACY_DATA_DIR,
        )
        stop_active_timers()
        start_scheduler()
        if not scheduler.running:
            raise RuntimeError("The reminder and recurring-task scheduler did not start.")

        server = make_server(
            HOST,
            0,
            get_wsgi_application(),
            server_class=ThreadingLocalServer,
            handler_class=LocalRequestHandler,
        )
        address, port = server.server_address
        url = f"http://{address}:{port}/"
        server_thread = threading.Thread(target=server.serve_forever, name="daily-django", daemon=True)
        server_thread.start()
        for _ in range(100):
            if not server_thread.is_alive():
                raise RuntimeError("The local Django server stopped during startup.")
            try:
                with urlopen(url, timeout=1):
                    break
            except (URLError, TimeoutError):
                time.sleep(0.1)
        else:
            raise RuntimeError("Timed out while starting the local Django server.")

        import webview

        webview.create_window(WINDOW_TITLE, url, width=1360, height=900, min_size=(800, 620))
        webview.start(
            private_mode=False,
            storage_path=str(settings.WEBVIEW_DIR),
        )
    except Exception as error:
        logging.exception("Daily desktop application failed to start")
        _show_startup_error(error)
        raise
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if server_thread is not None:
            server_thread.join(timeout=5)
        if scheduler.running:
            scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
