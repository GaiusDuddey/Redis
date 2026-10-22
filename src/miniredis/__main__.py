import argparse
import asyncio
import logging
import sys

from miniredis.config import PersistenceConfig
from miniredis.persistence import PersistenceError
from miniredis.server import Server


def main() -> None:
    parser = argparse.ArgumentParser(prog="miniredis")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6379)
    parser.add_argument("--dir", default="data", help="directory for AOF and snapshot files")
    parser.add_argument("--appendonly", action="store_true", help="enable the append-only file")
    parser.add_argument(
        "--appendfsync", choices=["always", "everysec", "no"], default="everysec"
    )
    parser.add_argument(
        "--snapshot-interval", type=float, default=0,
        help="seconds between automatic snapshots (0 = off)",
    )
    parser.add_argument("--aof-rewrite-min-size", type=int, default=64 * 1024 * 1024)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    config = PersistenceConfig(
        dir=args.dir,
        appendonly=args.appendonly,
        appendfsync=args.appendfsync,
        snapshot_interval=args.snapshot_interval,
        rewrite_min_size=args.aof_rewrite_min_size,
    )
    try:
        asyncio.run(Server(args.host, args.port, config).serve_forever())
    except KeyboardInterrupt:
        pass
    except PersistenceError as e:
        logging.getLogger("miniredis").error("refusing to start: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
