import os
from pathlib import Path


def home_dir() -> Path:
    env = os.environ.get("FLYTRIP_HOME")
    return Path(env) if env else Path.cwd()


def data_dir(home: Path) -> Path:
    path = home / ".flytrip"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir(home: Path) -> Path:
    path = home / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path
