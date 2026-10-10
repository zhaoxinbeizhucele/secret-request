"""Run the client bundled with this skill, including under Python isolated mode."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from secret_request.client import main

if __name__ == "__main__":
    raise SystemExit(main())
