import os
import threading

from flask import Blueprint, jsonify, request

import config as _cfg
from config import CS2_IMG, HISTORY_FILE, IMG_DIR, SSD_DIR, WIN_IMG
from services import dd_service, device_service, profile_service, rsync_service, team_service

api = Blueprint("api", __name__)
_sio = None  # injected by app.py


def set_socketio(sio):
    global _sio
    _sio = sio


# ── utility ───────────────────────────────────────────────────────

def _ok(data=None, **kw):
    return jsonify({"success": True, **(data or {}), **kw})


def _err(msg, code=400):
    return jsonify({"success": False, "error": msg}), code


def _bg(fn, *args):
    threading.Thread(target=fn, args=args, daemon=True).start()


# ── storage ───────────────────────────────────────────────────────

@api.get("/storage/info")
def storage_info():
    sshd_mounted = device_service.is_sshd_mounted()
    os.makedirs(_cfg.SSD_JOUEURS_DIR, exist_ok=True)
    return jsonify({
        "ssd":  {"path": _cfg.SSD_DIR,  "ready": True},
        "sshd": {"path": _cfg.SSHD_DIR, "mounted": sshd_mounted},
        # legacy fields kept for backward compat
        "mode": "dual", "mounted": sshd_mounted,
        "ready": True, "path": _cfg.SSD_DIR,
    })


@api.get("/mount/status")
def mount_status():
    return storage_info()


@api.post("/mount")
def mount():
    disk = (request.json or {}).get("disk", "")
    if not disk:
        return _err("disk required")
    ok, msg = device_service.mount_sshd(disk)
    if ok:
        os.makedirs(_cfg.SSHD_JOUEURS_DIR, exist_ok=True)
    return (jsonify({"success": ok, "message": msg}),
            200 if ok else 500)


@api.delete("/mount")
def unmount():
    ok = device_service.unmount_sshd()
    return jsonify({"success": ok})


# ── devices ───────────────────────────────────────────────────────

@api.get("/devices")
def list_devices():
    """USB keys only (auto-detected or manually selected), enriched with player."""
    assoc = device_service.load_associations()
    disks = device_service.get_usb_disks()
    for d in disks:
        d["player"] = assoc.get(d["uid"]) or assoc.get(d["name"])
    return jsonify(disks)


@api.get("/disks")
def list_all_disks():
    """ALL block devices with partitions — used for the disk browser."""
    assoc  = device_service.load_associations()
    disks  = device_service.get_all_disks_full()
    for d in disks:
        d["player"] = assoc.get(d["uid"]) or assoc.get(d["name"])
    return jsonify(disks)


@api.post("/devices/select")
def select_usb_disks():
    """Manually mark which disks are USB keys (overrides auto-detect)."""
    names = (request.json or {}).get("names", [])
    device_service.save_usb_selection(names)
    return _ok(selected=names)


# ── images ────────────────────────────────────────────────────────

@api.get("/images")
def list_images():
    imgs = []
    for path in [WIN_IMG, CS2_IMG]:
        if os.path.exists(path):
            st = os.stat(path)
            imgs.append({"name": os.path.basename(path),
                         "path": path, "size": st.st_size})
    return jsonify(imgs)


# ── profiles ─────────────────────────────────────────────────────

@api.get("/profiles")
def list_profiles():
    return jsonify(profile_service.list_profiles_ssd())


@api.get("/profiles/ssd")
def list_profiles_ssd():
    return jsonify(profile_service.list_profiles_ssd())


@api.get("/profiles/sshd")
def list_profiles_sshd():
    return jsonify(profile_service.list_profiles_sshd())


@api.get("/profiles/combined")
def list_profiles_combined():
    return jsonify(profile_service.list_profiles_combined())


@api.delete("/profiles/<name>")
def delete_profile(name):
    storage = request.args.get("storage", "sshd")
    ok = profile_service.delete_profile(name, storage)
    return _ok() if ok else _err(f"Profile '{name}' not found", 404)


@api.post("/profiles/rename")
def rename_profile():
    d = request.json or {}
    ok = profile_service.rename_profile(d.get("old_name", ""),
                                        d.get("new_name", ""))
    return _ok() if ok else _err("Source profile not found", 404)


