import sys
from pathlib import Path

# Add demo-microservices root to sys.path
demo_root = Path(__file__).resolve().parent.parent
if str(demo_root) not in sys.path:
    sys.path.insert(0, str(demo_root))

