import json
import os
import re
import subprocess

from config import ASSOC_FILE, SSHD_MOUNT

# Persists which disks the user has manually tagged as USB keys
_USB_SEL_FILE = os.environ.get("USB_SEL_FILE", "/data/usb_selection.conf")

# ── demo devices ─────────────────────────────────────────────────

_DEMO_DEVICES_FULL = [
    {
        "name": "sdc", "size": "32G", "tran": "usb",
        "vendor": "SanDisk", "model": "Ultra USB 3.0",
        "mountpoint": "", "is_sshd": False, "is_usb": True,
        "partitions": [
            {"name": "sdc1", "size": "16G", "mountpoint": "", "fstype": "ntfs"},
            {"name": "sdc2", "size": "14G", "mountpoint": "", "fstype": "ntfs"},
        ],
    },
    {
        "name": "sdd", "size": "32G", "tran": "usb",
        "vendor": "Kingston", "model": "DataTraveler 100 G3",
        "mountpoint": "", "is_sshd": False, "is_usb": True,
        "partitions": [
            {"name": "sdd1", "size": "16G", "mountpoint": "", "fstype": "ntfs"},
            {"name": "sdd2", "size": "14G", "mountpoint": "", "fstype": "ntfs"},
        ],
    },
    {
        "name": "sde", "size": "64G", "tran": "usb",
        "vendor": "Samsung", "model": "FIT Plus",
        "mountpoint": "", "is_sshd": False, "is_usb": True,
        "partitions": [
            {"name": "sde1", "size": "32G", "mountpoint": "", "fstype": "ntfs"},
            {"name": "sde2", "size": "30G", "mountpoint": "", "fstype": "ntfs"},
        ],
    },
]


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


# ── full disk tree (disks + partitions) ───────────────────────────

def get_all_disks_full():
    """
    Return all non-loop block devices with their partitions.
    In DEMO_MODE, returns a fixed set of fake USB drives.
    """
    from config import DEMO_MODE
    if DEMO_MODE:
        return [dict(d) for d in _DEMO_DEVICES_FULL]

    r = _run([
        "lsblk", "-o",
        "NAME,SIZE,TYPE,TRAN,VENDOR,MODEL,MOUNTPOINT,FSTYPE",
        "--json",
    ])
    try:
        raw = json.loads(r.stdout).get("blockdevices", [])
    except Exception:
        raw = []

    usb_sel = load_usb_selection()
    sshd_name = _sshd_base_name() if is_sshd_mounted() else None

    disks = []
    for d in raw:
        if d.get("type") not in ("disk",):
            continue
        name  = d.get("name", "")
        tran  = d.get("tran") or "unknown"
        parts = []
        for ch in d.get("children") or []:
            if ch.get("type") in ("part", "lvm"):
                parts.append({
                    "name":       ch.get("name", ""),
                    "size":       ch.get("size", "?"),
                    "mountpoint": ch.get("mountpoint") or "",
                    "fstype":     ch.get("fstype") or "",
                })
        disks.append({
            "name":       name,
            "size":       d.get("size", "?"),
            "tran":       tran,
            "vendor":     (d.get("vendor") or "").strip(),
            "model":      (d.get("model") or "").strip(),
            "mountpoint": d.get("mountpoint") or "",
            "is_sshd":    name == sshd_name,
            "is_usb":     tran == "usb" or name in usb_sel,
            "partitions": parts,
        })
    return disks


def get_all_disks():
    """Flat list of all disks (no partition detail)."""
    return [
        {k: v for k, v in d.items() if k != "partitions"}
        for d in get_all_disks_full()
    ]


# ── USB key selection (auto + manual override) ────────────────────

def load_usb_selection() -> set:
    """Return set of disk names manually marked as USB keys."""
    sel = set()
    if os.path.exists(_USB_SEL_FILE):
        with open(_USB_SEL_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    sel.add(line)
    return sel


def save_usb_selection(names: list):
    os.makedirs(os.path.dirname(_USB_SEL_FILE) or ".", exist_ok=True)
    with open(_USB_SEL_FILE, "w") as f:
        for n in names:
            f.write(n + "\n")


def get_usb_disks(exclude_sshd=True) -> list:
    """
    Return disks tagged as USB keys (tran==usb OR manually selected),
    optionally excluding the SSHD disk.
    """
    disks = [d for d in get_all_disks_full() if d["is_usb"]]
    if exclude_sshd:
        disks = [d for d in disks if not d["is_sshd"]]
    # Strip partitions before returning
    return [{k: v for k, v in d.items() if k != "partitions"} for d in disks]


# ── SSHD helpers ──────────────────────────────────────────────────

def _sshd_base_name():
    r = _run(["df", SSHD_MOUNT])
    lines = r.stdout.strip().splitlines()
    if len(lines) < 2:
        return None
    dev = lines[-1].split()[0]
    return re.sub(r"\d+$", "", dev.replace("/dev/", ""))


def get_size(path: str) -> int:
    if os.path.isfile(path):
        return os.path.getsize(path)
    r = _run(["blockdev", "--getsize64", path])
    try:
        return int(r.stdout.strip())
    except ValueError:
        return 0


def is_sshd_mounted() -> bool:
    return _run(["mountpoint", "-q", SSHD_MOUNT]).returncode == 0


def is_storage_ready() -> bool:
    """True if storage is accessible — either a local dir or SSHD mounted."""
    from config import STORAGE_LOCAL, IMG_DIR
    if STORAGE_LOCAL:
        return True  # local dir is always accessible
    return is_sshd_mounted()


def mount_sshd(disk: str):
    os.makedirs(SSHD_MOUNT, exist_ok=True)
    for dev in [f"/dev/{disk}1", f"/dev/{disk}"]:
        if _run(["mount", dev, SSHD_MOUNT]).returncode == 0:
            return True, f"Mounted {dev} → {SSHD_MOUNT}"
    return False, "Failed to mount — check disk name and permissions"


def unmount_sshd() -> bool:
    return _run(["umount", SSHD_MOUNT]).returncode == 0


# ── player associations ───────────────────────────────────────────

def load_associations() -> dict:
    assoc = {}
    if not os.path.exists(ASSOC_FILE):
        return assoc
    with open(ASSOC_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                disk, player = line.split("=", 1)
                assoc[disk.strip()] = player.strip()
    return assoc


def save_associations(assoc: dict):
    os.makedirs(os.path.dirname(ASSOC_FILE) or ".", exist_ok=True)
    with open(ASSOC_FILE, "w") as f:
        for disk, player in assoc.items():
            f.write(f"{disk}={player}\n")
