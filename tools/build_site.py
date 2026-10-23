"""Validate the editorial source, then stage only public files for Pages.

Importing this module does not build, fetch, publish, or mutate any data.
"""
from pathlib import Path
import json
import shutil
import tempfile

from editorial import load_json, require_valid
from editorial_delivery import build_outputs

R = Path(__file__).resolve().parents[1]


def build_site(root=R, out=None, now=None):
    root = Path(root)
    out = Path(out) if out is not None else root / '.site'
    if out.is_symlink():
        raise ValueError('refuse symlink build destination')
    source = root / 'config/editorial.json'
    raw = source.read_bytes()
    payload = load_json(source)
    require_valid(payload, now=now)
    generated = build_outputs(payload, raw)
    # Invalid manuscripts fail before touching the previous successful output.
    with tempfile.TemporaryDirectory(prefix='.site-build-', dir=out.parent) as temp:
        staged = Path(temp) / 'public'
        staged.mkdir()
        for name in ('index.html', 'manifest.webmanifest', 'sw.js'):
            shutil.copy2(root / name, staged / name)
        for name in ('assets', 'data'):
            shutil.copytree(root / name, staged / name)
        (staged / 'data/editorial.json').write_bytes(raw)
        (staged / 'data/editorial-manifest.json').write_text(
            json.dumps(generated['manifest'], ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (staged / 'data/editorial-summary.txt').write_text(generated['summary'], encoding='utf-8')
        (staged / '.nojekyll').touch()
        if source.read_bytes() != raw:
            raise ValueError('editorial source changed during build; rebuild from one version')
        if out.exists():
            shutil.rmtree(out)
        staged.rename(out)
    return generated


if __name__ == '__main__':
    build_site()
    print('Static site prepared:', R / '.site')