@api.post("/profiles/copy")
def copy_profile():
    d = request.json or {}
    ok = profile_service.copy_profile(d.get("src", ""), d.get("dst", ""))
    return _ok() if ok else _err("Source profile not found", 404)


# ── sync ──────────────────────────────────────────────────────────

@api.post("/sync/pull")
def sync_pull():
    """Pull profiles SSHD → SSD."""
    d     = request.json or {}
    team  = d.get("team") or ""
    names = d.get("names") or [p["name"] for p in profile_service.list_profiles_sshd()]
    if team:
        team_players = set(team_service.get_team_players(team))
        names = [n for n in names if n in team_players]
    if not names:
        return _err("No profiles on SSHD to pull" if not team
                    else f"No SSHD profiles for team '{team}'")
    if not device_service.is_sshd_mounted():
        return _err("SSHD not mounted")

    job_id = dd_service.create_job("sync_pull", [f"pull:{n}" for n in names])

    def _run():
        results = profile_service.sync_pull(names, job_id, _sio)
        ok  = sum(1 for v in results.values() if v)
        err = len(results) - ok
        dd_service.jobs[job_id]["status"] = "done"
        _sio.emit("job_complete", {"job_id": job_id, "ok": ok, "errors": err})

    _bg(_run)
    return _ok(job_id=job_id)


@api.post("/sync/push")
def sync_push():
    """Push profiles SSD → SSHD."""
    d     = request.json or {}
    team  = d.get("team") or ""
    names = d.get("names") or [p["name"] for p in profile_service.list_profiles_ssd()]
    if team:
        team_players = set(team_service.get_team_players(team))
        names = [n for n in names if n in team_players]
    if not names:
        return _err("No profiles on SSD to push" if not team
                    else f"No SSD profiles for team '{team}'")
    if not device_service.is_sshd_mounted():
        return _err("SSHD not mounted")

    job_id = dd_service.create_job("sync_push", [f"push:{n}" for n in names])

    def _run():
        results = profile_service.sync_push(names, job_id, _sio)
        ok  = sum(1 for v in results.values() if v)
        err = len(results) - ok
        dd_service.jobs[job_id]["status"] = "done"
        _sio.emit("job_complete", {"job_id": job_id, "ok": ok, "errors": err})

    _bg(_run)
    return _ok(job_id=job_id)


# ── teams ─────────────────────────────────────────────────────────

@api.get("/teams")
def list_teams():
    teams = team_service.load_teams()
    return jsonify([{"name": n, "players": p} for n, p in teams.items()])


@api.post("/teams")
def create_team():
    d = request.json or {}
    name = d.get("name", "").strip()
    if not name:
        return _err("name required")
    teams = team_service.load_teams()
    if name in teams:
        return _err(f"Team '{name}' already exists")
    teams[name] = [p.strip() for p in d.get("players", []) if p.strip()]
    team_service.save_teams(teams)
    return _ok()


@api.put("/teams/<name>")
def update_team(name):
    d = request.json or {}
    teams = team_service.load_teams()
    if name not in teams:
        return _err("Team not found", 404)
    new_name = d.get("name", name).strip() or name
    players  = [p.strip() for p in d.get("players", []) if p.strip()]
    if new_name != name:
        del teams[name]
    teams[new_name] = players
    team_service.save_teams(teams)
    return _ok()


@api.delete("/teams/<name>")
def delete_team(name):
    teams = team_service.load_teams()
    if name not in teams:
        return _err("Team not found", 404)
    del teams[name]
    team_service.save_teams(teams)
    return _ok()


# ── assignments ───────────────────────────────────────────────────

@api.get("/assignments")
def get_assignments():
    return jsonify(device_service.load_associations())


@api.post("/assignments")
def set_assignments():
    device_service.save_associations(request.json or {})
    return _ok()


# ── history ───────────────────────────────────────────────────────

@api.get("/history")
def get_history():
    lines = []
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE) as f:
            lines = [l.rstrip() for l in f.readlines()[-60:]]
    return jsonify(lines)


# ── jobs ─────────────────────────────────────────────────────────

@api.get("/jobs")
def get_jobs():
    return jsonify(list(dd_service.jobs.values()))


