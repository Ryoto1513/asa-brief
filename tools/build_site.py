"""Validate the editorial source, then stage only public files for Pages.

Importing this module does not build, fetch, publish, or mutate any data.
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import json
import shutil
import tempfile

from editorial import load_json, require_valid, order_articles, timestamp
from editorial_delivery import build_outputs
from chat_brief import load_editions, sha256

R = Path(__file__).resolve().parents[1]


def build_site(root=R, out=None, now=None):
    root = Path(root)
    out = Path(out) if out is not None else root / '.site'
    if out.is_symlink():
        raise ValueError('refuse symlink build destination')
    source = root / 'config/editorial.json'
    raw = source.read_bytes()
    payload = load_json(source)
    now = now or datetime.now(timezone.utc)
    require_valid(payload, now=now)
    if payload['articles'] != order_articles(payload['articles']):
        raise ValueError('editorial article order must match priority/newness policy; import or review source order')
    editions, originals = load_editions(root, now)
    earnings_payload = dict(payload, articles=[a for a in payload['articles'] if a.get('cat') == '決算'])
    earnings_ids = {a['id'] for a in earnings_payload['articles']}
    if 'briefings' in earnings_payload:
        earnings_payload['briefings'] = {day: [x for x in ids if x in earnings_ids]
                                        for day, ids in earnings_payload['briefings'].items()
                                        if any(x in earnings_ids for x in ids)}
    # Invalid manuscripts fail before touching the previous successful output.
    with tempfile.TemporaryDirectory(prefix='.site-build-', dir=out.parent) as temp:
        staged = Path(temp) / 'public'
        staged.mkdir()
        for name in ('index.html', 'manifest.webmanifest', 'sw.js'):
            shutil.copy2(root / name, staged / name)
        shutil.copytree(root / 'assets', staged / 'assets')
        public_data = staged / 'data'
        briefs = public_data / 'chat-briefs'
        briefs.mkdir(parents=True)
        shutil.copy2(root / 'data/earnings.json', public_data / 'earnings.json')
        def write_json(path, value):
            path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        write_json(public_data / 'editorial.json', earnings_payload)
        summaries = [{k: e[k] for k in ('edition_date', 'body_sha256', 'source_updated_at')} for e in editions]
        write_json(briefs / 'index.json', {'schema_version': 1, 'dates': sorted([e['edition_date'] for e in editions], reverse=True), 'editions': summaries})
        for edition in editions:
            day = edition['edition_date']
            write_json(briefs / (day + '.json'), edition)
            (briefs / (day + '.md')).write_bytes(originals[root / 'config/chat-briefs' / (day + '.md')])
        (staged / '.nojekyll').touch()
        files = [{'path': p.relative_to(staged).as_posix(), 'sha256': sha256(p.read_bytes())}
                 for p in sorted(staged.rglob('*')) if p.is_file() and p.name != '.nojekyll']
        absent = ['data/latest.json', 'data/archive/index.json', 'data/status.json',
                  'data/editorial-manifest.json', 'data/editorial-summary.txt']
        absent += [p.relative_to(root).as_posix() for p in sorted((root / 'data/archive').glob('????-??-??.json'))]
        manifest = {'schema_version': 1, 'kind': 'chat-news-mirror', 'editions': summaries,
                    'files': files, 'absent_paths': absent}
        write_json(public_data / 'chat-brief-manifest.json', manifest)
        if source.read_bytes() != raw or any(p.read_bytes() != b for p, b in originals.items()):
            raise ValueError('source changed during build; rebuild from one version')
        if out.exists():
            shutil.rmtree(out)
        staged.rename(out)
    return {'manifest': manifest}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--as-of', help='aware ISO snapshot timestamp; defaults to current UTC')
    args = parser.parse_args()
    build_site(now=timestamp(args.as_of) if args.as_of else None)
    print('Static site prepared:', R / '.site')
