import os

SSHD_MOUNT   = os.environ.get("SSHD_MOUNT",   "/mnt/sshd")
IMG_DIR      = os.environ.get("IMG_DIR",       "/mnt/sshd/images")
JOUEURS_DIR  = os.environ.get("JOUEURS_DIR",   "/mnt/sshd/images/joueurs")
WIN_IMG      = os.path.join(IMG_DIR, "windows_base.img")
CS2_IMG      = os.path.join(IMG_DIR, "cs2_vierge.img")
LOG_FILE     = os.environ.get("LOG_FILE",      "/data/usb_manager.log")
HISTORY_FILE = os.environ.get("HISTORY_FILE",  "/mnt/sshd/historique_tournoi.log")
ASSOC_FILE   = os.environ.get("ASSOC_FILE",    "/data/usb_associations.conf")
