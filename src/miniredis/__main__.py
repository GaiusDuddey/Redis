import argparse
import asyncio
import logging

from miniredis.server import Server


def main() -> None:
    parser = argparse.ArgumentParser(prog="miniredis")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6379)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    try:
        asyncio.run(Server(args.host, args.port).serve_forever())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
