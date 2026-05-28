import os

# ── Fast local SSD (always available) ────────────────────────────
# Master images + active player profiles live here for max speed.
SSD_DIR         = os.environ.get("SSD_DIR",
                  os.environ.get("IMG_DIR", "/data/images"))
SSD_JOUEURS_DIR = os.environ.get("SSD_JOUEURS_DIR",
                  os.environ.get("JOUEURS_DIR", os.path.join(SSD_DIR, "joueurs")))
WIN_IMG         = os.path.join(SSD_DIR, "windows_base.img")
CS2_IMG         = os.path.join(SSD_DIR, "cs2_vierge.img")

# ── SSHD external storage (optional, mount on demand) ────────────
# Permanent archive of all player profiles across tournaments.
SSHD_MOUNT      = os.environ.get("SSHD_MOUNT",      "/mnt/sshd")
SSHD_DIR        = os.environ.get("SSHD_DIR",
                  os.environ.get("IMG_DIR_SSHD",     "/mnt/sshd/images"))
SSHD_JOUEURS_DIR = os.environ.get("SSHD_JOUEURS_DIR",
                   os.path.join(SSHD_DIR, "joueurs"))
HISTORY_FILE    = os.environ.get("HISTORY_FILE",     "/data/historique_tournoi.log")

# ── Misc ─────────────────────────────────────────────────────────
LOG_FILE        = os.environ.get("LOG_FILE",         "/data/usb_manager.log")
ASSOC_FILE      = os.environ.get("ASSOC_FILE",       "/data/usb_associations.conf")

# Backward-compat aliases
IMG_DIR         = SSD_DIR
JOUEURS_DIR     = SSD_JOUEURS_DIR

# Demo mode: fake USB devices + simulated dd, no real disks touched.
DEMO_MODE       = os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes")
