import os
import sys

# Make "backend/" importable as a package root
sys.path.insert(0, os.path.dirname(__file__))

import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template
from flask_cors import CORS
from flask_socketio import SocketIO

from routes.api import api, set_socketio

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE, "frontend", "templates"),
    static_folder=os.path.join(BASE, "frontend", "static"),
)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

app.register_blueprint(api, url_prefix="/api")
set_socketio(socketio)


@app.get("/")
def index():
    return render_template("index.html")


@socketio.on("connect")
def on_connect():
    socketio.emit("connected", {"msg": "USB Manager ready"})


if __name__ == "__main__":
    import config
    os.makedirs("/data", exist_ok=True)
    if config.STORAGE_LOCAL or config.DEMO_MODE:
        os.makedirs(config.JOUEURS_DIR, exist_ok=True)
    if config.DEMO_MODE:
        # Create tiny placeholder images so file-existence checks pass
        for img in [config.WIN_IMG, config.CS2_IMG]:
            if not os.path.exists(img):
                with open(img, "wb") as f:
                    f.write(b"\x00" * 1024)  # 1 KB stub
        print("[DEMO MODE] Fake USB devices active — no real disks will be touched.")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)
