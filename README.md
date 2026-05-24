# USB Key Manager — CS2 Tournament

Web dashboard for mass-cloning USB keys (Windows To Go + CS2) across N drives in parallel, with real-time progress, player profile management, and full save/restore support.

---

## Features

| | |
|---|---|
| **Parallel dd** | Flash N keys simultaneously; live MB/s + ETA per drive via WebSocket |
| **Player profiles** | Save / restore / rename / copy CS2 partition images per player |
| **Session management** | Assign players → keys, switch players between rounds |
| **Master images** | One-shot clone of a master key → stored on SSHD |
| **Dark ops dashboard** | Terminal-style UI, no external runtime dependencies |

---

## Quick start

```bash
# Clone
git clone https://github.com/french-csgo/usb-cloner
cd usb-cloner

# Launch (needs Docker + root access to /dev)
docker compose up -d

# Open dashboard
xdg-open http://localhost:5000
```

> **Privileged mode** is required (`privileged: true` in compose) so the container can call `dd`, `mount`, `blockdev`, etc. on host block devices.

---

## Typical workflow

### First time setup

1. **Mount SSHD** — click *Mount* in the sidebar, enter the disk name (e.g. `sdb`)
2. **Create Master** — insert master USB key, click *Create Master*, enter disk name
3. **Deploy All Keys** — insert all tournament keys, click *Deploy All Keys*

### Between rounds / player swap

1. **Save Players** — flushes each player's CS2 partition to `joueurs/<name>.img` on the SSHD
2. **Assign Players** — reassign keys to the next set of players
3. **Load Players** — restores each player's profile (or blank CS2 for new players)

### Mid-session key swap

Use **Change Player** to save the current player and load a new one on a single key.

---

## API

All endpoints are under `/api/`.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/devices` | List USB disks |
| GET/POST | `/mount/status`, `/mount` | SSHD mount management |
| GET | `/profiles` | List player profiles |
| DELETE | `/profiles/<name>` | Delete a profile |
| POST | `/profiles/rename` | Rename `{old_name, new_name}` |
| POST | `/profiles/copy` | Copy `{src, dst}` |
| GET/POST | `/assignments` | Player ↔ key map |
| POST | `/operations/create-master` | `{disk, partition_win, partition_cs2}` |
| POST | `/operations/deploy` | `{partition_win, partition_cs2}` |
| POST | `/operations/save` | `{partition_cs2}` |
| POST | `/operations/load` | `{partition_cs2}` |
| POST | `/operations/reset` | `{partition_cs2}` |
| POST | `/operations/change-player` | `{disk, new_player, save_old, partition_cs2}` |
| GET | `/jobs`, `/jobs/<id>` | Job status |
| GET | `/history` | Tournament history log |

### WebSocket events (Socket.io)

| Event | Direction | Payload |
|-------|-----------|---------|
| `progress` | server→client | `{job_id, task_id, label, bytes_done, total_bytes, percent, speed, eta, status}` |
| `job_complete` | server→client | `{job_id, ok, errors}` |

---

## Configuration

All paths are environment variables (see `docker-compose.yml`):

| Variable | Default |
|----------|---------|
| `SSHD_MOUNT` | `/mnt/sshd` |
| `IMG_DIR` | `/mnt/sshd/images` |
| `JOUEURS_DIR` | `/mnt/sshd/images/joueurs` |
| `ASSOC_FILE` | `/data/usb_associations.conf` |
| `HISTORY_FILE` | `/mnt/sshd/historique_tournoi.log` |

---

## Docker image

The GitHub Action in `.github/workflows/docker-image.yml` builds and pushes to GHCR on every push to `main` and on version tags:

```bash
docker pull ghcr.io/french-csgo/usb-cloner:latest
```

---

## Hardware requirements

- Linux host (tested on Debian/Ubuntu)
- USB hub with enough bandwidth for N simultaneous writes
- SSHD or NAS with sufficient space (≈ 2× USB key size per player)
