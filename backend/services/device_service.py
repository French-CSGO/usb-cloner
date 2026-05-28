import json
import logging
import os
import re
import subprocess

from config import ASSOC_FILE, SSHD_MOUNT

log = logging.getLogger("usb-manager")

_USB_SEL_FILE = os.environ.get("USB_SEL_FILE", "/data/usb_selection.conf")

# ── demo devices (with fake serials) ─────────────────────────────

_DEMO_DEVICES_FULL = [
    {
        "name": "sdc", "size": "32G", "tran": "usb",
        "vendor": "SanDisk", "model": "Ultra USB 3.0",
        "serial": "4C530001241008111233",
        "mountpoint": "", "is_sshd": False, "is_usb": True,
        "partitions": [
            {"name": "sdc1", "size": "16G", "mountpoint": "", "fstype": "ntfs"},
            {"name": "sdc2", "size": "14G", "mountpoint": "", "fstype": "ntfs"},
        ],
    },
    {
        "name": "sdd", "size": "32G", "tran": "usb",
        "vendor": "Kingston", "model": "DataTraveler 100 G3",
        "serial": "5A37000142080812ABCD",
        "mountpoint": "", "is_sshd": False, "is_usb": True,
        "partitions": [
            {"name": "sdd1", "size": "16G", "mountpoint": "", "fstype": "ntfs"},
            {"name": "sdd2", "size": "14G", "mountpoint": "", "fstype": "ntfs"},
        ],
    },
    {
        "name": "sde", "size": "64G", "tran": "usb",
        "vendor": "Samsung", "model": "FIT Plus",
        "serial": "3B920001450809145678",
        "mountpoint": "", "is_sshd": False, "is_usb": True,
        "partitions": [
            {"name": "sde1", "size": "32G", "mountpoint": "", "fstype": "ntfs"},
            {"name": "sde2", "size": "30G", "mountpoint": "", "fstype": "ntfs"},
        ],
    },
]


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


# ── UID: stable identity per physical key ─────────────────────────

def _make_uid(d: dict) -> str:
    """
    Return a stable identifier for a disk that survives replug.
    Priority: USB serial → vendor+model+size fingerprint → disk name.
    """
    serial = (d.get("serial") or "").strip()
    if serial:
        return serial
    vendor = re.sub(r"\s+", "_", (d.get("vendor") or "").strip())
    model  = re.sub(r"\s+", "_", (d.get("model")  or "").strip())
    size   = d.get("size", "?")
    if vendor or model:
        return f"NOSERIAL_{vendor}_{model}_{size}"
    return d.get("name", "unknown")


def _is_legacy_key(uid: str) -> bool:
    """True if uid looks like an old disk-name entry (sdc, sdd…)."""
    return bool(re.match(r"^sd[a-z]+$", uid))


# ── full disk tree ────────────────────────────────────────────────

def get_all_disks_full() -> list:
    """
    All non-loop block devices with partitions + serial + uid.
    In DEMO_MODE returns fake drives.
    """
    from config import DEMO_MODE
    if DEMO_MODE:
        devs = [dict(d) for d in _DEMO_DEVICES_FULL]
        for d in devs:
            d["uid"] = _make_uid(d)
        return devs

    # Try with SERIAL column; fall back silently if lsblk is older
    for cols in (
        "NAME,SIZE,TYPE,TRAN,VENDOR,MODEL,MOUNTPOINT,FSTYPE,SERIAL",
        "NAME,SIZE,TYPE,TRAN,VENDOR,MODEL,MOUNTPOINT,FSTYPE",
    ):
        r = _run(["lsblk", "-o", cols, "--json"])
        if r.returncode == 0:
            break
    else:
        return []

    try:
        raw = json.loads(r.stdout).get("blockdevices", [])
    except Exception:
        return []

    usb_sel   = load_usb_selection()
    sshd_name = _sshd_base_name() if is_sshd_mounted() else None

    disks = []
    for d in raw:
        if d.get("type") != "disk":
            continue
        name   = d.get("name", "")
        tran   = d.get("tran") or "unknown"
        serial = (d.get("serial") or "").strip()
        parts  = [
            {
                "name":       ch.get("name", ""),
                "size":       ch.get("size", "?"),
                "mountpoint": ch.get("mountpoint") or "",
                "fstype":     ch.get("fstype") or "",
            }
            for ch in (d.get("children") or [])
            if ch.get("type") in ("part", "lvm")
        ]
        entry = {
            "name":       name,
            "size":       d.get("size", "?"),
            "tran":       tran,
            "vendor":     (d.get("vendor") or "").strip(),
            "model":      (d.get("model")  or "").strip(),
            "serial":     serial,
            "mountpoint": d.get("mountpoint") or "",
            "is_sshd":    name == sshd_name,
            "is_usb":     tran == "usb" or name in usb_sel,
            "partitions": parts,
        }
        entry["uid"] = _make_uid(entry)
        disks.append(entry)
    return disks


def get_all_disks() -> list:
    return [{k: v for k, v in d.items() if k != "partitions"}
            for d in get_all_disks_full()]


# ── USB key selection ─────────────────────────────────────────────

def load_usb_selection() -> set:
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
    disks = [d for d in get_all_disks_full() if d["is_usb"]]
    if exclude_sshd:
        disks = [d for d in disks if not d["is_sshd"]]
    return [{k: v for k, v in d.items() if k != "partitions"} for d in disks]


# ── association helpers ───────────────────────────────────────────

def uid_to_name_map() -> dict:
    """Return {uid: current_dev_name} for all currently connected disks."""
    return {d["uid"]: d["name"] for d in get_all_disks_full()}


def resolve_to_devices(assoc: dict) -> dict:
    """
    Map {uid: player} → {dev_name: player} using currently connected disks.
    Also handles legacy {disk_name: player} entries transparently.
    """
    u2n    = uid_to_name_map()
    result = {}
    for uid, player in assoc.items():
        if _is_legacy_key(uid):
            # Old format: disk name directly
            result[uid] = player
        elif uid in u2n:
            result[u2n[uid]] = player
        else:
            log.warning("UID %s not found in current disks (key not connected?)", uid)
    return result


# ── SSHD ──────────────────────────────────────────────────────────

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
    return True


def mount_sshd(disk: str):
    os.makedirs(SSHD_MOUNT, exist_ok=True)
    for dev in [f"/dev/{disk}1", f"/dev/{disk}"]:
        if _run(["mount", dev, SSHD_MOUNT]).returncode == 0:
            return True, f"Mounted {dev} → {SSHD_MOUNT}"
    return False, "Failed to mount — check disk name and permissions"


def unmount_sshd() -> bool:
    return _run(["umount", SSHD_MOUNT]).returncode == 0


# ── player associations (uid-keyed) ──────────────────────────────

def load_associations() -> dict:
    """Return {uid: player}. Handles legacy disk-name format transparently."""
    assoc = {}
    if not os.path.exists(ASSOC_FILE):
        return assoc
    with open(ASSOC_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                uid, player = line.split("=", 1)
                assoc[uid.strip()] = player.strip()
    return assoc


def save_associations(assoc: dict):
    os.makedirs(os.path.dirname(ASSOC_FILE) or ".", exist_ok=True)
    with open(ASSOC_FILE, "w") as f:
        for uid, player in assoc.items():
            f.write(f"{uid}={player}\n")
