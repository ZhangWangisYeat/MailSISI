"""Config, secrets, and logging."""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Whatever the setup window writes (download folder, schedule) goes here and is
# layered on top of config.yaml, so the shipped file and its comments survive.
SETTINGS_FILE = "settings.yaml"

def base_dir() -> Path:
    """Home for config.yaml, settings.yaml, .env, the db and the log. That's the
    exe's folder once packaged, the project folder from source. It deliberately
    isn't the working directory - Windows starts the logon task from somewhere
    else entirely."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent

def load_config(path: str = "config.yaml") -> dict:
    """config.yaml, plus this machine's settings.yaml on top, plus .env."""
    home = base_dir()
    load_dotenv(home / ".env")

    cfg_path = Path(path)
    if not cfg_path.is_absolute():
        cfg_path = home / cfg_path
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    settings_path = home / SETTINGS_FILE
    if settings_path.exists():
        with open(settings_path, "r", encoding="utf-8") as f:
            cfg.update(yaml.safe_load(f) or {})

    # relative db/log paths belong next to the app, not the working directory
    for key in ("db_path", "log_file"):
        val = cfg.get(key)
        if val and not Path(val).is_absolute():
            cfg[key] = str(home / val)
    return cfg

def get_env(name: str, default: str | None = None, required: bool = False) -> str | None:
    val = os.environ.get(name, default)
    if required and not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val

def setup_logging(cfg: dict) -> logging.Logger:
    logger = logging.getLogger("mailsisi")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    if cfg.get("log_file"):
        fh = RotatingFileHandler(
            cfg["log_file"],
            maxBytes=cfg.get("log_max_bytes", 5_242_880),
            backupCount=cfg.get("log_backup_count", 3),
            encoding="utf-8",
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger

def distributor_rule(cfg: dict, distributor: str) -> dict:
    """That distributor's block from config.yaml, for its per-sender overrides."""
    for rule in cfg.get("senders", []):
        if rule.get("distributor") == distributor:
            return rule
    return {}
