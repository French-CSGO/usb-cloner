import os

_TEAMS_FILE = os.environ.get("TEAMS_FILE", "/data/teams.conf")


def load_teams() -> dict:
    """Returns {team_name: [player, ...]}"""
    teams = {}
    if not os.path.exists(_TEAMS_FILE):
        return teams
    with open(_TEAMS_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, players_str = line.split("=", 1)
            players = [p.strip() for p in players_str.split(",") if p.strip()]
            teams[name.strip()] = players
    return teams


def save_teams(teams: dict):
    os.makedirs(os.path.dirname(_TEAMS_FILE) or ".", exist_ok=True)
    with open(_TEAMS_FILE, "w") as f:
        for name, players in teams.items():
            f.write(f"{name}={','.join(players)}\n")


def get_team_players(team_name: str) -> list:
    return load_teams().get(team_name, [])
