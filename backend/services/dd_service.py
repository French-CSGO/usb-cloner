"""
dd_service — runs dd operations in background threads, reports live
progress via SocketIO events, and tracks job state in memory.

Progress event shape:
  { job_id, task_id, label, bytes_done, total_bytes,
    percent, speed, elapsed, eta, status }

Job-complete event shape:
  { job_id, ok, errors }
"""

import logging
import os
import random
import re
import subprocess
import threading
import time
import uuid
from datetime import datetime

log = logging.getLogger("usb-manager")

# ── in-memory job registry ────────────────────────────────────────
jobs: dict[str, dict] = {}
_lock = threading.Lock()

_PROGRESS_RE = re.compile(
    r"(\d+)\s+bytes[^,]*,\s*([\d.]+)\s+s,\s*([\d.]+\s+[KMGT]?B/s)"
)

_DEMO_SIZE = 32 * 1024 * 1024 * 1024  # 32 GB — displayed size in demo


# ── helpers ───────────────────────────────────────────────────────

def get_size(path: str) -> int:
    """Size in bytes — works for regular files and block devices."""
    from config import DEMO_MODE
    if DEMO_MODE and path.startswith("/dev/"):
        return _DEMO_SIZE
    if os.path.isfile(path):
        return os.path.getsize(path)
    r = subprocess.run(["blockdev", "--getsize64", path],
                       capture_output=True, text=True)
    try:
        return int(r.stdout.strip())
    except ValueError:
        return 0


def create_job(operation: str, task_ids: list[str]) -> str:
    job_id = uuid.uuid4().hex[:8]
    with _lock:
        jobs[job_id] = {
            "id":         job_id,
            "operation":  operation,
            "status":     "running",
            "created_at": datetime.now().isoformat(),
            "tasks": {
                tid: {"task_id": tid, "status": "pending", "percent": 0, "label": tid}
                for tid in task_ids
            },
        }
    return job_id


# ── demo simulator ────────────────────────────────────────────────

def _simulate_dd(src: str, dst: str, total_bytes: int,
                 job_id: str, task_id: str, label: str, socketio) -> bool:
    """Fake dd — emits realistic progress events without touching any disk."""
    log.info("[DEMO] %s → %s", src, dst)
    display_total = _DEMO_SIZE  # always show 32 GB in demo
    speed_mbps    = random.randint(75, 115)
    duration      = display_total / (speed_mbps * 1024 * 1024)
    steps         = 40

    with _lock:
        jobs[job_id]["tasks"][task_id].update({
            "status": "running", "label": label, "total_bytes": display_total,
        })

    for i in range(1, steps + 1):
        frac      = i / steps
        bytes_done = int(display_total * frac)
        elapsed    = round(duration * frac, 1)
        speed_now  = f"{speed_mbps + random.randint(-8, 8)} MB/s"
        eta        = int(duration * (1 - frac)) if i < steps else 0
        pct        = min(99, int(frac * 100)) if i < steps else 100
        status     = "done" if i == steps else "running"

        data = {
            "job_id": job_id, "task_id": task_id, "label": label,
            "bytes_done": bytes_done, "total_bytes": display_total,
            "percent": pct, "speed": speed_now,
            "elapsed": elapsed, "eta": eta, "status": status,
        }
        with _lock:
            jobs[job_id]["tasks"][task_id].update(data)
        socketio.emit("progress", data)
        time.sleep(duration / steps)

    # Create a stub file when saving to a non-device path (e.g. joueurs/*.img)
    if not dst.startswith("/dev/"):
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        if not os.path.exists(dst):
            with open(dst, "wb") as f:
                f.write(b"\x00" * 1024)

    return True


# ── single dd task ────────────────────────────────────────────────

def _run_dd(src: str, dst: str, total_bytes: int,
            job_id: str, task_id: str, label: str, socketio) -> bool:
    """
    Run one dd, stream stderr, emit 'progress' events, return success bool.
    In DEMO_MODE, simulates progress without touching any disk.
    """
    from config import DEMO_MODE
    if DEMO_MODE:
        return _simulate_dd(src, dst, total_bytes, job_id, task_id, label, socketio)

    log.info("dd  %s → %s  (%d MB)", src, dst, total_bytes // 1024 // 1024)
    if dst.startswith("/dev/"):
        subprocess.run(["umount", dst], capture_output=True)

    proc = subprocess.Popen(
        ["dd", f"if={src}", f"of={dst}", "bs=4M", "status=progress", "conv=fsync"],
        stderr=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
    )

    with _lock:
        jobs[job_id]["tasks"][task_id].update({
            "status": "running", "pid": proc.pid,
            "label": label, "total_bytes": total_bytes,
        })

    buf = b""
    while True:
        chunk = proc.stderr.read(512)
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
            bytes_done = int(m.group(1))
            elapsed    = float(m.group(2))
            speed      = m.group(3)
            pct = min(99, int(bytes_done / total_bytes * 100)) if total_bytes else 0
            eta = None
            if elapsed > 0 and bytes_done > 0 and total_bytes > bytes_done:
                rate = bytes_done / elapsed
                eta  = int((total_bytes - bytes_done) / rate)

            data = {
                "job_id": job_id, "task_id": task_id, "label": label,
                "bytes_done": bytes_done, "total_bytes": total_bytes,
                "percent": pct, "speed": speed,
                "elapsed": round(elapsed, 1), "eta": eta, "status": "running",
            }
            with _lock:
                jobs[job_id]["tasks"][task_id].update(data)
            socketio.emit("progress", data)

    proc.wait()
    success = proc.returncode == 0
    subprocess.run(["sync"], capture_output=True)
    log.info("dd  %s → %s  %s", src, dst, "OK" if success else "FAILED")

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

def run_parallel(job_id: str, tasks: dict, socketio, sequential=False) -> dict:
    """
    tasks = { task_id: (src, dst, total_bytes, label), ... }
    Returns { task_id: bool } result map.
    """
    results: dict[str, bool] = {}
    threads = []

    def _worker(tid, src, dst, total_bytes, label):
        ok = _run_dd(src, dst, total_bytes, job_id, tid, label, socketio)
        results[tid] = ok

    for tid, (src, dst, total_bytes, label) in tasks.items():
        t = threading.Thread(target=_worker,
                             args=(tid, src, dst, total_bytes, label),
                             daemon=True)
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
