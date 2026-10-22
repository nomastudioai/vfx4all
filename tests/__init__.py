"""Offline tests: no network, no Comfy credits. Run from the repository root:

    python -m unittest -v

The package points the app's run folder at a temporary directory before any test imports the app,
so uploads made by the server tests never land in runs/, and blanks the Comfy key (load_dotenv never
overrides a variable that is already set), so no test can reach Comfy Cloud even with a .env present.
"""

import os
import tempfile

os.environ["VFX4ALL_RUNS_DIR"] = tempfile.mkdtemp(prefix="vfx4all-tests-")
os.environ["COMFY_API_KEY"] = ""