@api.get("/jobs/<job_id>")
def get_job(job_id):
    job = dd_service.jobs.get(job_id)
    return jsonify(job) if job else _err("not found", 404)


@api.delete("/jobs/<job_id>/tasks/<task_id>")
def cancel_task(job_id, task_id):
    ok = dd_service.cancel_task(job_id, task_id)
    if ok:
        _sio.emit("progress", {
            "job_id": job_id, "task_id": task_id,
            "status": "cancelled", "percent":
                dd_service.jobs[job_id]["tasks"][task_id].get("percent", 0),
        })
    return _ok() if ok else _err("task not found or already finished", 404)


# ── operations ────────────────────────────────────────────────────

@api.post("/operations/create-master")
def create_master():
    d = request.json or {}
    disk    = d.get("disk", "")
    p_win   = d.get("partition_win", "1")
    p_cs2   = d.get("partition_cs2", "2")
    if not disk:
        return _err("disk required")

    src_win  = f"/dev/{disk}{p_win}"
    src_cs2  = f"/dev/{disk}{p_cs2}"
    os.makedirs(IMG_DIR, exist_ok=True)

    tasks = {
        "windows": (src_win, WIN_IMG,  dd_service.get_size(src_win), "Windows → master"),
        "cs2":     (src_cs2, CS2_IMG, dd_service.get_size(src_cs2), "CS2 → master"),
    }
    job_id = dd_service.create_job("create_master", list(tasks))

    def _run():
        dd_service.run_parallel(job_id, tasks, _sio)
        profile_service.log_history(f"Master images created from /dev/{disk}")

    _bg(_run)
    return _ok(job_id=job_id)


@api.post("/operations/deploy")
def deploy():
    d = request.json or {}
    p_win = d.get("partition_win", "1")
    p_cs2 = d.get("partition_cs2", "2")
    team  = d.get("team") or ""

    if not os.path.exists(WIN_IMG) or not os.path.exists(CS2_IMG):
        return _err("Master images not found — run Create Master first")

    disks = device_service.get_usb_disks()
    if not disks:
        return _err("No USB keys detected")

    if team:
        team_players  = set(team_service.get_team_players(team))
        assoc         = device_service.load_associations()
        dev_assoc     = device_service.resolve_to_devices(assoc)
        team_disks    = {disk for disk, player in dev_assoc.items() if player in team_players}
        disks = [d for d in disks if d["name"] in team_disks]
        if not disks:
            return _err(f"No keys assigned to team '{team}'")

    win_sz  = dd_service.get_size(WIN_IMG)
    cs2_sz  = dd_service.get_size(CS2_IMG)
    tasks   = {}
    for disk in disks:
        n = disk["name"]
        tasks[f"{n}p{p_win}"] = (WIN_IMG, f"/dev/{n}{p_win}", win_sz,
                                  f"{n}p{p_win} ← Windows")
        tasks[f"{n}p{p_cs2}"] = (CS2_IMG, f"/dev/{n}{p_cs2}", cs2_sz,
                                  f"{n}p{p_cs2} ← CS2 blank")

    job_id = dd_service.create_job("deploy", list(tasks))

    def _run():
        dd_service.run_parallel(job_id, tasks, _sio)
        profile_service.log_history(f"Deploy completed: {len(disks)} keys")

    _bg(_run)
    return _ok(job_id=job_id)


def _save_worker(tid, disk, player, p_cs2, job_id):
    """Mount CS2 partition read-only, rsync it into the player's SSHD profile."""
    if tid in dd_service._cancelled:
        dd_service._cancelled.discard(tid)
        return False

    label = f"{disk} → {player}"
    ok, mnt = device_service.mount_partition(disk, p_cs2, rw=False)
    if not ok:
        with dd_service._lock:
            dd_service.jobs[job_id]["tasks"][tid].update({"status": "error", "label": label})
        _sio.emit("progress", {"job_id": job_id, "task_id": tid, "label": label,
                                "percent": 0, "status": "error"})
        return False

    try:
        return rsync_service.run_rsync(
            mnt, profile_service.profile_dir(player),
            job_id, tid, label, _sio, delete=True)
    finally:
        device_service.unmount_partition(mnt)


