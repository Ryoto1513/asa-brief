#!/usr/bin/env python3
"""Deterministic delivery artifacts and read-only GitHub Pages verification.

The caller must validate/editorially approve the manuscript before build_outputs.
Hashes attest byte identity, NOT source truth, interpretation, browser rendering,
RSS freshness or receipt in a ChatGPT conversation. No posting API is called.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request

MAX_BYTES = 2_000_000
HEX256 = re.compile(r'^[0-9a-f]{64}$')


def _json(raw):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError('duplicate_json_key')
            out[key] = value
        return out
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite_json')))


def canonical_hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def build_outputs(payload, raw_bytes):
    """Derive a manifest and plain-text summary from exactly these manuscript bytes.

    No wall clock, network, LLM, truncation or independent prose source is used.
    All retained articles are included and labelled by publication/expiry dates;
    this is an edition inventory, not a claim that archived news happened today.
    """
    if not isinstance(raw_bytes, bytes) or _json(raw_bytes) != payload:
        raise ValueError('payload_bytes_mismatch')
    if (not isinstance(payload, dict) or type(payload.get('schema_version')) is not int or payload.get('schema_version') != 1
            or not isinstance(payload.get('editorial_version'), str)
            or not payload['editorial_version'].strip()
            or not isinstance(payload.get('articles'), list)):
        raise ValueError('invalid_manuscript')
    version = payload['editorial_version']
    lines = [f'朝のブリーフ｜原稿版 {version}',
             '確定原稿の要約一覧（過去記事を含む）。公開・出典再確認・会話送信の完了を意味しません。', '']
    links = []
    for article in payload['articles']:
        fields = ('id', 'title', 'lead', 'published_at', 'home_until')
        if not isinstance(article, dict) or any(not isinstance(article.get(k), str) or not article[k] for k in fields):
            raise ValueError('invalid_summary_article')
        identity = article['id']
        if identity in [link['id'] for link in links]:
            raise ValueError('duplicate_article_id')
        links.append({'id': identity, 'sha256': canonical_hash(article),
                      'published_at': article['published_at'], 'home_until': article['home_until']})
        lines.extend([f"■ {article['title']} [{identity}]", article['lead'],
                      f"発表: {article['published_at']} ／ 今日欄の掲載期限: {article['home_until']}", ''])
    if not links:
        lines.append('この原稿版に編集記事はありません。')
    summary = '\n'.join(lines).rstrip() + '\n'
    manifest = {'schema_version': 1, 'edition': version, 'editorial_version': version,
                'manuscript_sha256': hashlib.sha256(raw_bytes).hexdigest(),
                'article_ids': [link['id'] for link in links], 'articles': links,
                'summary_sha256': hashlib.sha256(summary.encode('utf-8')).hexdigest()}
    return {'manifest': manifest, 'summary': summary}


def _check_manifest(manifest):
    if (not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int or manifest.get('schema_version') != 1
            or not isinstance(manifest.get('edition'), str) or not manifest['edition']
            or manifest.get('editorial_version') != manifest['edition']
            or not isinstance(manifest.get('articles'), list)
            or not isinstance(manifest.get('article_ids'), list)):
        raise ValueError('invalid_manifest')
    for key in ('manuscript_sha256', 'summary_sha256'):
        if not isinstance(manifest.get(key), str) or not HEX256.fullmatch(manifest[key]):
            raise ValueError('invalid_manifest_hash')
    ids = []
    for article in manifest['articles']:
        if (not isinstance(article, dict) or not isinstance(article.get('id'), str) or not article['id']
                or not isinstance(article.get('sha256'), str) or not HEX256.fullmatch(article['sha256'])
                or any(not isinstance(article.get(k), str) or not article[k] for k in ('published_at', 'home_until'))):
            raise ValueError('invalid_manifest_article')
        ids.append(article['id'])
    if ids != manifest['article_ids'] or len(ids) != len(set(ids)):
        raise ValueError('invalid_manifest_ids')


def _base_url(base_url):
    """Limit the live verifier to public GitHub Pages; custom domains need review."""
    if not isinstance(base_url, str) or re.search(r'[\s\\\x00-\x1f\x7f]', base_url):
        raise ValueError('unsafe_public_url')
    try:
        parts = urllib.parse.urlsplit(base_url)
        host = parts.hostname or ''
        if (parts.scheme != 'https' or parts.username is not None or parts.password is not None
                or parts.port not in (None, 443) or parts.query or parts.fragment
                or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?\.github\.io', host)):
            raise ValueError('unsafe_public_url')
        if any(not re.fullmatch(r'[A-Za-z0-9_.-]+', part) or part in ('.', '..')
               for part in parts.path.split('/') if part):
            raise ValueError('unsafe_public_url')
    except ValueError:
        raise ValueError('unsafe_public_url') from None
    return urllib.parse.urlunsplit(('https', host, parts.path.rstrip('/') + '/', '', ''))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A redirect may cross host/scheme or lead to a private endpoint.
        return None


def _download(url):
    request = urllib.request.Request(url, headers={
        'User-Agent': 'AsaBrief/2.0-public-verifier', 'Accept': 'application/json, text/plain',
        'Cache-Control': 'no-cache', 'Pragma': 'no-cache'})
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(request, timeout=12) as response:
        if response.status != 200:
            raise ValueError('unexpected_http_status')
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('public_file_too_large')
    return raw


def delivery_status(expected, state, reason, public_url=None):
    """Report only the website check. Conversation delivery is always not_sent."""
    _check_manifest(expected)
    descriptions = {
        'success': '公開確認成功：原稿・要約・記事ID・版・ハッシュが公開ファイルと一致しました。',
        'delayed': '公開確認待ち：予定の原稿版との一致を確認できません。配信成功とは扱いません。',
        'failed': '公開確認失敗：公開ファイルの不整合または検証エラーがあります。配信成功とは扱いません。',
    }
    if state not in descriptions:
        raise ValueError('invalid_delivery_state')
    return {'state': state, 'reason': reason, 'edition': expected['edition'],
            'manuscript_sha256': expected['manuscript_sha256'],
            'summary_sha256': expected['summary_sha256'],
            'article_ids': list(expected['article_ids']), 'public_url': public_url,
            'conversation_delivery': 'not_sent',
            'message': descriptions[state] + f" 原稿版: {expected['edition']}。会話への自動投稿は未実施です。"}


def verify_public(expected, base_url, downloader=None):
    """Fetch read-only evidence once; never retry, deploy or claim thread delivery.

    A self-consistent but different edition is delayed. Broken/mixed files fail.
    Missing files/network unavailability are delayed, not successful. The caller
    decides whether/when to retry within an authorized deployment observation.
    """
    _check_manifest(expected)
    try:
        base = _base_url(base_url)
    except ValueError:
        return delivery_status(expected, 'failed', 'unsafe_public_url')
    fetch = downloader or _download
    try:
        query = '?asa_brief_sha=' + expected['manuscript_sha256']
        def read(name):
            raw = fetch(base + 'data/' + name + query)
            if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
                raise ValueError('invalid_public_bytes')
            return raw
        raw = read('editorial.json')
        manifest = _json(read('editorial-manifest.json'))
        summary = read('editorial-summary.txt')
        _check_manifest(manifest)
        actual = build_outputs(_json(raw), raw)
        if manifest != actual['manifest'] or summary != actual['summary'].encode('utf-8'):
            return delivery_status(expected, 'failed', 'public_files_inconsistent', base)
        if manifest != expected:
            if manifest['edition'] == expected['edition']:
                return delivery_status(expected, 'failed', 'edition_content_mismatch', base)
            return delivery_status(expected, 'delayed', 'different_edition', base)
        return delivery_status(expected, 'success', 'exact_match', base)
    except urllib.error.HTTPError as error:
        state = 'delayed' if error.code in (404, 408, 425, 429, 500, 502, 503, 504) else 'failed'
        return delivery_status(expected, state, f'http_{error.code}', base)
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return delivery_status(expected, 'delayed', 'public_endpoint_unavailable', base)
    except (ValueError, TypeError, KeyError, UnicodeError):
        return delivery_status(expected, 'failed', 'invalid_public_data', base)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    verify = commands.add_parser('verify', help='read-only comparison with expected build output')
    verify.add_argument('--expected', required=True, type=Path)
    verify.add_argument('--base-url', required=True)
    verify.add_argument('--status-output', type=Path)
    report = commands.add_parser('report', help='record a known failure/delay against the expected manuscript')
    report.add_argument('--expected', required=True, type=Path)
    report.add_argument('--state', required=True, choices=('delayed', 'failed'))
    report.add_argument('--reason', required=True)
    report.add_argument('--status-output', type=Path)
    args = parser.parse_args(argv)
    try:
        expected = _json(args.expected.read_bytes())
        result = (verify_public(expected, args.base_url) if args.command == 'verify'
                  else delivery_status(expected, args.state, args.reason))
    except (ValueError, TypeError, KeyError, OSError):
        result = {'state': 'failed', 'reason': 'invalid_expected_manifest',
                  'conversation_delivery': 'not_sent', 'message': '検証元マニフェストが不正です。公開成功とは扱いません。'}
    output = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.status_output:
        args.status_output.write_text(output, encoding='utf-8')
    print(output, end='')
    # The report command succeeds at writing evidence; its state still says failed/delayed.
    if args.command == 'report' and 'edition' in result:
        return 0
    return 0 if result['state'] == 'success' else 1


if __name__ == '__main__':
    raise SystemExit(main())
