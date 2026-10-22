"""Start VFX 4 All from anywhere: python run.py [--port 8420]"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)

from vfx4all.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
