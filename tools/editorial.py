"""Offline manuscript validation and optimistic, atomic import. No truth oracle.

Schema 1 remains the application's wire format. New articles carry the additive
manuscript_version=2 contract. Only the three exact historical article hashes
below are grandfathered; editing one requires an explicit migration/review.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import math
import os
import re
import tempfile
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit, urlencode

MAX_BYTES = 2_000_000
JST = timezone(timedelta(hours=9))

LEGACY_HASHES = {
    'disco-20261022-2q': '7962ae5a8c316293aec1e9a0b508380e1c80af003bb178f1af7131ff198e9814',
    'php-critical-20261022': '26a7b626ad8d72c4c6b750518e8305bce4b2f75bc107908911c4c4e2850be3f7',
    'france-unrest-20261022': 'f8de9a4605a22698ff8eba9be7d9eb78ee1d06dc04e3e4e6a6096ac5288f39ff',
}
ROLES = {'what', 'background', 'mechanism', 'impact', 'perspectives', 'outlook'}
KINDS = {'actual': '実績', 'company_forecast': '会社予想', 'market_forecast': '市場予想'}
UNITS = {'億円', '百万円', '円', 'USD', '百万USD', '%', 'pt', '件', '指数', '日'}
MONEY = {'億円': 'JPY', '百万円': 'JPY', '円': 'JPY', 'USD': 'USD', '百万USD': 'USD'}
NUMBER = re.compile(r'^(?:約)?([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(%|pt|億円|百万円|円|百万USD|USD|件|指数|日)?$')
SECRET = re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16}|sk-[A-Za-z0-9_-]{20,})\b|(?:password|passwd|api[_-]?key|access[_-]?token|client[_-]?secret)\s*[:=]\s*\S+', re.I)
EMAIL = re.compile(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', re.I)
PHONE = re.compile(r'(?<!\d)(?:0[789]0[- ]?\d{4}[- ]?\d{4}|\+81[- ]?[789]0[- ]?\d{4}[- ]?\d{4})(?!\d)')
SENSITIVE_KEY = re.compile(r'^(?:password|passwd|api[_-]?key|access[_-]?token|client[_-]?secret|private[_-]?key|email|phone|address|account[_-]?number|my[_-]?number)$', re.I)


class SaveCommittedError(OSError):
    """Replace succeeded, but directory durability is unknown; never retry blindly."""


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def load_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    raw = Path(path).read_bytes()
    if len(raw) > MAX_BYTES:
        raise ValueError('manuscript exceeds 2 MB public-verification limit')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('non-finite JSON number')))


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d(?:\.\d{1,6})?)?(?:Z|[+-]\d\d:\d\d)', value):
        raise ValueError('ISO timestamp with timezone required')
    if not value.endswith('Z') and int(value[-2:]) > 59:
        raise ValueError('invalid offset minutes')
    if value.endswith('-00:00'):
        raise ValueError('unknown timezone offset')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.utcoffset() is None or abs(result.utcoffset().total_seconds()) > 14 * 3600:
        raise ValueError('invalid timezone offset')
    return result


def iso_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('YYYY-MM-DD date required')
    return date.fromisoformat(value)


def safe_url(value):
    """Syntax/public-host check only: no DNS, HTTP, source-content or truth check."""
    if not isinstance(value, str) or re.search(r'[\s\\\x00-\x1f\x7f]', unquote(value)):
        return False
    try:
        p = urlsplit(value)
        if p.scheme != 'https' or not p.hostname or p.username is not None or p.password is not None:
            return False
        if p.port not in (None, 443) or p.fragment:
            return False
        host = p.hostname.encode('idna').decode('ascii').lower()
        if host.endswith(('.local', '.internal', '.localhost')) or host in ('localhost', 'metadata.google.internal'):
            return False
        try:
            if not ipaddress.ip_address(host).is_global:
                return False
        except ValueError:
            if all(re.fullmatch(r'(?:[0-9]+|0x[0-9a-f]+)', x) for x in host.split('.')) or '.' not in host or len(host) > 253 or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', x) for x in host.split('.')):
                return False
        if any(SENSITIVE_KEY.fullmatch(k) or k.lower() in ('token', 'key', 'auth', 'signature') for k, _ in parse_qsl(p.query)):
            return False
        return True
    except (ValueError, UnicodeError):
        return False


def _url_key(value):
    p = urlsplit(value)
    query = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith('utm_')]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip('/'), urlencode(sorted(query)), ''))


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def validate(payload, now=None):
    """Return separate machine/review verdicts; recorded reviews are not verified facts.

    Expired archival articles are retained. Freshness is enforced on the imported
    target, not retrospectively on the whole library, so expiry cannot break RSS.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('now must have a timezone')
    report = {key: {'status': 'passed', 'issues': []} for key in
              ('structural', 'numeric', 'sourcecheck', 'editorial', 'privacy')}
    report['legacy_ids'] = []
    report['sourcecheck']['meaning'] = 'required review attestations present; not an independent source check'
    report['sourcecheck']['source_truth'] = 'not_verified_by_program'
    report['editorial']['editorial_judgment'] = 'recorded_attestation'
    report['legacy_policy'] = 'exact historical hashes exempt from new metadata; no new truth/editorial approval inferred'
    report['limits'] = ['No source fetch or truth verification; reviews are recorded attestations.',
                        'Numeric checks cover bound structured metrics, not arbitrary prose.',
                        'Secret/PII heuristics are incomplete and may reject public contact information. Human review remains required.']

    def issue(group, path, message):
        report[group]['status'] = 'failed'
        report[group]['issues'].append(f'{path}: {message}')

    def need_text(obj, key, path):
        value = obj.get(key)
        if not isinstance(value, str) or not value.strip():
            issue('structural', path + '.' + key, 'nonempty string required')
            return ''
        return value

    def strings(value, path, nonempty=True):
        if not isinstance(value, list) or (nonempty and not value) or any(not isinstance(x, str) or not x.strip() for x in value):
            issue('structural', path, 'list of nonempty strings required')
            return []
        return value

    def refs(value, total, path, required=False):
        if not isinstance(value, list) or (required and not value) or any(type(x) is not int or not 1 <= x <= total for x in value):
            issue('structural', path, 'valid 1-based source references required')
            return []
        if len(set(value)) != len(value):
            issue('structural', path, 'duplicate reference')
        return value

    def stamp(obj, key, path):
        try:
            return timestamp(obj.get(key))
        except (ValueError, TypeError):
            issue('structural', path + '.' + key, 'valid timestamp with timezone required')
            return None

    def privacy(value, path):
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(key, str) and SENSITIVE_KEY.fullmatch(key) and item:
                    issue('privacy', path, 'sensitive field; remove or review outside public manuscript')
                privacy(item, path + '.' + str(key))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                privacy(item, f'{path}[{i}]')
        elif isinstance(value, str) and (SECRET.search(value) or EMAIL.search(value) or PHONE.search(value)):
            issue('privacy', path, 'possible credential or personal contact data (value redacted)')

    if not isinstance(payload, dict):
        issue('structural', '$', 'object required')
        report['ok'] = False
        return report
    privacy(payload, '$')
    if type(payload.get('schema_version')) is not int or payload.get('schema_version') != 1:
        issue('structural', '$.schema_version', 'must be integer 1 (app wire compatibility)')
    need_text(payload, 'editorial_version', '$')
    try:
        iso_date(payload.get('reviewed_on', ''))
    except (ValueError, TypeError):
        issue('structural', '$.reviewed_on', 'ISO date required')
    articles = payload.get('articles')
    if not isinstance(articles, list):
        issue('structural', '$.articles', 'array required')
        articles = []
    seen = {key: set() for key in ('id', 'title', 'source_url', 'disclosure_key')}
    for ai, article in enumerate(articles):
        path = f'$.articles[{ai}]'
        if not isinstance(article, dict):
            issue('structural', path, 'object required')
            continue
        aid = article.get('id')
        for key in seen:
            value = article.get(key)
            if isinstance(value, str) and value:
                normal = ' '.join(value.casefold().split()) if key == 'title' else value
                if key == 'source_url' and safe_url(value):
                    normal = _url_key(value)
                if normal in seen[key]:
                    issue('structural', path + '.' + key, 'duplicate article identity/content')
                seen[key].add(normal)
        if isinstance(aid, str) and aid in LEGACY_HASHES:
            try:
                exact = canonical_hash(article) == LEGACY_HASHES[aid]
            except (ValueError, TypeError):
                exact = False
            if exact:
                report['legacy_ids'].append(aid)
                continue
            issue('structural', path, 'historical article changed; exact regression required')
            continue
        for key in ('id', 'title', 'lead', 'cat', 'priority', 'date', 'scope', 'selection_reason', 'publisher', 'source_url'):
            need_text(article, key, path)
        if not isinstance(aid, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,119}', aid):
            issue('structural', path + '.id', 'stable lowercase slug required')
        if article.get('manuscript_version') != 2 or type(article.get('manuscript_version')) is not int:
            issue('structural', path + '.manuscript_version', 'integer 2 required for new articles')
        for key in ('revision', 'read'):
            if type(article.get(key)) is not int or article[key] < 1:
                issue('structural', path + '.' + key, 'positive integer required')
        for key in ('quality', 'source_kind'):
            if article.get(key) != 'editorial':
                issue('structural', path + '.' + key, 'must be editorial')
        if not safe_url(article.get('source_url')):
            issue('structural', path + '.source_url', 'safe public HTTPS URL required')
        published = stamp(article, 'published_at', path)
        checked = stamp(article, 'checked_at', path)
        expiry = stamp(article, 'home_until', path)
        if published and checked and not published <= checked <= now:
            issue('structural', path, 'require published_at <= checked_at <= validation time')
        if expiry and published and checked and expiry <= max(published, checked):
            issue('structural', path + '.home_until', 'expiry must follow publication and check')
        if published and article.get('date') != published.astimezone(JST).strftime('%m/%d'):
            issue('structural', path + '.date', 'display date must match published_at')
        if checked and article.get('reviewed_on') != checked.astimezone(JST).date().isoformat():
            issue('structural', path + '.reviewed_on', 'display review date must match checked_at')
        for key in ('covered_headlines', 'match_terms'):
            if key in article:
                strings(article[key], path + '.' + key, nonempty=False)
        if 'sections' in article and article['sections'] != []:
            issue('structural', path + '.sections', 'use typed blocks, not legacy sections, for new articles')
        if article.get('cat') not in ('日本経済', '世界経済', '金融政策', '政治・地方自治', '国際情勢', 'AI・産業', '資産形成', '決算', 'セキュリティ', '社会・重要'):
            issue('structural', path + '.cat', 'supported application category required')
        if article.get('priority') not in ('重要', '通常', '参考'):
            issue('structural', path + '.priority', 'supported importance required')
        if article.get('cat') == '決算':
            if not isinstance(article.get('company_code'), str) or not re.fullmatch(r'[0-9A-Z]{4}', article['company_code']):
                issue('structural', path + '.company_code', 'four-character company code required')
            need_text(article, 'disclosure_key', path)
        strings(article.get('takeaways'), path + '.takeaways')
        glossary = article.get('glossary')
        if not isinstance(glossary, list) or not glossary:
            issue('structural', path + '.glossary', 'nonempty glossary required')
        else:
            for i, row in enumerate(glossary):
                if not isinstance(row, list) or len(row) != 2 or any(not isinstance(v, str) or not v.strip() for v in row):
                    issue('structural', f'{path}.glossary[{i}]', 'term/definition string pair required')
        sources = article.get('sources')
        if not isinstance(sources, list) or not sources:
            issue('structural', path + '.sources', 'nonempty sources required')
            sources = []
        source_urls = set()
        for si, source in enumerate(sources):
            sp = f'{path}.sources[{si}]'
            if not isinstance(source, dict):
                issue('structural', sp, 'object required')
                continue
            need_text(source, 'name', sp)
            if not safe_url(source.get('url')):
                issue('structural', sp + '.url', 'safe public HTTPS URL required')
            else:
                key = _url_key(source['url'])
                if key in source_urls:
                    issue('structural', sp, 'duplicate source URL')
                source_urls.add(key)
            source_time = stamp(source, 'published_at', sp)
            if source_time and checked and source_time > checked:
                issue('structural', sp, 'source published after check')
        if safe_url(article.get('source_url')) and _url_key(article['source_url']) not in source_urls:
            issue('structural', path + '.source_url', 'primary URL must appear in sources')
        history = article.get('update_history')
        previous = None
        if not isinstance(history, list) or not history:
            issue('structural', path + '.update_history', 'nonempty history required')
        else:
            for hi, entry in enumerate(history):
                hp = f'{path}.update_history[{hi}]'
                if not isinstance(entry, dict):
                    issue('structural', hp, 'object required')
                    continue
                if type(entry.get('version')) is not int or entry['version'] != hi + 1:
                    issue('structural', hp, 'consecutive versions starting at 1 required')
                need_text(entry, 'summary', hp)
                at = stamp(entry, 'at', hp)
                if at and ((previous and at <= previous) or (published and at < published) or (checked and at > checked)):
                    issue('structural', hp, 'history timestamps must increase within publication/check window')
                previous = at or previous
            if article.get('revision') != len(history) or previous != checked:
                issue('structural', path + '.update_history', 'last revision/time must match revision/checked_at')
        reviews = article.get('review')
        for group in ('sourcecheck', 'editorial'):
            review = reviews.get(group) if isinstance(reviews, dict) else None
            if not isinstance(review, dict) or review.get('status') not in ('passed', 'pending', 'failed'):
                issue(group, path + '.review.' + group, 'recorded review required')
                continue
            if review['status'] == 'failed':
                issue(group, path, 'review failed')
            elif review['status'] == 'pending' and report[group]['status'] != 'failed':
                report[group]['status'] = 'pending'
                report[group]['issues'].append(path + ': review pending')
            if not all(isinstance(review.get(k), str) and review[k].strip() for k in ('reviewer', 'note')):
                issue(group, path, 'reviewer public role and review note required')
            try:
                rt = timestamp(review.get('checked_at'))
                if not checked or rt != checked:
                    raise ValueError()
            except (ValueError, TypeError):
                issue(group, path, 'review time must match checked_at')
        metrics = article.get('metrics')
        if not isinstance(metrics, list):
            issue('numeric', path + '.metrics', 'structured metrics array required (may be empty)')
            metrics = []
        metric_map = {}
        for mi, metric in enumerate(metrics):
            mp = f'{path}.metrics[{mi}]'
            if not isinstance(metric, dict):
                issue('numeric', mp, 'object required')
                continue
            mid = metric.get('id')
            if not isinstance(mid, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', mid) or mid in metric_map:
                issue('numeric', mp, 'unique metric ID required')
                continue
            metric_map[mid] = metric
            if not _finite(metric.get('value')):
                issue('numeric', mp, 'finite numeric value required; boolean is not a number')
            if not isinstance(metric.get('unit'), str) or metric.get('unit') not in UNITS or not isinstance(metric.get('kind'), str) or metric.get('kind') not in KINDS:
                issue('numeric', mp, 'supported unit and actual/forecast kind required')
            if isinstance(metric.get('unit'), str) and metric.get('unit') in MONEY and metric.get('currency') != MONEY[metric['unit']]:
                issue('numeric', mp, 'currency must match monetary unit')
            if type(metric.get('important')) is not bool or metric.get('verification') not in ('verified', 'unverified'):
                issue('numeric', mp, 'importance and evidence status required')
            if metric.get('verification') != 'verified':
                issue('numeric', mp, 'unverified numbers are refused; describe missing evidence without a numeric claim')
            refs(metric.get('refs'), len(sources), mp + '.refs', required=True)
            period = metric.get('period')
            try:
                if not isinstance(period, dict) or not isinstance(period.get('label'), str) or not period['label'].strip():
                    raise ValueError()
                start, end = iso_date(period['start']), iso_date(period['end'])
                if start > end or (metric.get('kind') == 'actual' and checked and end > checked.astimezone(JST).date()):
                    raise ValueError()
            except (ValueError, TypeError, KeyError):
                issue('numeric', mp + '.period', 'ordered ISO dates and visible period label required; actual cannot end after check')
        # Acyclic dependencies and explicit operations; no eval or expressions.
        visiting, visited = set(), set()
        def calculation(mid):
            if mid in visiting:
                issue('numeric', path + '.metrics', 'calculation dependency cycle')
                return
            if mid in visited:
                return
            visiting.add(mid)
            metric = metric_map[mid]
            calc = metric.get('calculation')
            if calc is not None:
                cp = path + '.metrics.' + mid + '.calculation'
                try:
                    if not isinstance(calc, dict) or calc.get('operation') not in ('ratio_percent', 'growth_percent', 'difference', 'sum'):
                        raise ValueError('unsupported operation')
                    ids, precision = calc.get('inputs'), calc.get('precision')
                    if not isinstance(ids, list) or len(ids) != 2 or any(not isinstance(x, str) or x not in metric_map for x in ids):
                        raise ValueError('two known metric inputs required')
                    if type(precision) is not int or not 0 <= precision <= 6:
                        raise ValueError('precision must be 0..6')
                    for dep in ids:
                        calculation(dep)
                    left, right = [metric_map[x] for x in ids]
                    if any(not _finite(m.get('value')) for m in (left, right, metric)):
                        raise ValueError('finite operands required')
                    if left.get('unit') != right.get('unit') or left.get('currency') != right.get('currency'):
                        raise ValueError('operand units/currency must match')
                    if left.get('kind') != right.get('kind') or metric.get('kind') != left.get('kind'):
                        raise ValueError('actual and forecasts cannot be mixed by these operations')
                    op = calc['operation']
                    lp, rp = left.get('period', {}), right.get('period', {})
                    if op == 'growth_percent':
                        ls, le, rs, re_ = [iso_date(x) for x in (lp['start'], lp['end'], rp['start'], rp['end'])]
                        if not re_ < ls or abs((le-ls).days - (re_-rs).days) > 3:
                            raise ValueError('growth needs nonoverlapping comparable current/prior periods')
                    elif (lp.get('start'), lp.get('end')) != (rp.get('start'), rp.get('end')):
                        raise ValueError('operation needs same period')
                    if metric.get('period') != lp:
                        raise ValueError('result period must match first operand')
                    a, b = Decimal(str(left['value'])), Decimal(str(right['value']))
                    if op in ('ratio_percent', 'growth_percent') and b == 0:
                        raise ValueError('zero denominator')
                    if op == 'ratio_percent': value = a / b * 100
                    elif op == 'growth_percent': value = (a / b - 1) * 100
                    elif op == 'difference': value = a - b
                    else: value = a + b
                    unit = '%' if op in ('ratio_percent', 'growth_percent') else 'pt' if op == 'difference' and left['unit'] == '%' else left['unit']
                    if metric.get('unit') != unit:
                        raise ValueError('result unit mismatch')
                    rounded = value.quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_UP)
                    if Decimal(str(metric['value'])) != rounded:
                        raise ValueError('recalculated result mismatch')
                except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
                    issue('numeric', cp, str(exc) if isinstance(exc, ValueError) else 'invalid calculation metadata')
            visiting.discard(mid)
            visited.add(mid)
        for mid in metric_map:
            calculation(mid)
        blocks = article.get('blocks')
        if not isinstance(blocks, list) or not blocks:
            issue('structural', path + '.blocks', 'nonempty blocks required')
            blocks = []
        roles, used_metrics = set(), set()
        for bi, block in enumerate(blocks):
            bp = f'{path}.blocks[{bi}]'
            if not isinstance(block, dict):
                issue('structural', bp, 'object required')
                continue
            need_text(block, 'title', bp)
            claim = block.get('claim_type')
            if claim not in ('fact', 'analysis', 'prediction'):
                issue('structural', bp, 'separate fact/analysis/prediction claim_type required')
            label = {'fact': '事実', 'analysis': '分析', 'prediction': '予測'}.get(claim) if isinstance(claim, str) else None
            if label and label not in str(block.get('title', '')):
                issue('structural', bp + '.title', 'visible 事実/分析/予測 label required without changing the renderer')
            role = block.get('role')
            if not isinstance(role, str) or role not in ROLES:
                issue('structural', bp, 'known editorial role required')
            else:
                roles.add(role)
            refs(block.get('refs', []), len(sources), bp + '.refs', required=claim == 'fact')
            kind = block.get('type')
            bindings = []
            if kind == 'text':
                strings(block.get('paragraphs'), bp + '.paragraphs')
            elif kind == 'flow':
                strings(block.get('steps'), bp + '.steps')
            elif kind == 'timeline':
                rows = block.get('rows')
                if not isinstance(rows, list) or not rows:
                    issue('structural', bp, 'nonempty timeline rows required')
                    rows = []
                previous_event = None
                for row in rows:
                    try:
                        if not isinstance(row, list) or len(row) != 2 or not isinstance(row[1], str) or not row[1].strip():
                            raise ValueError()
                        at = timestamp(row[0])
                        if (previous_event and at <= previous_event) or (claim == 'fact' and checked and at > checked):
                            raise ValueError()
                        previous_event = at
                    except (ValueError, TypeError):
                        issue('structural', bp, 'timeline needs ordered aware timestamps/text; future event is not a fact')
            elif kind in ('table', 'bars'):
                rows = block.get('rows')
                if not isinstance(rows, list) or not rows:
                    issue('structural', bp + '.rows', 'nonempty matrix required')
                    rows = []
                if kind == 'table':
                    headers = strings(block.get('headers'), bp + '.headers')
                    cells = block.get('numeric_cells', [])
                    if not isinstance(cells, list):
                        issue('numeric', bp, 'numeric_cells array required')
                        cells = []
                    cell_map = {}
                    for cell in cells:
                        if not isinstance(cell, dict) or type(cell.get('row')) is not int or type(cell.get('column')) is not int:
                            issue('numeric', bp, 'integer numeric cell coordinates required')
                            continue
                        coord = (cell['row'], cell['column'])
                        if coord in cell_map or not (0 <= coord[0] < len(rows) and 0 <= coord[1] < len(headers)):
                            issue('numeric', bp, 'duplicate/out-of-range numeric binding')
                        cell_map[coord] = cell.get('metric')
                    found = set()
                    for ri, row in enumerate(rows):
                        if not isinstance(row, list) or len(row) != len(headers):
                            issue('structural', bp, 'table row/header width mismatch')
                            continue
                        for ci, value in enumerate(row):
                            if not isinstance(value, str) and not _finite(value):
                                issue('structural', bp, 'table cells must be strings or finite numbers')
                            match = NUMBER.fullmatch(value) if isinstance(value, str) else None
                            if _finite(value) or match or (ri, ci) in cell_map:
                                found.add((ri, ci))
                                number = value if _finite(value) else float(match.group(1).replace(',', '')) if match else None
                                mid = cell_map.get((ri, ci))
                                if match and match.group(2) and isinstance(mid, str) and mid in metric_map and match.group(2) != metric_map[mid].get('unit'):
                                    issue('numeric', bp, 'numeric cell suffix differs from metric unit')
                                # Only this cell's column and first (row-header) cell
                                # describe it. A caption or another row cannot rescue it.
                                context = [headers[ci], row[0] if ci != 0 else '']
                                suffix = match.group(2) if match else None
                                bindings.append((mid, number, context, suffix))
                    if set(cell_map) - found:
                        issue('numeric', bp, 'unused/invalid numeric cell binding')
                else:
                    need_text(block, 'unit', bp)
                    ids = block.get('metric_ids')
                    if not isinstance(ids, list) or len(ids) != len(rows):
                        issue('numeric', bp, 'one metric_id per chart row required')
                        ids = []
                    for ri, row in enumerate(rows):
                        if not isinstance(row, list) or len(row) != 2 or not isinstance(row[0], str) or not row[0] or not _finite(row[1]) or row[1] < 0:
                            issue('numeric', bp, 'bar row requires label/nonnegative finite value (renderer limitation)')
                            continue
                        bindings.append((ids[ri] if ri < len(ids) else None, row[1], [row[0]], block.get('unit')))
            else:
                issue('structural', bp, 'supported block type required')
            for mid, number, context, suffix in bindings:
                if not isinstance(mid, str) or mid not in metric_map:
                    issue('numeric', bp, 'every numeric cell/chart value needs a known metric binding')
                    continue
                metric = metric_map[mid]
                used_metrics.add(mid)
                if not _finite(number) or not _finite(metric.get('value')) or not math.isclose(number, metric['value'], rel_tol=0, abs_tol=1e-9):
                    issue('numeric', bp, 'displayed number differs from structured metric')
                local = ' '.join(x for x in context if isinstance(x, str))
                period = metric.get('period', {})
                label = metric.get('label')
                tokens = (label, KINDS.get(metric.get('kind')) if isinstance(metric.get('kind'), str) else None,
                          period.get('label') if isinstance(period, dict) else None)
                if any(not isinstance(token, str) or not token.strip() or token not in local for token in tokens):
                    issue('numeric', bp, 'bound row/column must label metric, period and actual/company/market forecast')
                labels = {m.get('label') for m in metric_map.values()
                          if isinstance(m.get('label'), str) and m['label'].strip()}
                visible_labels = set(re.findall('|'.join(re.escape(x) for x in sorted(labels, key=len, reverse=True)), local)) if labels else set()
                if not isinstance(label, str) or visible_labels != {label}:
                    issue('numeric', bp, 'bound headers must identify one unambiguous metric label')
                # Reject ambiguous local axes, even if the expected token is present.
                if any(token in local and token != tokens[1] for token in KINDS.values()):
                    issue('numeric', bp, 'bound headers contradict actual/forecast kind')
                periods = {m.get('period', {}).get('label') for m in metric_map.values()
                           if isinstance(m.get('period'), dict) and isinstance(m['period'].get('label'), str)}
                if isinstance(period, dict) and any(token and token in local and token != period.get('label') for token in periods):
                    issue('numeric', bp, 'bound headers contradict metric period')
                # Names and date labels can contain unit characters (日本, 月末日).
                # Remove the already-bound labels before interpreting unit text.
                unit_context = local
                for bound_label in sorted((x for x in (label, period.get('label') if isinstance(period, dict) else None)
                                           if isinstance(x, str) and x), key=len, reverse=True):
                    unit_context = unit_context.replace(bound_label, ' ')
                units = set(re.findall('|'.join(re.escape(u) for u in sorted(UNITS, key=len, reverse=True)), unit_context))
                # A suffix cannot override a contradictory row/column unit.
                if suffix is not None:
                    if suffix != metric.get('unit') or (units and units != {suffix}):
                        issue('numeric', bp, 'numeric cell/chart unit differs from metric')
                else:
                    if not isinstance(metric.get('unit'), str) or units != {metric['unit']}:
                        issue('numeric', bp, 'bound headers must unambiguously label metric unit')
                if claim == 'fact' and metric.get('kind') != 'actual':
                    issue('numeric', bp, 'forecast cannot be labeled as a fact block')
        if not ROLES <= roles:
            issue('structural', path + '.blocks', 'missing what/background/mechanism/impact/perspectives/outlook coverage')
        # Supporting operands may be undisplayed, but all metrics need provenance.
    report['ok'] = all(report[group]['status'] == 'passed' for group in
                       ('structural', 'numeric', 'sourcecheck', 'editorial', 'privacy'))
    return report