@api.post("/operations/save")
def save_players():
    d     = request.json or {}
    p_cs2 = d.get("partition_cs2", "2")
    team  = d.get("team") or ""
    assoc = device_service.load_associations()

    if not assoc:
        return _err("No assignments — use Assign Players first")

    dev_assoc = device_service.resolve_to_devices(assoc)
    if not dev_assoc:
        return _err("No connected keys match current assignments")

    if team:
        team_players = set(team_service.get_team_players(team))
        dev_assoc = {disk: player for disk, player in dev_assoc.items()
                     if player in team_players}
        if not dev_assoc:
            return _err(f"No keys assigned to team '{team}'")

    if not device_service.is_sshd_mounted():
        return _err("SSHD not mounted — player profiles are stored on the SSHD")

    os.makedirs(_cfg.PROFILES_DIR, exist_ok=True)
    tasks = {f"{disk}:{player}": (disk, player, p_cs2)
             for disk, player in dev_assoc.items()}
    job_id = dd_service.create_job("save", list(tasks))

    def _run():
        rsync_service.run_parallel(
            job_id, tasks, _sio,
            lambda tid, disk, player, p_cs2: _save_worker(tid, disk, player, p_cs2, job_id))
        profile_service.log_history(f"Save: {len(dev_assoc)} players")

    _bg(_run)
    return _ok(job_id=job_id)


def _load_worker(tid, disk, player, p_cs2, job_id):
    """Mount CS2 partition, rsync the player's SSHD profile onto it (mirror)."""
    if tid in dd_service._cancelled:
        dd_service._cancelled.discard(tid)
        return False

    label = f"{player} → {disk}"
    ok, mnt = device_service.mount_partition(disk, p_cs2, rw=True)
    if not ok:
        with dd_service._lock:
            dd_service.jobs[job_id]["tasks"][tid].update({"status": "error", "label": label})
        _sio.emit("progress", {"job_id": job_id, "task_id": tid, "label": label,
                                "percent": 0, "status": "error"})
        return False

    try:
        if profile_service.profile_exists(player):
            return rsync_service.run_rsync(
                profile_service.profile_dir(player), mnt,
                job_id, tid, label, _sio, delete=True)
        label = f"{label} (no profile, kept as-is)"
        with dd_service._lock:
            dd_service.jobs[job_id]["tasks"][tid].update({
                "status": "done", "percent": 100, "label": label,
            })
        _sio.emit("progress", {"job_id": job_id, "task_id": tid, "label": label,
                                "percent": 100, "status": "done"})
        return True
    finally:
        device_service.unmount_partition(mnt)


@api.post("/operations/load")
def load_players():
    d     = request.json or {}
    p_cs2 = d.get("partition_cs2", "2")
    team  = d.get("team") or ""
    assoc = device_service.load_associations()

    if not assoc:
        return _err("No assignments")

    dev_assoc = device_service.resolve_to_devices(assoc)
    if not dev_assoc:
        return _err("No connected keys match current assignments")

    if team:
        team_players = set(team_service.get_team_players(team))
        dev_assoc = {disk: player for disk, player in dev_assoc.items()
                     if player in team_players}
        if not dev_assoc:
            return _err(f"No keys assigned to team '{team}'")

    if not device_service.is_sshd_mounted():
        return _err("SSHD not mounted — player profiles are stored on the SSHD")

    tasks = {f"{disk}:{player}": (disk, player, p_cs2)
             for disk, player in dev_assoc.items()}
    job_id = dd_service.create_job("load", list(tasks))

    def _run():
        rsync_service.run_parallel(
            job_id, tasks, _sio,
            lambda tid, disk, player, p_cs2: _load_worker(tid, disk, player, p_cs2, job_id))
        profile_service.log_history(f"Load: {len(dev_assoc)} players")

    _bg(_run)
    return _ok(job_id=job_id)


