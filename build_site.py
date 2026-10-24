"""Compatibility entry point: always use the fail-closed Chat-mirror builder."""
from pathlib import Path
import runpy
import sys
TOOLS = Path(__file__).resolve().parent / 'tools'
sys.path.insert(0, str(TOOLS))
if __name__ == '__main__':
    runpy.run_path(str(TOOLS / 'build_site.py'), run_name='__main__')
