"""Blog Automation — WordPress upload tooling (skill).

Public entry point: scripts.upload_blog.upload_blog()
CLI entry point:    python -m scripts.run
"""

import sys

# Keep the skill folder bytecode-free. The skill ships as a clean
# directory (no __pycache__/, no .pyc) and stays that way at runtime.
sys.dont_write_bytecode = True

__version__ = "0.1.0"