def require_valid(payload, now=None):
    report = validate(payload, now=now)
    if not report['ok']:
        raise ValueError(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return report


def order_articles(articles):
    """Stable editorial importance, newest publication, then explicit ID tie-break."""
    legacy_rank = {identifier: index for index, identifier in enumerate(LEGACY_HASHES)}
    # Preserve the approved three-article-only edition. Mixed/new editions use
    # the explicit priority/newness rule, without changing article timestamps.
    if all(a['id'] in legacy_rank for a in articles):
        return sorted(articles, key=lambda a: legacy_rank[a['id']])
    return sorted(articles, key=lambda a: (
        {'重要': 0, '通常': 1, '参考': 2}.get(a.get('priority'), 1),
        -timestamp(a['published_at']).timestamp(),
        a['id']))


def import_article(manuscript, target, mode, base_sha256, base_version, edition, now=None):
    """Validate and compare-and-swap under an exclusive local lock, never merge stale edits.

    The lock serializes cooperative writers on a local filesystem, not remote Git
    writers. Commit/push must separately enforce the expected remote parent SHA.
    """
    now = now or datetime.now(timezone.utc)
    target = Path(target)
    if target.is_symlink() or not target.is_file():
        raise ValueError('target must be an existing regular file, not a symlink')
    if mode not in ('create', 'update') or not re.fullmatch(r'[0-9a-f]{64}', base_sha256 or ''):
        raise ValueError('mode and exact base SHA256 required')
    if not isinstance(edition, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,119}', edition) or edition == base_version:
        raise ValueError('new distinct edition identifier required')
    if not isinstance(manuscript, dict) or not isinstance(manuscript.get('id'), str):
        raise ValueError('single article object required')
    if manuscript['id'] in LEGACY_HASHES:
        raise ValueError('historical articles are immutable in this import contract')
    lock = target.with_name(target.name + '.lock')
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    temp = None
    try:
        os.close(fd)
        before = target.read_bytes()
        if hashlib.sha256(before).hexdigest() != base_sha256:
            raise ValueError('stale base SHA256; reread and reconcile without force')
        payload = load_json(target)
        if payload.get('editorial_version') != base_version:
            raise ValueError('stale base version')
        require_valid(payload, now=now)
        articles = payload['articles']
        matches = [i for i, a in enumerate(articles) if a.get('id') == manuscript['id']]
        if mode == 'create':
            if matches or manuscript.get('revision') != 1:
                raise ValueError('create requires a new ID at revision 1')
            articles.append(manuscript)
        else:
            if len(matches) != 1:
                raise ValueError('update requires exactly one existing ID')
            old = articles[matches[0]]
            if manuscript.get('revision') != old.get('revision', 0) + 1:
                raise ValueError('update revision must advance by one')
            history = manuscript.get('update_history')
            if not isinstance(history, list) or history[:-1] != old.get('update_history'):
                raise ValueError('update must preserve history and append one entry')
            if manuscript.get('published_at') != old.get('published_at'):
                raise ValueError('original publication timestamp must be preserved')
            articles[matches[0]] = manuscript
        payload['articles'] = order_articles(articles)
        payload['editorial_version'] = edition
        payload['reviewed_on'] = timestamp(manuscript.get('checked_at')).astimezone(JST).date().isoformat()
        require_valid(payload, now=now)
        if timestamp(manuscript.get('home_until')) <= now:
            raise ValueError('cannot import an expired manuscript')
        encoded = (json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
        if len(encoded) > MAX_BYTES:
            raise ValueError('merged manuscript exceeds 2 MB public-verification limit')
        # Refuse non-cooperating local edits observed before replace as well.
        if target.read_bytes() != before:
            raise ValueError('target changed during validation')
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.' + target.name + '.', delete=False) as handle:
            temp = Path(handle.name)
            os.fchmod(handle.fileno(), target.stat().st_mode & 0o777)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        if target.read_bytes() != before:
            raise ValueError('target changed before atomic replace')
        os.replace(temp, target)
        temp = None
        try:
            directory = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError as exc:
            # The atomic replace has committed. Rolling back here could destroy
            # a subsequent writer; distinguish uncertainty from a rejected save.
            raise SaveCommittedError('save committed; directory durability unknown; reread target and reconcile, do not retry') from exc
        return payload
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    check = sub.add_parser('validate')
    check.add_argument('path', type=Path)
    imp = sub.add_parser('import')
    imp.add_argument('path', type=Path, help='single v2 article JSON')
    imp.add_argument('--target', type=Path, required=True)
    imp.add_argument('--mode', choices=('create', 'update'), required=True)
    imp.add_argument('--base-sha256', required=True)
    imp.add_argument('--base-version', required=True)
    imp.add_argument('--edition', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'validate':
            report = validate(load_json(args.path))
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report['ok'] else 1
        import_article(load_json(args.path), args.target, args.mode, args.base_sha256, args.base_version, args.edition)
        print('Imported validated article atomically; Git commit/publish and conversation delivery have NOT run.')
        return 0
    except SaveCommittedError:
        print('Editorial save UNKNOWN: replacement committed but directory durability was not confirmed. Reread the target; do not retry automatically.')
        return 2
    except (ValueError, OSError, TypeError, UnicodeError) as exc:
        # Do not dump submitted values or raw input in diagnostics.
        print('Editorial operation refused:', str(exc) if not isinstance(exc, json.JSONDecodeError) else 'invalid JSON')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
