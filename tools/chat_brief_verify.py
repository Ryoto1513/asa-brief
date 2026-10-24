"""Single-attempt, fail-closed public Chat mirror verification (stdlib only)."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

MANIFEST_PATH = 'data/chat-brief-manifest.json'


def safe_path(value):
    if not isinstance(value, str) or not value or '\\' in value or '?' in value or '#' in value:
        raise ValueError('invalid public path')
    p = PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or str(p) != value:
        raise ValueError('invalid public path')
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('unexpected public redirect')


def download(url):
    request = Request(url, headers={'Cache-Control': 'no-cache', 'User-Agent': 'asa-brief-public-verification/1'})
    with build_opener(NoRedirect()).open(request, timeout=30) as response:
        if response.geturl() != url:
            raise ValueError('unexpected public redirect')
        return response.read(4 * 1024 * 1024 + 1)


def verify(expected_raw, base_url, downloader=download):
    expected = json.loads(expected_raw)
    if type(expected.get('schema_version')) is not int or expected.get('schema_version') != 1 or expected.get('kind') != 'chat-news-mirror':
        raise ValueError('invalid manifest schema')
    parsed = urlsplit(base_url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('invalid public base URL')
    base_url = base_url.rstrip('/') + '/'
    files = expected.get('files')
    if not isinstance(files, list) or not files:
        raise ValueError('missing manifest files')
    paths = [safe_path(f['path']) for f in files]
    if len(paths) != len(set(paths)) or MANIFEST_PATH in paths:
        raise ValueError('duplicate or recursive manifest path')
    required = {'index.html', 'sw.js', 'assets/app.js', 'assets/style.css', 'data/chat-briefs/index.json', 'data/editorial.json', 'data/earnings.json'}
    editions = expected.get('editions')
    if not isinstance(editions, list) or not editions:
        raise ValueError('missing verified editions')
    for edition in editions:
        date = edition['edition_date']
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date) or not re.fullmatch('[0-9a-f]{64}', edition['body_sha256']):
            raise ValueError('invalid edition')
        required.update({f'data/chat-briefs/{date}.md', f'data/chat-briefs/{date}.json'})
    if not required.issubset(paths):
        raise ValueError('manifest omits required files')
    absent = [safe_path(p) for p in expected.get('absent_paths', [])]
    if set(absent) & set(paths):
        raise ValueError('contradictory absent path')
    if downloader(base_url + MANIFEST_PATH) != expected_raw:
        raise ValueError('public manifest byte mismatch')
    public = {}
    for record in files:
        if not re.fullmatch('[0-9a-f]{64}', record['sha256']):
            raise ValueError('invalid hash')
        raw = downloader(base_url + record['path'])
        if len(raw) > 4 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != record['sha256']:
            raise ValueError('public file hash mismatch: ' + record['path'])
        public[record['path']] = raw
    index = json.loads(public['data/chat-briefs/index.json'])
    if set(index['dates']) != {e['edition_date'] for e in editions}:
        raise ValueError('public index dates mismatch')
    for edition in editions:
        prefix = 'data/chat-briefs/' + edition['edition_date']
        raw = public[prefix + '.md']
        payload = json.loads(public[prefix + '.json'])
        if hashlib.sha256(raw).hexdigest() != edition['body_sha256'] or payload['body_markdown'].encode('utf-8') != raw or payload['body_sha256'] != edition['body_sha256'] or payload['edition_date'] != edition['edition_date']:
            raise ValueError('canonical public body mismatch')
    for path in absent:
        try:
            downloader(base_url + path)
        except HTTPError as error:
            if error.code not in (404, 410):
                raise
        else:
            raise ValueError('obsolete public path still accessible: ' + path)
    return {'state': 'success', 'publication_verified': True, 'manifest_sha256': hashlib.sha256(expected_raw).hexdigest(), 'edition_dates': index['dates'], 'files_verified': len(files), 'obsolete_paths_absent': len(absent), 'conversation_delivery': 'not_sent'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected', required=True)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--status-output', required=True)
    args = parser.parse_args()
    result = {'state': 'failed', 'publication_verified': False, 'conversation_delivery': 'not_sent'}
    try:
        result = verify(Path(args.expected).read_bytes(), args.base_url)
    except Exception as error:
        # Do not persist remote response bodies, request metadata, or credentials.
        result['reason'] = type(error).__name__ + ': ' + str(error)[:500]
    Path(args.status_output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['state'] == 'success' else 1


if __name__ == '__main__':
    raise SystemExit(main())
