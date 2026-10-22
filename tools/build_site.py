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
# Keep editor-authored reports separate from the automatically refreshed edition.
import json
editorial=R/'config/editorial.json'
if editorial.exists():
    payload=json.loads(editorial.read_text(encoding='utf-8'))
    if payload.get('schema_version')!=1:raise ValueError('editorial schema')
    shutil.copy2(editorial,out/'data/editorial.json')
(out/'.nojekyll').touch()
print('Static site prepared:',out)
