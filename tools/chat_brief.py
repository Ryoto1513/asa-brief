"""Fail-closed, dependency-free public Chat news manuscript compiler.

Only reviewed news-body Markdown and its public metadata belong in config/chat-briefs.
Conversation transcripts, identifiers, prompts and audit evidence never belong here.
"""
from datetime import datetime, timezone, timedelta, date
import hashlib
import ipaddress
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, unquote

JST = timezone(timedelta(hours=9))
META_KEYS = {'schema_version', 'date', 'title', 'source_kind', 'source_updated_at',
             'information_cutoff', 'body_file', 'body_sha256', 'body_utf8_bytes',
             'body_line_count', 'body_codepoints', 'citation_conversion_count', 'status'}
PRIVATE = re.compile(r'chatgpt\.com/(?:c|g|share|backend-api)/|chat\.openai\.com|'
                     r'conversation[_ -]?id|user[_ -]?id|authorization\s*:|'
                     r'Bearer\s+|sk-[A-Za-z0-9]{12}|(?:system|user|assistant)\s*:', re.I)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timestamp must have a timezone')
    return result


def safe_url(value):
    if not isinstance(value, str) or re.search(r'[\s<>"\\\x00-\x1f]', value):
        raise ValueError('unsafe source URL')
    u = urlsplit(value)
    if u.scheme != 'https' or not u.hostname or u.username or u.password or u.port not in (None, 443):
        raise ValueError('source URL must be public HTTPS without credentials')
    host = u.hostname.lower()
    if host in ('localhost', 'chatgpt.com', 'chat.openai.com') or host.endswith(('.localhost', '.local', '.internal', '.chatgpt.com', '.chat.openai.com')) or '.' not in host:
        raise ValueError('private source URL')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError('IP source URL forbidden')
    if PRIVATE.search(unquote(value)) or re.search(r'(?:token|secret|password|signature|api_key)=', unquote(u.query), re.I):
        raise ValueError('sensitive source URL')
    return value


def inlines(text):
    """Small explicit Markdown allowlist; unknown syntax is an error, never dropped."""
    tokens, plain = [], []
    def flush():
        if plain:
            tokens.append({'type': 'text', 'text': ''.join(plain)})
            plain.clear()
    i = 0
    while i < len(text):
        if text.startswith('**', i):
            end = text.find('**', i + 2)
            if end < 0 or end == i + 2:
                raise ValueError('unclosed or empty strong markup')
            flush(); tokens.append({'type': 'strong', 'children': inlines(text[i + 2:end])}); i = end + 2
        elif text[i] == '*':
            end = text.find('*', i + 1)
            if end < 0 or end == i + 1:
                raise ValueError('unclosed or empty emphasis markup')
            flush(); tokens.append({'type': 'em', 'children': inlines(text[i + 1:end])}); i = end + 1
        elif text[i] == '[':
            match = re.match(r'\[([^\[\]\n]+)\]\((https://[^\s()]+)\)', text[i:])
            if not match:
                raise ValueError('unsupported or unresolved link markup')
            flush(); tokens.append({'type': 'link', 'text': match[1], 'url': safe_url(match[2])}); i += len(match[0])
        elif text[i] in '<>`~\\' or text[i] in '\ue200\ue201\ue202' or text.startswith('![', i):
            raise ValueError('unsupported Markdown or unresolved citation token')
        else:
            plain.append(text[i]); i += 1
    flush()
    return tokens


