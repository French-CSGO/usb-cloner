import os

SSHD_MOUNT   = os.environ.get("SSHD_MOUNT",   "/mnt/sshd")
IMG_DIR      = os.environ.get("IMG_DIR",       "/mnt/sshd/images")
JOUEURS_DIR  = os.environ.get("JOUEURS_DIR",   "/mnt/sshd/images/joueurs")
WIN_IMG      = os.path.join(IMG_DIR, "windows_base.img")
CS2_IMG      = os.path.join(IMG_DIR, "cs2_vierge.img")
LOG_FILE     = os.environ.get("LOG_FILE",      "/data/usb_manager.log")
HISTORY_FILE = os.environ.get("HISTORY_FILE",  "/data/historique_tournoi.log")
ASSOC_FILE   = os.environ.get("ASSOC_FILE",    "/data/usb_associations.conf")

# True when IMG_DIR is a local path (not under SSHD_MOUNT).
# Can also be forced with STORAGE_LOCAL=1.
STORAGE_LOCAL = (
    os.environ.get("STORAGE_LOCAL", "").lower() in ("1", "true", "yes")
    or not IMG_DIR.startswith(SSHD_MOUNT)
)

# Demo mode: fake USB devices + simulated dd progress, no real disks needed.
DEMO_MODE = os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes")

