import logging
import os
import shutil
import time
from datetime import datetime

from config import HISTORY_FILE, PROFILES_DIR, SSD_JOUEURS_DIR, SSHD_JOUEURS_DIR

log = logging.getLogger("usb-manager")


# ── internal helpers ──────────────────────────────────────────────

def _dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for fname in files:
            try:
                total += os.path.getsize(os.path.join(root, fname))
            except OSError:
                pass
    return total


def _info_img(path: str) -> dict:
    st = os.stat(path)
    return {
        "name":     os.path.basename(path)[:-4],
        "type":     "img",
        "size":     st.st_size,
        "modified": datetime.fromtimestamp(st.st_mtime).isoformat(),
    }


def _info_dir(path: str) -> dict:
    st = os.stat(path)
    return {
        "name":     os.path.basename(path),
        "type":     "dir",
        "size":     _dir_size(path),
        "modified": datetime.fromtimestamp(st.st_mtime).isoformat(),
    }


def _list_dir(directory: str) -> list:
    if not os.path.isdir(directory):
        return []
    result = []
    for fname in sorted(os.listdir(directory)):
        full = os.path.join(directory, fname)
        try:
            if fname.endswith(".img") and os.path.isfile(full):
                result.append(_info_img(full))
            elif os.path.isdir(full) and not fname.startswith("."):
                result.append(_info_dir(full))
        except OSError:
            pass
    return result


# ── profile lists ─────────────────────────────────────────────────

def list_profiles() -> list:
    return list_profiles_ssd()


def list_profiles_ssd() -> list:
    return _list_dir(SSD_JOUEURS_DIR)


def list_profiles_sshd() -> list:
    return _list_dir(SSHD_JOUEURS_DIR)


def list_profiles_combined() -> list:
    """Merge SSD + SSHD into one list with presence flags."""
    ssd  = {p["name"]: p for p in list_profiles_ssd()}
    sshd = {p["name"]: p for p in list_profiles_sshd()}
    names = sorted(set(ssd) | set(sshd))
    result = []
    for name in names:
        entry = {"name": name, "on_ssd": name in ssd, "on_sshd": name in sshd}
        if name in ssd:
            entry["ssd_size"]  = ssd[name]["size"]
            entry["ssd_mtime"] = ssd[name]["modified"]
            entry["ssd_type"]  = ssd[name]["type"]
        if name in sshd:
            entry["sshd_size"]  = sshd[name]["size"]
            entry["sshd_mtime"] = sshd[name]["modified"]
            entry["sshd_type"]  = sshd[name]["type"]
        result.append(entry)
    return result


# ── directory-profile helpers (rsync-based, stored on SSHD) ──────

def profile_dir(player: str) -> str:
    return os.path.join(PROFILES_DIR, player)


def profile_exists(player: str) -> bool:
    return os.path.isdir(profile_dir(player))


# ── file copy with WebSocket progress (legacy .img sync) ─────────

def _copy_with_progress(src: str, dst: str,
                         job_id: str, task_id: str, label: str,
                         socketio) -> bool:
    # Import here to avoid circular import at module load time
    import services.dd_service as _dd

    try:
        total  = os.path.getsize(src)
        chunk  = 4 * 1024 * 1024   # 4 MB
        done   = 0
        start  = time.time()
        os.makedirs(os.path.dirname(dst), exist_ok=True)

        with _dd._lock:
            _dd.jobs[job_id]["tasks"][task_id].update({
                "status": "running", "label": label, "total_bytes": total,
            })

        with open(src, "rb") as f_in, open(dst, "wb") as f_out:
            while True:
                buf = f_in.read(chunk)
                if not buf:
                    break
                f_out.write(buf)
                done    += len(buf)
                elapsed  = time.time() - start
                pct      = min(99, int(done / total * 100)) if total else 0
                speed    = (f"{done / elapsed / 1024 / 1024:.0f} MB/s"
                            if elapsed > 0.2 else "—")
                eta      = (int((total - done) / (done / elapsed))
                            if done > 0 and elapsed > 0.2 else None)
                data = {
                    "job_id": job_id, "task_id": task_id, "label": label,
                    "bytes_done": done, "total_bytes": total,
                    "percent": pct, "speed": speed,
                    "elapsed": round(elapsed, 1), "eta": eta, "status": "running",
                }
                with _dd._lock:
                    _dd.jobs[job_id]["tasks"][task_id].update(data)
                socketio.emit("progress", data)

        with _dd._lock:
            _dd.jobs[job_id]["tasks"][task_id].update({"status": "done", "percent": 100})
        socketio.emit("progress", {
            "job_id": job_id, "task_id": task_id, "label": label,
            "percent": 100, "status": "done",
        })
        return True

    except Exception as e:
        log.exception("Copy error %s → %s: %s", src, dst, e)
        import services.dd_service as _dd
        with _dd._lock:
            _dd.jobs[job_id]["tasks"][task_id].update({"status": "error"})
        socketio.emit("progress", {
            "job_id": job_id, "task_id": task_id, "label": label,
            "percent": 0, "status": "error",
        })
        return False