def parse_markdown(body):
    if not body.strip() or PRIVATE.search(body) or '\x00' in body or re.search(r'[\ue000-\uf8ff]', body):
        raise ValueError('empty, private, or unresolved manuscript')
    lines, blocks, i = body.splitlines(), [], 0
    def cells(line):
        if not line.startswith('|') or not line.endswith('|'):
            raise ValueError('table must have explicit edge pipes')
        return [x.strip() for x in line[1:-1].split('|')]
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1; continue
        h = re.match(r'^(#{1,6}) (.+)$', line)
        if h:
            blocks.append({'type': 'heading', 'level': len(h[1]), 'inlines': inlines(h[2])}); i += 1; continue
        if line == '---':
            blocks.append({'type': 'hr'}); i += 1; continue
        if line.startswith('|'):
            headers = cells(line)
            if i + 1 >= len(lines):
                raise ValueError('missing table divider')
            divider = cells(lines[i + 1])
            if len(headers) != len(divider) or not all(re.fullmatch(r':?-{3,}:?', x) for x in divider):
                raise ValueError('invalid table divider')
            align = ['center' if x.startswith(':') and x.endswith(':') else 'right' if x.endswith(':') else 'left' for x in divider]
            rows = []; i += 2
            while i < len(lines) and lines[i].startswith('|'):
                row = cells(lines[i])
                if len(row) != len(headers):
                    raise ValueError('table column mismatch')
                rows.append([inlines(x) for x in row]); i += 1
            blocks.append({'type': 'table', 'headers': [inlines(x) for x in headers], 'rows': rows, 'align': align}); continue
        li = re.match(r'^([-+*]|\d+\.) (.+)$', line)
        if li:
            ordered = li[1].endswith('.'); start = int(li[1][:-1]) if ordered else 1
            items = []
            while i < len(lines):
                item = re.match(r'^(\d+\.) (.+)$' if ordered else r'^[-+*] (.+)$', lines[i])
                if not item: break
                if ordered and int(item[1][:-1]) != start + len(items):
                    raise ValueError('nonconsecutive ordered list markers unsupported')
                items.append(inlines(item[2] if ordered else item[1])); i += 1
            blocks.append({'type': 'list', 'ordered': ordered, 'start': start, 'items': items}); continue
        para = []
        while i < len(lines) and lines[i].strip():
            current = lines[i]
            if re.match(r'^(?:#|\||---$|[-+*] |\d+\. )', current) and para: break
            if re.match(r'^(?:>|\s{4}|\t|#{1,6}[^ ])', current) or re.search(r'(?<!\w)_[^\n]+_|!\[|\]\[', current):
                raise ValueError('unsupported block markup')
            para.append(current); i += 1
        blocks.append({'type': 'paragraph', 'inlines': inlines('\n'.join(para))})
    return blocks


def load_editions(root, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None: raise ValueError('aware validation time required')
    folder = Path(root) / 'config/chat-briefs'
    if not folder.is_dir(): raise ValueError('canonical Chat manuscript missing')
    if folder.is_symlink() or any(p.is_symlink() or not p.is_file() for p in folder.iterdir()):
        raise ValueError('unexpected directory or symlink in canonical source')
    editions, originals = [], {}
    for path in sorted(folder.glob('*.meta.json')):
        raw_meta = path.read_bytes(); meta = json.loads(raw_meta)
        if set(meta) != META_KEYS or meta['schema_version'] != 1 or meta['status'] != 'verified' or meta['source_kind'] != 'chat-news-mirror':
            raise ValueError('unapproved metadata schema or manuscript')
        day = meta['date']; date.fromisoformat(day)
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day) or day > now.astimezone(JST).date().isoformat():
            raise ValueError('invalid or future edition')
        if path.name != day + '.meta.json' or meta['body_file'] != day + '.md':
            raise ValueError('edition filename mismatch')
        updated = timestamp(meta['source_updated_at']); cutoff = timestamp(meta['information_cutoff'])
        if updated > now or cutoff > now or cutoff > updated or cutoff.astimezone(JST).date().isoformat() != day or updated.astimezone(JST).date().isoformat() < day:
            raise ValueError('inconsistent source edition timestamps')
        if not isinstance(meta['title'], str) or PRIVATE.search(meta['title']) or re.search(r'[<>\n]', meta['title']):
            raise ValueError('unsafe title')
        body_path = folder / meta['body_file']; raw = body_path.read_bytes(); body = raw.decode('utf-8')
        if sha256(raw) != meta['body_sha256'] or len(raw) != meta['body_utf8_bytes'] or len(body) != meta['body_codepoints'] or len(body.splitlines()) != meta['body_line_count']:
            raise ValueError('canonical body integrity mismatch')
        blocks = parse_markdown(body)
        edition = dict(meta, edition_date=day, body_markdown=body, blocks=blocks)
        editions.append(edition); originals[path] = raw_meta; originals[body_path] = raw
    if not editions: raise ValueError('canonical Chat manuscript missing')
    expected = {p.name for p in originals}
    if {p.name for p in folder.iterdir() if p.is_file()} != expected:
        raise ValueError('unexpected files in public manuscript directory')
    return editions, originals
