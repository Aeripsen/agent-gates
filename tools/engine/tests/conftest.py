import sys
from pathlib import Path

# Flat modules, no package install: put tools/engine on the path so `import ground` works.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
