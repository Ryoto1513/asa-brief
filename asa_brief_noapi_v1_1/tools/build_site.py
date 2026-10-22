"""Copy only public website assets into .site for Pages publication."""
from pathlib import Path
import shutil
R=Path(__file__).resolve().parents[1]
out=R/'.site'
if out.exists():shutil.rmtree(out)
out.mkdir()
for name in ('index.html','manifest.webmanifest','sw.js'):
    shutil.copy2(R/name,out/name)
for name in ('assets','data'):
    shutil.copytree(R/name,out/name)
(out/'.nojekyll').touch()
print('Static site prepared:',out)
