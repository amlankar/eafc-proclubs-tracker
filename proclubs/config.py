"""Configuration validation shared by the CLI and network collector."""

import re
import tomllib
from pathlib import Path


def validate_config(config):
    try:
        club, collector, dashboard = (config[key] for key in ("club", "collector", "dashboard"))
        for key in ("name", "edition"):
            if (
                not isinstance(club[key], str)
                or not club[key].strip()
                or not 1 <= len(club[key]) <= 100
            ):
                raise ValueError(f"Invalid club {key}")
        if not isinstance(club["id"], str) or not re.fullmatch(r"\d{1,20}", club["id"]):
            raise ValueError("Club id must be a numeric string")
        if not isinstance(club["platform"], str) or not re.fullmatch(
            r"[a-z0-9-]{1,32}", club["platform"]
        ):
            raise ValueError("Invalid platform")
        limits = {
            "minimum_interval_seconds": (3000, 604800),
            "active_interval_seconds": (600, 604800),
            "active_window_seconds": (600, 1800),
            "request_spacing_seconds": (3, 60),
            "timeout_seconds": (5, 60),
            "block_cooldown_seconds": (86400, 31536000),
            "error_cooldown_seconds": (3600, 31536000),
            "metadata_interval_seconds": (86400, 31536000),
        }
        for key, (minimum, maximum) in limits.items():
            value = collector.get(
                key, {"active_interval_seconds": 600, "active_window_seconds": 1800}.get(key)
            )
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"{key} must be an integer from {minimum} to {maximum}")
        if dashboard["host"] not in {"127.0.0.1", "localhost", "0.0.0.0"}:
            raise ValueError("Invalid dashboard host")
        if type(dashboard["port"]) is not int or not 1 <= dashboard["port"] <= 65535:
            raise ValueError("Invalid dashboard port")
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Configuration requires club, collector and dashboard settings") from exc
    return config


def load_config(path):
    with Path(path).open("rb") as file:
        return validate_config(tomllib.load(file))
