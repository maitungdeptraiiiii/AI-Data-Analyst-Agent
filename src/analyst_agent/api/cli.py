import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the AI Data Analyst Agent Web API and UI")
    parser.add_argument("--host", default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8002, help="Port number (default: 8002)")
    parser.add_argument(
        "--reload", action="store_true", help="Enable live auto-reload for development"
    )
    args = parser.parse_args()

    print(f"\n🚀 AI Data Analyst Agent Web UI starting at: http://{args.host}:{args.port}/\n")
    uvicorn.run("analyst_agent.api.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
