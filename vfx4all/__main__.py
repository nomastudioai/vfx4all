"""python -m vfx4all [--port 8420] [--host 127.0.0.1]"""

import argparse
import webbrowser

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the VFX 4 All web app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8420)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    url = f"http://{args.host}:{args.port}"
    print(f"VFX 4 All running at {url}")
    if not args.no_browser:
        webbrowser.open(url)
    uvicorn.run("vfx4all.server:app", host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
