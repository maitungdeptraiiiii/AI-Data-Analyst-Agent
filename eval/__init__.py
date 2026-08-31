import sys
from pathlib import Path

# Ensure src/ is on sys.path for direct module runs
_src_dir = str(Path(__file__).resolve().parent.parent / "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)
