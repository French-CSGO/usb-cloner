import logging
import os
import sys

# Make "backend/" importable as a package root
sys.path.insert(0, os.path.dirname(__file__))

import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request
from flask_cors import CORS
from flask_socketio import SocketIO

from routes.api import api, set_socketio

# ── logging ───────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("usb-manager")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE, "frontend", "templates"),
    static_folder=os.path.join(BASE, "frontend", "static"),
)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet",
                    logger=False, engineio_logger=False)

app.register_blueprint(api, url_prefix="/api")
set_socketio(socketio)


@app.get("/")
def index():
    return render_template("index.html")


@app.after_request
def _log_request(response):
    # Skip static assets to keep logs readable
    if not request.path.startswith("/static"):
        log.info("%s %s → %s", request.method, request.path, response.status_code)
    return response


@app.errorhandler(Exception)
def _handle_error(e):
    log.exception("Unhandled error: %s", e)
    return {"error": str(e)}, 500


@socketio.on("connect")
def on_connect():
    log.info("WebSocket client connected")
    socketio.emit("connected", {"msg": "USB Manager ready"})


@socketio.on("disconnect")
def on_disconnect():
    log.info("WebSocket client disconnected")


if __name__ == "__main__":
    import config
    os.makedirs("/data", exist_ok=True)
    os.makedirs(config.SSD_JOUEURS_DIR, exist_ok=True)
    if config.DEMO_MODE:
        for img in [config.WIN_IMG, config.CS2_IMG]:
            if not os.path.exists(img):
                with open(img, "wb") as f:
                    f.write(b"\x00" * 1024)
        log.info("DEMO MODE — fake USB devices active, no real disks will be touched")

    log.info("SSD_DIR      : %s", config.SSD_DIR)
    log.info("IMG_DIR      : %s", config.IMG_DIR)
    log.info("Starting on  : http://0.0.0.0:5000")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)
