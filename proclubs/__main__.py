import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .collector import collect, import_seed
from .config import load_config
from .security import migrate_credentials
from .server import serve
from .store import Store

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description="EA FC Clubs local stats archive")
    parser.add_argument("--config", type=Path, default=ROOT / "config.toml")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("collect", help="One conservative collection batch")
    imp = commands.add_parser("import-seed", help="Offline, idempotent initial snapshot import")
    imp.add_argument("directory", type=Path, nargs="?", default=ROOT / "data/seed")
    web = commands.add_parser("serve", help="Read-only local dashboard")
    web.add_argument("--port", type=int)
    web.add_argument(
        "--host",
        choices=["localhost", "127.0.0.1", "0.0.0.0"],
        help="Listen address; 0.0.0.0 enables network access",
    )
    web.add_argument(
        "--shared", action="store_true", help="Password-protected viewer using data/sharing.json"
    )
    commands.add_parser("status")
    commands.add_parser("init", help="Initialize an empty archive without EA requests")
    exp = commands.add_parser("export", help="Lossless JSON archive with raw responses")
    exp.add_argument("destination", type=Path)
    backup = commands.add_parser("backup", help="Consistent SQLite backup, including WAL state")
    backup.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        config = load_config(args.config)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    db_path = args.data_dir / "stats.sqlite3"
    try:
        if args.command == "collect":
            result = collect(db_path, config)
            print(json.dumps(result, indent=2))
            return 1 if result["status"] in {"failed", "partial"} else 0
        if args.command == "import-seed":
            print(json.dumps(import_seed(db_path, config, args.directory), indent=2))
            return 0
        if args.command == "serve":
            sharing = (
                migrate_credentials(
                    args.data_dir / "sharing.json", args.data_dir / "sharing-password.txt"
                )
                if args.shared
                else None
            )
            serve(db_path, config, args.port, sharing, args.host)
            return 0
        store = Store(db_path, config)
        try:
            if args.command == "init":
                print("Initialized empty archive; no EA requests made")
                return 0
            if args.command == "export":
                args.destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                args.destination.write_text(
                    json.dumps(store.export(), indent=2, ensure_ascii=False)
                )
                args.destination.chmod(0o600)
                print(f"Exported to {args.destination}")
            elif args.command == "backup":
                if args.destination.resolve() == db_path.resolve():
                    raise ValueError("Backup destination must differ from active database")
                if args.destination.exists():
                    raise ValueError("Backup destination already exists; choose a new filename")
                args.destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with sqlite3.connect(args.destination) as target:
                    store.db.backup(target)
                args.destination.chmod(0o600)
                print(f"Backed up to {args.destination}")
            else:
                d = store.dashboard()
                print(
                    json.dumps(
                        {
                            "club": d["club"],
                            "baseline": d["baseline"],
                            "overall": d["overall"],
                            "archived_matches": d["archive"]["games"],
                            "runs": d["runs"],
                            "cooldown_until": d["cooldown_until"],
                            "warnings": d["warnings"],
                        },
                        indent=2,
                    )
                )
        finally:
            store.close()
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
