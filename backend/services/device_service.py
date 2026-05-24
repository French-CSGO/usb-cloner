import json
import os
import re
import subprocess

from config import ASSOC_FILE, SSHD_MOUNT


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def get_all_disks():
    """Return list of all non-loop block devices with metadata."""
    r = _run(["lsblk", "-d", "-o", "NAME,SIZE,TYPE,TRAN,VENDOR,MODEL", "--json"])
    try:
        data = json.loads(r.stdout)
        devs = []
        for d in data.get("blockdevices", []):
            if d.get("type") == "disk":
                devs.append({
                    "name":   d.get("name", ""),
                    "size":   d.get("size", "?"),
                    "tran":   d.get("tran") or "unknown",
                    "vendor": (d.get("vendor") or "").strip(),
                    "model":  (d.get("model") or "").strip(),
                })
        return devs
    except Exception:
        return []


def _sshd_base_name():
    """Derive the bare disk name that hosts the SSHD mount, e.g. 'sdb'."""
    r = _run(["df", SSHD_MOUNT])
    lines = r.stdout.strip().splitlines()
    if len(lines) < 2:
        return None
    dev = lines[-1].split()[0]  # e.g. /dev/sdb1
    return re.sub(r"\d+$", "", dev.replace("/dev/", ""))


def get_usb_disks(exclude_sshd=True):
    """Return USB disks only, optionally excluding the SSHD disk."""
    disks = [d for d in get_all_disks() if d["tran"] == "usb"]
    if exclude_sshd and is_sshd_mounted():
        sshd_name = _sshd_base_name()
        if sshd_name:
            disks = [d for d in disks if d["name"] != sshd_name]
    return disks


def get_size(path):
    """Return size in bytes for a file or block device."""
    if os.path.isfile(path):
        return os.path.getsize(path)
    r = _run(["blockdev", "--getsize64", path])
    try:
        return int(r.stdout.strip())
    except ValueError:
        return 0


def is_sshd_mounted():
    return _run(["mountpoint", "-q", SSHD_MOUNT]).returncode == 0


def mount_sshd(disk):
    os.makedirs(SSHD_MOUNT, exist_ok=True)
    for dev in [f"/dev/{disk}1", f"/dev/{disk}"]:
        r = _run(["mount", dev, SSHD_MOUNT])
        if r.returncode == 0:
            return True, f"Mounted {dev} → {SSHD_MOUNT}"
    return False, "Failed to mount SSHD — check disk name"


def unmount_sshd():
    return _run(["umount", SSHD_MOUNT]).returncode == 0


def load_associations():
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


def save_associations(assoc):
    os.makedirs(os.path.dirname(ASSOC_FILE), exist_ok=True)
    with open(ASSOC_FILE, "w") as f:
        for disk, player in assoc.items():
            f.write(f"{disk}={player}\n")
