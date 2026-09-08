"""PyInstaller entry point for the self-contained macOS application backend."""

from lifetrack.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
