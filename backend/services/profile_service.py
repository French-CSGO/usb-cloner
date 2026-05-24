import os
import shutil
from datetime import datetime

from config import HISTORY_FILE, JOUEURS_DIR


def list_profiles():
    profiles = []
    if not os.path.exists(JOUEURS_DIR):
        return profiles
    for fname in os.listdir(JOUEURS_DIR):
        if fname.endswith(".img"):
            path = os.path.join(JOUEURS_DIR, fname)
            st = os.stat(path)
            profiles.append({
                "name":     fname[:-4],
                "size":     st.st_size,
                "modified": datetime.fromtimestamp(st.st_mtime).isoformat(),
            })
    return sorted(profiles, key=lambda x: x["name"])


def delete_profile(name):
    path = os.path.join(JOUEURS_DIR, f"{name}.img")
    if os.path.exists(path):
        os.remove(path)
        log_history(f"Profile deleted: {name}")
        return True
    return False


def rename_profile(old_name, new_name):
    src = os.path.join(JOUEURS_DIR, f"{old_name}.img")
    dst = os.path.join(JOUEURS_DIR, f"{new_name}.img")
    if os.path.exists(src):
        os.rename(src, dst)
        log_history(f"Profile renamed: {old_name} → {new_name}")
        return True
    return False


def copy_profile(src_name, dst_name):
    src = os.path.join(JOUEURS_DIR, f"{src_name}.img")
    dst = os.path.join(JOUEURS_DIR, f"{dst_name}.img")
    if os.path.exists(src):
        shutil.copy2(src, dst)
        log_history(f"Profile copied: {src_name} → {dst_name}")
        return True
    return False


def log_history(message):
    try:
        dir_ = os.path.dirname(HISTORY_FILE)
        if dir_:
            os.makedirs(dir_, exist_ok=True)
        with open(HISTORY_FILE, "a") as f:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{ts}] {message}\n")
    except OSError:
        pass
