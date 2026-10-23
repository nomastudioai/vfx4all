"""python -m vfx4all [--port 8420] [--host 127.0.0.1] [--no-browser]

VFX4ALL_HOST and VFX4ALL_PORT set the defaults (the Docker image listens on 0.0.0.0).
Behind a reverse proxy, FORWARDED_ALLOW_IPS lists the proxies whose X-Forwarded headers count.
"""

import argparse
import logging
import os
import webbrowser

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the VFX 4 All web app")
    parser.add_argument("--host", default=os.environ.get("VFX4ALL_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("VFX4ALL_PORT", "8420")))
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    url = f"http://{'127.0.0.1' if args.host == '0.0.0.0' else args.host}:{args.port}"
    print(f"VFX 4 All running at {url}")
    if not args.no_browser:
        webbrowser.open(url)
    uvicorn.run("vfx4all.server:app", host=args.host, port=args.port, log_level="warning", proxy_headers=True,
                forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"))


if __name__ == "__main__":
    main()
