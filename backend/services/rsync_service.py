"""
rsync_service — runs rsync operations in background threads, reports live
progress via SocketIO events, reusing dd_service's job registry so both
appear in the same "ACTIVE OPERATIONS" panel.
"""

import logging
import os
import random
import re
import subprocess
import time

from services import dd_service

log = logging.getLogger("usb-manager")

jobs  = dd_service.jobs
_lock = dd_service._lock

# rsync --info=progress2 line, e.g.:
#   "  1,234,567,890  42%   85.31MB/s    0:00:12"
_PROGRESS_RE = re.compile(r"([\d,]+)\s+(\d{1,3})%\s+([\d.]+\S+/s)")


# ── demo simulator ────────────────────────────────────────────────

def _simulate_rsync(dst: str, job_id: str, task_id: str, label: str, socketio) -> bool:
    log.info("[DEMO] rsync → %s", dst)
    speed_mbps = random.randint(150, 350)
    steps      = 15
    duration   = random.uniform(1.5, 3.0)

    with _lock:
        jobs[job_id]["tasks"][task_id].update({"status": "running", "label": label})

    for i in range(1, steps + 1):
        if task_id in dd_service._cancelled:
            dd_service._cancelled.discard(task_id)
            return False

        frac = i / steps
        pct  = min(99, int(frac * 100)) if i < steps else 100
        status = "done" if i == steps else "running"
        data = {
            "job_id": job_id, "task_id": task_id, "label": label,
            "percent": pct, "speed": f"{speed_mbps} MB/s", "status": status,
        }
        with _lock:
            jobs[job_id]["tasks"][task_id].update(data)
        socketio.emit("progress", data)
        time.sleep(duration / steps)

    os.makedirs(dst, exist_ok=True)
    with open(os.path.join(dst, ".profile_marker"), "w") as f:
        f.write("demo profile\n")

    return True


# ── single rsync task ────────────────────────────────────────────

def run_rsync(src: str, dst: str, job_id: str, task_id: str, label: str, socketio,
              delete: bool = False, link_dest: str | None = None) -> bool:
    """
    Run one rsync of src/ → dst/, emit 'progress' events, return success bool.
    In DEMO_MODE, simulates progress without touching any disk.
    """
    from config import DEMO_MODE
    if DEMO_MODE:
        return _simulate_rsync(dst, job_id, task_id, label, socketio)

    if task_id in dd_service._cancelled:
        dd_service._cancelled.discard(task_id)
        return False

    os.makedirs(dst, exist_ok=True)

    cmd = ["rsync", "-a", "--info=progress2"]
    if delete:
        cmd.append("--delete")
    if link_dest and os.path.isdir(link_dest):
        cmd += ["--link-dest", os.path.abspath(link_dest)]
    cmd += [src.rstrip("/") + "/", dst.rstrip("/") + "/"]

    log.info("rsync %s → %s", src, dst)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    with _lock:
        jobs[job_id]["tasks"][task_id].update({
            "status": "running", "pid": proc.pid, "label": label,
        })

    buf = b""
    while True:
        if task_id in dd_service._cancelled:
            proc.terminate()
            dd_service._cancelled.discard(task_id)
            proc.wait()
            with _lock:
                jobs[job_id]["tasks"][task_id].update({"status": "cancelled"})
            socketio.emit("progress", {
                "job_id": job_id, "task_id": task_id, "label": label,
                "status": "cancelled",
            })
            return False

        chunk = proc.stdout.read(512)
        if not chunk:
            break
        buf += chunk
        while True:
            sep = -1
            for ch in (b"\r", b"\n"):
                idx = buf.find(ch)
                if idx != -1 and (sep == -1 or idx < sep):
                    sep = idx
            if sep == -1:
                break
            line = buf[:sep].decode("utf-8", errors="replace").strip()
            buf = buf[sep + 1:]
            if not line:
                continue
            m = _PROGRESS_RE.search(line)
            if not m:
                continue
            pct   = min(99, int(m.group(2)))
            speed = m.group(3)
            data = {
                "job_id": job_id, "task_id": task_id, "label": label,
                "percent": pct, "speed": speed, "status": "running",
            }
            with _lock:
                jobs[job_id]["tasks"][task_id].update(data)
            socketio.emit("progress", data)

    proc.wait()
    success = proc.returncode == 0
    log.info("rsync %s → %s  %s", src, dst, "OK" if success else "FAILED")

    final_pct    = 100 if success else jobs[job_id]["tasks"][task_id].get("percent", 0)
    final_status = "done" if success else "error"
    with _lock:
        jobs[job_id]["tasks"][task_id].update({
            "status": final_status, "percent": final_pct,
        })
    socketio.emit("progress", {
        "job_id": job_id, "task_id": task_id, "label": label,
        "percent": final_pct, "status": final_status,
    })
    return success


# ── parallel job runner ───────────────────────────────────────────

def run_parallel(job_id: str, tasks: dict, socketio, worker_fn, sequential=False) -> dict:
    """
    tasks = { task_id: (...args for worker_fn), ... }
    worker_fn(task_id, *args) -> bool
    Returns { task_id: bool } result map.
    """
    import threading

    results: dict[str, bool] = {}
    threads = []

    def _worker(tid, args):
        ok = worker_fn(tid, *args)
        results[tid] = ok

    for tid, args in tasks.items():
        t = threading.Thread(target=_worker, args=(tid, args), daemon=True)
        if sequential:
            t.start(); t.join()
        else:
            t.start()
            threads.append(t)

    for t in threads:
        t.join()

    ok_count  = sum(1 for v in results.values() if v)
    err_count = len(results) - ok_count
    with _lock:
        jobs[job_id]["status"] = "done"
        jobs[job_id]["result"] = {"ok": ok_count, "errors": err_count}

    socketio.emit("job_complete", {
        "job_id": job_id, "ok": ok_count, "errors": err_count,
    })
    return results