@api.post("/operations/reset")
def reset_cs2():
    d     = request.json or {}
    p_cs2 = d.get("partition_cs2", "2")

    if not os.path.exists(CS2_IMG):
        return _err("CS2 blank image not found")

    disks  = device_service.get_usb_disks()
    cs2_sz = dd_service.get_size(CS2_IMG)
    tasks  = {
        n["name"]: (CS2_IMG, f"/dev/{n['name']}{p_cs2}", cs2_sz,
                    f"blank → {n['name']}p{p_cs2}")
        for n in disks
    }
    job_id = dd_service.create_job("reset", list(tasks))

    def _run():
        dd_service.run_parallel(job_id, tasks, _sio)
        device_service.save_associations({})
        profile_service.log_history(f"Reset CS2 blank on {len(disks)} keys")

    _bg(_run)
    return _ok(job_id=job_id)


@api.post("/operations/change-player")
def change_player():
    d          = request.json or {}
    disk       = d.get("disk", "")
    p_cs2      = d.get("partition_cs2", "2")
    new_player = d.get("new_player", "")
    save_old   = d.get("save_old", True)

    if not disk or not new_player:
        return _err("disk and new_player required")

    if not device_service.is_sshd_mounted():
        return _err("SSHD not mounted — player profiles are stored on the SSHD")

    assoc      = device_service.load_associations()
    # Resolve device name → uid for stable storage
    name_to_uid = {v: k for k, v in device_service.uid_to_name_map().items()}
    uid        = name_to_uid.get(disk, disk)
    old_player = assoc.get(uid) or assoc.get(disk)
    tasks      = {}

    if old_player and save_old:
        tasks[f"save:{old_player}"] = f"Save {old_player}"

    tasks[f"load:{new_player}"] = f"Load {new_player}"

    job_id = dd_service.create_job("change_player", list(tasks))

    def _run():
        ok, mnt = device_service.mount_partition(disk, p_cs2, rw=True)
        if not ok:
            with dd_service._lock:
                for tid, label in tasks.items():
                    dd_service.jobs[job_id]["tasks"][tid].update({"status": "error", "label": label})
                    _sio.emit("progress", {"job_id": job_id, "task_id": tid, "label": label,
                                            "percent": 0, "status": "error"})
                dd_service.jobs[job_id]["status"] = "done"
                dd_service.jobs[job_id]["result"] = {"ok": 0, "errors": len(tasks)}
            _sio.emit("job_complete", {"job_id": job_id, "ok": 0, "errors": len(tasks)})
            return

        try:
            if old_player and save_old:
                tid = f"save:{old_player}"
                if tid not in dd_service._cancelled:
                    rsync_service.run_rsync(
                        mnt, profile_service.profile_dir(old_player),
                        job_id, tid, tasks[tid], _sio, delete=True)
                else:
                    dd_service._cancelled.discard(tid)

            tid   = f"load:{new_player}"
            label = tasks[tid]
            if tid in dd_service._cancelled:
                dd_service._cancelled.discard(tid)
            elif profile_service.profile_exists(new_player):
                rsync_service.run_rsync(
                    profile_service.profile_dir(new_player), mnt,
                    job_id, tid, label, _sio, delete=True)
            else:
                label = f"{label} (no profile, kept as-is)"
                with dd_service._lock:
                    dd_service.jobs[job_id]["tasks"][tid].update({
                        "status": "done", "percent": 100, "label": label,
                    })
                _sio.emit("progress", {"job_id": job_id, "task_id": tid, "label": label,
                                        "percent": 100, "status": "done"})
        finally:
            device_service.unmount_partition(mnt)

        results   = {tid: dd_service.jobs[job_id]["tasks"][tid].get("status") == "done"
                      for tid in tasks}
        ok_count  = sum(1 for v in results.values() if v)
        err_count = len(results) - ok_count
        with dd_service._lock:
            dd_service.jobs[job_id]["status"] = "done"
            dd_service.jobs[job_id]["result"] = {"ok": ok_count, "errors": err_count}
        _sio.emit("job_complete", {"job_id": job_id, "ok": ok_count, "errors": err_count})

        # Save by uid (stable across replug); remove any legacy disk-name entry
        assoc.pop(disk, None)
        assoc[uid] = new_player
        device_service.save_associations(assoc)
        profile_service.log_history(
            f"Player changed /dev/{disk}: {old_player} → {new_player}")

    _bg(_run)
    return _ok(job_id=job_id)