# ── sync: SSHD ↔ SSD (legacy .img profiles only) ─────────────────

def sync_pull(names: list, job_id: str, socketio) -> dict:
    """Copy legacy .img profiles SSHD → SSD (pull into fast local cache)."""
    os.makedirs(SSD_JOUEURS_DIR, exist_ok=True)
    results = {}
    for name in names:
        src = os.path.join(SSHD_JOUEURS_DIR, f"{name}.img")
        dst = os.path.join(SSD_JOUEURS_DIR,  f"{name}.img")
        tid = f"pull:{name}"
        ok  = _copy_with_progress(src, dst, job_id, tid,
                                   f"↓ SSHD→SSD  {name}", socketio)
        results[tid] = ok
        if ok:
            log.info("Pulled %s: SSHD → SSD", name)
            log_history(f"Pulled {name}: SSHD → SSD")
    return results


def sync_push(names: list, job_id: str, socketio) -> dict:
    """Copy legacy .img profiles SSD → SSHD (push to permanent archive)."""
    os.makedirs(SSHD_JOUEURS_DIR, exist_ok=True)
    results = {}
    for name in names:
        src = os.path.join(SSD_JOUEURS_DIR,  f"{name}.img")
        dst = os.path.join(SSHD_JOUEURS_DIR, f"{name}.img")
        tid = f"push:{name}"
        ok  = _copy_with_progress(src, dst, job_id, tid,
                                   f"↑ SSD→SSHD  {name}", socketio)
        results[tid] = ok
        if ok:
            log.info("Pushed %s: SSD → SSHD", name)
            log_history(f"Pushed {name}: SSD → SSHD")
    return results


# ── profile CRUD (dir-based on SSHD, legacy .img on SSD/SSHD) ────

def _profile_paths(name: str, storage: str) -> list:
    """Return existing (path, type) candidates for a profile under given storage."""
    dirs = []
    if storage in ("ssd",  "both"): dirs.append(SSD_JOUEURS_DIR)
    if storage in ("sshd", "both"): dirs.append(SSHD_JOUEURS_DIR)
    found = []
    for d in dirs:
        dir_path = os.path.join(d, name)
        img_path = os.path.join(d, f"{name}.img")
        if os.path.isdir(dir_path):
            found.append((dir_path, "dir"))
        elif os.path.isfile(img_path):
            found.append((img_path, "img"))
    return found


def delete_profile(name: str, storage: str = "sshd") -> bool:
    deleted = False
    for path, ptype in _profile_paths(name, storage):
        if ptype == "dir":
            shutil.rmtree(path)
        else:
            os.remove(path)
        deleted = True
    if deleted:
        log_history(f"Profile deleted: {name} ({storage})")
    return deleted


def rename_profile(old_name: str, new_name: str) -> bool:
    renamed = False
    for d in (SSHD_JOUEURS_DIR, SSD_JOUEURS_DIR):
        src_dir = os.path.join(d, old_name)
        src_img = os.path.join(d, f"{old_name}.img")
        if os.path.isdir(src_dir):
            os.rename(src_dir, os.path.join(d, new_name))
            renamed = True
        elif os.path.isfile(src_img):
            os.rename(src_img, os.path.join(d, f"{new_name}.img"))
            renamed = True
    if renamed:
        log_history(f"Profile renamed: {old_name} → {new_name}")
    return renamed


def copy_profile(src_name: str, dst_name: str) -> bool:
    copied = False
    for d in (SSHD_JOUEURS_DIR, SSD_JOUEURS_DIR):
        src_dir = os.path.join(d, src_name)
        src_img = os.path.join(d, f"{src_name}.img")
        if os.path.isdir(src_dir):
            shutil.copytree(src_dir, os.path.join(d, dst_name))
            copied = True
        elif os.path.isfile(src_img):
            shutil.copy2(src_img, os.path.join(d, f"{dst_name}.img"))
            copied = True
    if copied:
        log_history(f"Profile copied: {src_name} → {dst_name}")
    return copied


def log_history(message: str):
    try:
        d = os.path.dirname(HISTORY_FILE)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(HISTORY_FILE, "a") as f:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{ts}] {message}\n")
    except OSError:
        pass
