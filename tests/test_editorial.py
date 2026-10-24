"""Offline validation/import checks; all new manuscripts are visibly synthetic."""
import copy
import hashlib
import json
import math
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R / 'tools'))
import editorial as e

NOW = datetime.fromisoformat('2026-10-23T11:00:00+09:00')
FIXTURE = R / 'tests/fixtures/editorial_v2.json'


def legacy_collection():
    """Frozen, hash-checked historical unit fixture, never the evolving library."""
    payload = json.loads((R / 'tests/fixtures/editorial_legacy.json').read_text(encoding='utf-8'))
    hashes = {a['id']: e.canonical_hash(a) for a in payload['articles']}
    if len(payload['articles']) != 3 or hashes != e.LEGACY_HASHES:
        raise AssertionError('historical fixture must contain exactly the immutable three articles')
    return payload


def article_checked_at(checked_at):
    """Move a synthetic article coherently, keeping all timestamp relationships."""
    value = article()
    delta = checked_at - e.timestamp(value['checked_at'])
    def shift(node):
        if isinstance(node, dict):
            return {key: shift(item) for key, item in node.items()}
        if isinstance(node, list):
            return [shift(item) for item in node]
        if isinstance(node, str) and re.match(r'^\d{4}-\d\d-\d\dT', node):
            return (e.timestamp(node) + delta).isoformat()
        return node
    value = shift(value)
    value['date'] = e.timestamp(value['published_at']).astimezone(e.JST).strftime('%m/%d')
    value['reviewed_on'] = checked_at.astimezone(e.JST).date().isoformat()
    return value


def article():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


def collection(*articles):
    return {'schema_version': 1, 'editorial_version': 'synthetic-r1',
            'reviewed_on': '2026-10-23', 'articles': list(articles)}


def metric(identifier='sales', value=100, unit='億円', kind='actual', **extra):
    labels = {'sales': '架空売上', 'profit': '架空利益', 'growth': '架空増収率',
              'margin': '架空利益率', 'margin_difference': '架空利益率差'}
    result = {'id': identifier, 'label': labels.get(identifier, identifier), 'value': value, 'unit': unit,
              'kind': kind, 'period': {'start': '2026-04-01', 'end': '2026-09-30', 'label': '2026上期'},
              'refs': [1], 'verification': 'verified', 'important': True}
    if unit in ('円', '百万円', '億円'):
        result['currency'] = 'JPY'
    if unit in ('USD', '百万USD'):
        result['currency'] = 'USD'
    result.update(extra)
    return result


def numeric_article():
    result = article()
    result['metrics'] = [metric()]
    result['blocks'].append({
        'type': 'table', 'title': '事実｜合成数値の比較', 'role': 'what', 'claim_type': 'fact',
        'headers': ['項目', '2026上期 実績（億円）'], 'rows': [['架空売上', '100']],
        'caption': '2026上期 実績。単位：億円。合成テスト値。', 'refs': [1],
        'numeric_cells': [{'row': 0, 'column': 1, 'metric': 'sales'}],
    })
    return result


class ValidationTests(unittest.TestCase):
    def reject(self, value, section=None):
        report = e.validate(value, now=NOW)
        self.assertFalse(report['ok'], report)
        if section:
            self.assertEqual(report[section]['status'], 'failed', report)
        with self.assertRaises(ValueError):
            e.require_valid(value, now=NOW)
        return report

    def test_valid_synthetic_article(self):
        report = e.validate(collection(article()), now=NOW)
        self.assertTrue(report['ok'], report)
        self.assertEqual(report['structural']['status'], 'passed')
        self.assertEqual(report['numeric']['status'], 'passed')
        self.assertEqual(report['sourcecheck']['status'], 'passed')
        self.assertEqual(report['editorial']['status'], 'passed')

    def test_canonical_hash_independent_of_object_key_order(self):
        self.assertEqual(e.canonical_hash({'a': 1, 'b': 2}), e.canonical_hash({'b': 2, 'a': 1}))
        self.assertNotEqual(e.canonical_hash({'a': 1}), e.canonical_hash({'a': 2}))

    def test_collection_shape_and_version(self):
        for bad in (None, [], 'text', {}, {'schema_version': 2, 'articles': []},
                    collection('not-an-object')):
            with self.subTest(bad=bad):
                self.reject(bad, 'structural')

    def test_required_strings(self):
        for field in ('id', 'title', 'lead', 'cat', 'priority', 'published_at', 'checked_at',
                      'home_until', 'scope', 'selection_reason', 'publisher', 'source_url'):
            for bad in (None, '', [], 42):
                with self.subTest(field=field, bad=bad):
                    a = article(); a[field] = bad
                    self.reject(collection(a), 'structural')

    def test_integer_fields_reject_bool_and_invalid_ranges(self):
        for field in ('revision', 'read', 'manuscript_version'):
            for bad in (True, '2', 0, -1):
                with self.subTest(field=field, bad=bad):
                    a = article(); a[field] = bad
                    self.reject(collection(a), 'structural')

    def test_bad_dates_timezone_order_and_expiry(self):
        changes = [
            ('published_at', '2026-10-23T09:00:00'),
            ('checked_at', '2026-13-23T09:30:00+09:00'),
            ('published_at', '2026-10-24T09:00:00+09:00'),
            ('checked_at', '2026-10-22T09:30:00+09:00'),
            ('home_until', '2026-10-23T08:00:00+09:00'),
        ]
        for field, bad in changes:
            with self.subTest(field=field, bad=bad):
                a = article(); a[field] = bad
                self.reject(collection(a), 'structural')

    def test_unsafe_or_malformed_source_urls(self):
        urls = ['javascript:alert(1)', 'file:///tmp/test', 'ftp://example.com/a',
                'https://user:password@example.com/a', 'https:///missing-host',
                'https://localhost/a', 'https://127.0.0.1/a', 'https://10.0.0.1/a',
                'https://[::1]/a', 'https://127.1/a', 'https://example.com:bad/a', 'https://example.com/a\nInjected']
        for url in urls:
            for place in ('primary', 'source'):
                with self.subTest(url=url, place=place):
                    a = article()
                    if place == 'primary': a['source_url'] = url
                    else: a['sources'][0]['url'] = url
                    self.reject(collection(a), 'structural')

    def test_source_timestamps_need_timezone(self):
        a = article(); a['sources'][0]['published_at'] = '2026-10-23'
        self.reject(collection(a), 'structural')

    def date_only_article(self):
        a = article()
        a['sources'][0].update({
            'published_at': '2026-10-23',
            'published_at_precision': 'date_only',
            'publication_note': 'Synthetic publisher date only; time and timezone unknown.',
            'observed_at': a['checked_at'],
            'observation_note': 'Synthetic retrieval fixture; page displayed this date.',
        })
        return a

    def test_date_only_requires_explicit_precision_and_observation_evidence(self):
        a = self.date_only_article()
        before = copy.deepcopy(a)
        report = e.validate(collection(a), now=NOW)
        self.assertTrue(report['ok'], report)
        self.assertEqual(a, before)  # Never fill midnight or substitute observation.
        self.assertEqual(report['sourcecheck']['source_truth'], 'not_verified_by_program')
        for key in ('published_at_precision', 'publication_note', 'observed_at', 'observation_note'):
            bad = copy.deepcopy(a); del bad['sources'][0][key]
            with self.subTest(missing=key):
                self.reject(collection(bad), 'structural')
        for key in ('publication_note', 'observation_note'):
            for value in ('', '  ', None, [], True):
                bad = copy.deepcopy(a); bad['sources'][0][key] = value
                with self.subTest(key=key, value=value):
                    self.reject(collection(bad), 'structural')

    def test_date_only_precision_cannot_bypass_invalid_or_exact_timestamps(self):
        for value in ('2026-02-30', '20261023', '2026-1-2', '', None, [],
                      '2026-10-23T09:00:00+09:00', '2026-10-24T09:00:00Z',
                      '2026-10-23T09:00:00', '2026-10-23T09:00:00+08:99'):
            a = self.date_only_article(); a['sources'][0]['published_at'] = value
            with self.subTest(value=value):
                self.reject(collection(a), 'structural')

    def test_source_precision_mismatch_and_unknown_precision_rejected(self):
        for precision in ('timestamp', '', 'day', 'unknown', None, [], True):
            a = self.date_only_article(); a['sources'][0]['published_at_precision'] = precision
            with self.subTest(precision=precision):
                self.reject(collection(a), 'structural')
        for precision in ('', 'day', 'unknown', None, [], True):
            a = article(); a['sources'][0]['published_at_precision'] = precision
            self.reject(collection(a), 'structural')

    def test_exact_source_timestamp_validation_is_unchanged(self):
        for precision in (None, 'timestamp'):
            for value in ('2026-10-23T00:00:00Z', '2026-10-23T09:00:00+09:00'):
                a = article(); a['sources'][0]['published_at'] = value
                if precision: a['sources'][0]['published_at_precision'] = precision
                report = e.validate(collection(a), now=NOW)
                self.assertTrue(report['ok'], report)
            for value in ('2026-10-23T09:00:00', '2026-10-23T09:00:00-00:00',
                          '2026-10-23T09:00:00+08:99', '2026-10-23T09:00:00+14:01',
                          '2026-10-23T09:00:00+25:00', '2026-10-23T09:31:00+09:00',
                          '2026-10-24T00:00:00Z', '2026-02-30T09:00:00Z'):
                a = article(); a['sources'][0]['published_at'] = value
                if precision: a['sources'][0]['published_at_precision'] = precision
                with self.subTest(precision=precision, value=value):
                    self.reject(collection(a), 'structural')

    def test_date_only_unknown_timezone_uses_observation_not_interval_completion(self):
        a = self.date_only_article()
        # 09:30 JST observation is compatible with this publisher date, but the
        # day has NOT ended globally. Accept only with the actual observation
        # attestation; do not interpret this date as an exact before-cutoff time.
        self.assertTrue(e.validate(collection(a), now=NOW)['ok'])
        for value in ('2026-10-24', '9999-12-31'):
            a['sources'][0]['published_at'] = value
            self.reject(collection(a), 'structural')
        # Boundary: Oct 23 begins earliest at Oct 22 10:00 UTC (UTC+14),
        # even though the viewer in JST still sees Oct 22. No JST inference.
        a = self.date_only_article()
        a['sources'][0]['observed_at'] = '2026-10-22T10:00:00Z'
        self.assertTrue(e.validate(collection(a), now=NOW)['ok'])
        a['sources'][0]['observed_at'] = '2026-10-22T09:59:59Z'
        self.reject(collection(a), 'structural')

    def test_source_observation_requires_real_aware_timestamp_before_check(self):
        for value in (None, '', '2026-10-23', '2026-10-23T09:00:00',
                      '2026-10-23T09:00:00-00:00', '2026-10-23T09:00:00+08:99',
                      '2026-10-23T09:00:00+14:01', '2026-02-30T09:00:00Z',
                      '2026-10-23T09:31:00+09:00', '2026-10-24T09:00:00+09:00'):
            a = self.date_only_article(); a['sources'][0]['observed_at'] = value
            with self.subTest(value=value):
                self.reject(collection(a), 'structural')
        a = article()
        a['sources'][0].update(observed_at='2026-10-23T08:59:59+09:00',
                               observation_note='Synthetic observation before exact publication.')
        self.reject(collection(a), 'structural')
        a['sources'][0]['observed_at'] = a['checked_at']
        self.assertTrue(e.validate(collection(a), now=NOW)['ok'])

    def test_date_only_does_not_relax_article_history_or_review_chronology(self):
        for key, value in (('published_at', '2026-10-23'),
                           ('published_at', '2026-10-23T10:00:00+09:00'),
                           ('checked_at', '2026-10-23'),
                           ('checked_at', '2026-10-24T09:30:00+09:00'),
                           ('home_until', '2026-10-23T09:00:00+09:00')):
            a = self.date_only_article(); a[key] = value
            self.reject(collection(a), 'structural')
        for value in ('2026-10-23', '2026-10-23T09:31:00+09:00'):
            a = self.date_only_article(); a['update_history'][0]['at'] = value
            self.reject(collection(a), 'structural')
            for review in ('sourcecheck', 'editorial'):
                a = self.date_only_article(); a['review'][review]['checked_at'] = value
                self.reject(collection(a))
        a = self.date_only_article(); a['revision'] = 2
        a['update_history'].append({'version': 2, 'at': '2026-10-23T09:29:00+09:00',
                                    'summary': 'Synthetic backwards history'})
        self.reject(collection(a), 'structural')

    def test_refs_are_existing_one_based_integers(self):
        for refs in ([0], [2], [-1], [True], ['1'], '1'):
            with self.subTest(refs=refs):
                a = article(); a['blocks'][0]['refs'] = refs
                self.reject(collection(a), 'structural')

    def test_facts_require_sources_and_claim_type(self):
        for field, value in [('refs', []), ('claim_type', 'mixed'), ('claim_type', None)]:
            a = article(); a['blocks'][0][field] = value
            self.reject(collection(a), 'structural')

    def test_block_role_type_is_checked_without_crashing(self):
        a = article(); a['blocks'][0]['role'] = []
        self.reject(collection(a), 'structural')

    def test_claim_types_are_visibly_labeled(self):
        a = article(); a['blocks'][0]['title'] = '何が起きたか'
        self.reject(collection(a), 'structural')
        a = article(); a['blocks'][-1]['title'] = '事実｜今後の見通し'
        self.reject(collection(a), 'structural')

    def test_article_reviewed_date_matches_check(self):
        a = article(); a['reviewed_on'] = '2026-10-22'
        self.reject(collection(a), 'structural')

    def test_required_editorial_sections(self):
        a = article(); a['blocks'] = a['blocks'][:-1]
        self.reject(collection(a), 'structural')

    def test_collection_article_count_is_not_fixed(self):
        for count in (0, 1, 4):
            values = []
            for n in range(count):
                a = article(); a['id'] += f'-{n}'; a['title'] += f'（別件{n}）'
                a['source_url'] += f'/{n}'; a['sources'][0]['url'] = a['source_url']
                values.append(a)
            report = e.validate(collection(*values), now=NOW)
            self.assertTrue(report['ok'], report)

    def test_duplicate_identity_title_and_source(self):
        for field in ('id', 'title', 'source_url', 'disclosure_key'):
            with self.subTest(field=field):
                a = article(); b = article()
                b['id'] += '-second'; b['title'] += '別件'; b['source_url'] += '/second'
                a['disclosure_key'] = '0000:2026-10-23'; b['disclosure_key'] = '0001:2026-10-23'
                b[field] = a[field]
                self.reject(collection(a, b), 'structural')

    def test_duplicate_title_whitespace_is_normalized(self):
        a = article(); b = article(); b['id'] += '-second'; b['source_url'] += '/second'
        b['title'] = '  ' + a['title'] + '  '
        self.reject(collection(a, b), 'structural')

    def test_legacy_articles_exactly_preserved_and_accepted(self):
        existing = legacy_collection()
        self.assertTrue(e.validate(existing, now=NOW)['ok'])
        for original in existing['articles']:
            changed = copy.deepcopy(original); changed['lead'] += '変更'
            self.reject(collection(changed), 'structural')

    def test_new_id_cannot_reuse_legacy_exemption(self):
        existing = legacy_collection()
        changed = copy.deepcopy(existing['articles'][0]); changed['id'] = 'new-not-grandfathered'
        self.reject(collection(changed), 'structural')

    def test_later_synthetic_check_is_accepted_only_at_trusted_fixture_time(self):
        # Both times are fixed test data, not clocks derived from a manuscript.
        later = NOW + timedelta(hours=1)
        a = article_checked_at(later)
        rejected = self.reject(collection(a), 'structural')
        self.assertIn('require published_at <= checked_at <= validation time',
                      ' '.join(rejected['structural']['issues']))
        self.assertTrue(e.validate(collection(a), now=later)['ok'])
        self.assertTrue(e.validate(collection(a), now=later.astimezone(timezone.utc))['ok'])
        a = article_checked_at(later + timedelta(seconds=1))
        report = e.validate(collection(a), now=later)
        self.assertFalse(report['ok'])
        self.assertIn('require published_at <= checked_at <= validation time',
                      ' '.join(report['structural']['issues']))

    def test_numeric_table_valid(self):
        report = e.validate(collection(numeric_article()), now=NOW)
        self.assertTrue(report['ok'], report)


    def test_coordinate_labels_not_elsewhere_in_table(self):
        a = numeric_article()
        a['metrics'][0]['label'] = '架空売上'
        forecast = metric('forecast', 120, kind='company_forecast', label='架空売上')
        forecast['period'] = {'start': '2026-10-01', 'end': '2027-03-31', 'label': '2026下期'}
        a['metrics'].append(forecast)
        block = a['blocks'][-1]
        block.update(claim_type='analysis', title='分析｜合成比較',
                     headers=['項目', '2026上期 実績（億円）', '2026下期 会社予想（億円）'],
                     rows=[['架空売上', '100', '120']],
                     numeric_cells=[{'row': 0, 'column': 1, 'metric': 'sales'},
                                    {'row': 0, 'column': 2, 'metric': 'forecast'}])
        self.assertTrue(e.validate(collection(a), now=NOW)['ok'])
        for change in ('kind', 'period', 'label', 'missing', 'unit'):
            bad = copy.deepcopy(a); b = bad['blocks'][-1]
            if change == 'kind':
                b['headers'][1] = '2026上期 会社予想（億円）'
                b['headers'][2] = '2026下期 実績（億円）'
            elif change == 'period':
                b['headers'][1] = '2026下期 実績（億円）'
                b['headers'][2] = '2026上期 会社予想（億円）'
            elif change == 'label': b['rows'][0][0] = '架空利益'
            elif change == 'missing': b['headers'][1] = '値'
            else: b['headers'][1] = '2026上期 実績（百万円）'
            with self.subTest(change=change): self.reject(collection(bad), 'numeric')

    def test_metric_identity_missing_and_swapped_rows(self):
        a = numeric_article(); a['metrics'].append(metric('profit', 100))
        b = a['blocks'][-1]
        b['rows'].append(['架空利益', '100'])
        b['numeric_cells'].append({'row': 1, 'column': 1, 'metric': 'profit'})
        self.assertTrue(e.validate(collection(a), now=NOW)['ok'])
        bad = copy.deepcopy(a)
        bad['blocks'][-1]['rows'].reverse()
        self.reject(collection(bad), 'numeric')
        bad = copy.deepcopy(a); del bad['metrics'][0]['label']
        self.reject(collection(bad), 'numeric')

    def test_suffix_cannot_override_header_or_ambiguous_metric_labels(self):
        a = numeric_article()
        a['blocks'][-1]['rows'][0][1] = '100億円'
        a['blocks'][-1]['headers'][1] = '2026上期 実績（百万円）'
        self.reject(collection(a), 'numeric')
        a = numeric_article(); a['metrics'].append(metric('profit', 100))
        a['blocks'][-1]['rows'][0][0] = '架空売上・架空利益'
        self.reject(collection(a), 'numeric')

    def test_metric_and_period_names_are_not_units(self):
        for name, period in (('日本売上', '2026上期'), ('架空売上', '2026年9月30日')):
            a = numeric_article()
            a['metrics'][0]['label'] = name
            a['metrics'][0]['period']['label'] = period
            a['blocks'][-1]['rows'][0][0] = name
            a['blocks'][-1]['headers'][1] = period + ' 実績（億円）'
            with self.subTest(name=name, period=period):
                self.assertTrue(e.validate(collection(a), now=NOW)['ok'])

    def test_order_priority_newness_ties_and_legacy_compatibility(self):
        def item(identity, priority, published):
            return {'id': identity, 'priority': priority, 'published_at': published}
        old = item('old-important', '重要', '2026-10-22T09:00:00+09:00')
        new = item('new-important', '重要', '2026-10-23T09:00:00+09:00')
        normal = item('new-normal', '通常', '2026-10-23T10:00:00+09:00')
        tie = item('a-tie-important', '重要', new['published_at'])
        expected = ['a-tie-important', 'new-important', 'old-important', 'new-normal']
        for sequence in ([normal, old, new, tie], [tie, new, old, normal]):
            self.assertEqual([a['id'] for a in e.order_articles(sequence)], expected)
        legacy = legacy_collection()['articles']
        self.assertEqual(e.order_articles(list(reversed(legacy))), legacy)

    def test_bars_use_each_row_not_other_labels(self):
        a = numeric_article(); a['metrics'].append(metric('profit', 20))
        a['blocks'][-1] = {'type': 'bars', 'title': '事実｜合成', 'role': 'what',
            'claim_type': 'fact', 'unit': '億円', 'refs': [1], 'metric_ids': ['sales', 'profit'],
            'rows': [['架空売上 2026上期 実績', 100], ['架空利益 2026上期 実績', 20]]}
        self.assertTrue(e.validate(collection(a), now=NOW)['ok'])
        a['blocks'][-1]['rows'][0][0] = '架空利益 2026上期 実績'
        self.reject(collection(a), 'numeric')

    def test_jst_display_and_review_dates_for_equivalent_instants(self):
        a = article()
        a['published_at'] = '2026-10-22T23:30:00Z'
        a['checked_at'] = '2026-10-22T23:45:00Z'
        a['sources'][0]['published_at'] = a['published_at']
        a['update_history'][0]['at'] = a['checked_at']
        for review in a['review'].values(): review['checked_at'] = a['checked_at']
        self.assertTrue(e.validate(collection(a), now=NOW)['ok'])
        a['date'] = '10/22'
        self.reject(collection(a), 'structural')

    def test_table_shape_and_cell_binding(self):
        for mutation in ('ragged', 'missing_binding', 'wrong_metric', 'wrong_value', 'bad_position'):
            with self.subTest(mutation=mutation):
                a = numeric_article(); block = a['blocks'][-1]
                if mutation == 'ragged': block['rows'][0].append('extra')
                elif mutation == 'missing_binding': block['numeric_cells'] = []
                elif mutation == 'wrong_metric': block['numeric_cells'][0]['metric'] = 'missing'
                elif mutation == 'wrong_value': block['rows'][0][1] = '999'
                else: block['numeric_cells'][0]['row'] = 9
                self.reject(collection(a))

    def test_metric_types_units_periods_and_refs(self):
        changes = [('value', True), ('value', '100'), ('value', math.inf), ('value', math.nan),
                   ('unit', ''), ('unit', []), ('unit', 'unknown-unit'), ('kind', []), ('kind', 'forecast'), ('refs', []),
                   ('period', {'start': '2026-09-30', 'end': '2026-04-01', 'label': 'bad'}),
                   ('period', {'start': 'bad', 'end': '2026-09-30', 'label': 'bad'})]
        for field, value in changes:
            with self.subTest(field=field, value=value):
                a = numeric_article(); a['metrics'][0][field] = value
                self.reject(collection(a), 'structural' if field == 'refs' else 'numeric')

    def test_huge_number_is_cleanly_rejected(self):
        a = numeric_article(); a['metrics'][0]['value'] = 10 ** 1000
        self.reject(collection(a), 'numeric')

    def test_growth_recomputed_with_comparable_prior_period(self):
        a = numeric_article()
        # Mixed-unit columns state units on each value, not a misleading shared header.
        a['blocks'][-1]['headers'][1] = '2026上期 実績'
        a['blocks'][-1]['rows'][0][1] = '100億円'
        prior = metric('prior_sales', 80)
        prior['period'] = {'start': '2025-04-01', 'end': '2025-09-30', 'label': '2025上期'}
        a['metrics'] += [prior, metric('growth', 25, '%',
                            calculation={'operation': 'growth_percent', 'inputs': ['sales', 'prior_sales'], 'precision': 1})]
        a['blocks'][-1]['rows'].append(['架空増収率', '25%'])
        a['blocks'][-1]['numeric_cells'].append({'row': 1, 'column': 1, 'metric': 'growth'})
        a['blocks'][-1]['caption'] += ' 増加率の単位：%。'
        self.assertTrue(e.validate(collection(a), now=NOW)['ok'])
        bad = copy.deepcopy(a); bad['metrics'][-1]['value'] = 30
        self.reject(collection(bad), 'numeric')
        bad = copy.deepcopy(a); bad['metrics'][1]['period'] = copy.deepcopy(bad['metrics'][0]['period'])
        self.reject(collection(bad), 'numeric')
        bad = copy.deepcopy(a); bad['metrics'][1]['kind'] = 'company_forecast'
        self.reject(collection(bad), 'numeric')
        bad = copy.deepcopy(a); bad['metrics'][1]['unit'] = 'USD'; bad['metrics'][1]['currency'] = 'USD'
        self.reject(collection(bad), 'numeric')

    def test_currency_unit_mismatch(self):
        a = numeric_article(); a['cat'] = '決算'; a['metrics'][0]['currency'] = 'USD'
        self.reject(collection(a), 'numeric')

    def test_duplicate_metric_id(self):
        a = numeric_article(); a['metrics'].append(copy.deepcopy(a['metrics'][0]))
        self.reject(collection(a), 'numeric')

    def test_important_unverified_number_rejected(self):
        a = numeric_article(); a['metrics'][0]['verification'] = 'unverified'
        self.reject(collection(a), 'numeric')

    def test_actual_forecast_labels_are_visible_and_not_interchangeable(self):
        a = numeric_article(); a['metrics'][0]['kind'] = 'company_forecast'
        self.reject(collection(a), 'numeric')
        a = numeric_article(); a['blocks'][-1]['caption'] = '合成'; a['blocks'][-1]['headers'][1] = '値'
        self.reject(collection(a), 'numeric')

    def test_valid_bars_and_invalid_nonfinite_bar(self):
        a = article(); a['metrics'] = [metric()]
        a['blocks'].append({'type': 'bars', 'title': '事実｜合成チャート', 'role': 'what',
                            'claim_type': 'fact', 'unit': '億円', 'rows': [['2026上期 実績 架空売上', 100]],
                            'caption': '2026上期 実績 億円', 'refs': [1], 'metric_ids': ['sales']})
        self.assertTrue(e.validate(collection(a), now=NOW)['ok'])
        a['blocks'][-1]['rows'][0][1] = math.inf
        self.reject(collection(a))

    def test_ratio_recomputed_and_zero_division_rejected(self):
        a = numeric_article()
        # Mixed-unit columns state units on each value, not a misleading shared header.
        a['blocks'][-1]['headers'][1] = '2026上期 実績'
        a['blocks'][-1]['rows'][0][1] = '100億円'
        a['metrics'] += [metric('profit', 20), metric('margin', 20, '%',
                              calculation={'operation': 'ratio_percent', 'inputs': ['profit', 'sales'], 'precision': 1})]
        a['blocks'][-1]['rows'] += [['架空利益率', '20%']]
        a['blocks'][-1]['numeric_cells'] += [{'row': 1, 'column': 1, 'metric': 'margin'}]
        a['blocks'][-1]['caption'] += ' 利益率の単位：%。'
        self.assertTrue(e.validate(collection(a), now=NOW)['ok'])
        bad = copy.deepcopy(a); bad['metrics'][-1]['value'] = 99
        self.reject(collection(bad), 'numeric')
        bad = copy.deepcopy(a); bad['metrics'][0]['value'] = 0; bad['blocks'][-1]['rows'][0][1] = '0'
        self.reject(collection(bad), 'numeric')

    def test_percentage_difference_is_percentage_points(self):
        a = numeric_article()
        # Mixed-unit columns state units on each value, not a misleading shared header.
        a['blocks'][-1]['headers'][1] = '2026上期 実績'
        a['blocks'][-1]['rows'][0][1] = '100億円'
        a['metrics'] += [metric('margin_left', 45, '%'), metric('margin_right', 40, '%'),
                         metric('margin_difference', 5, 'pt', calculation={
                             'operation': 'difference', 'inputs': ['margin_left', 'margin_right'], 'precision': 1})]
        a['blocks'][-1]['rows'].append(['架空利益率差', '5pt'])
        a['blocks'][-1]['numeric_cells'].append({'row': 1, 'column': 1, 'metric': 'margin_difference'})
        a['blocks'][-1]['caption'] += ' 比率差の単位：pt。'
        self.assertTrue(e.validate(collection(a), now=NOW)['ok'])
        a['metrics'][-1]['unit'] = '%'; a['blocks'][-1]['rows'][-1][1] = '5%'
        a['blocks'][-1]['caption'] += ' %'
        self.reject(collection(a), 'numeric')

    def test_timeline_timestamp_order_and_fact_future_guard(self):
        a = article()
        a['blocks'].append({'type': 'timeline', 'title': '事実｜架空の経緯',
                            'role': 'background', 'claim_type': 'fact', 'refs': [1],
                            'rows': [['2026-10-23T09:00:00+09:00', '架空の発表'],
                                     ['2026-10-23T09:15:00+09:00', '架空の確認']]})
        self.assertTrue(e.validate(collection(a), now=NOW)['ok'])
        for rows in ([['bad-date', '説明']], list(reversed(a['blocks'][-1]['rows'])),
                     [['2026-10-24T09:00:00+09:00', '未来の出来事']]):
            with self.subTest(rows=rows):
                bad = copy.deepcopy(a); bad['blocks'][-1]['rows'] = rows
                self.reject(collection(bad), 'structural')

    def test_calculation_missing_inputs_and_cycles_rejected(self):
        for inputs in (['missing', 'sales'], ['sales', 'sales']):
            a = numeric_article()
            a['metrics'][0]['calculation'] = {'operation': 'ratio_percent', 'inputs': inputs, 'precision': 1}
            self.reject(collection(a), 'numeric')

    def test_separate_source_and_editorial_review(self):
        for name in ('sourcecheck', 'editorial'):
            a = article(); a['review'][name]['status'] = 'pending'
            report = e.validate(collection(a), now=NOW)
            self.assertFalse(report['ok'], report)
            self.assertEqual(report['structural']['status'], 'passed', report)
            self.assertEqual(report['numeric']['status'], 'passed', report)
            self.assertEqual(report[name]['status'], 'pending', report)

    def test_secret_and_pii_risk_checks(self):
        samples = ['api_key=' + 'x' * 32, '-----BEGIN PRIVATE KEY-----',
                   'ghp_' + 'A' * 36, 'private-person@example.com', '090-1234-5678']
        for value in samples:
            with self.subTest(kind=value[:12]):
                a = article(); a['blocks'][0]['paragraphs'].append(value)
                self.reject(collection(a), 'privacy')

    def test_nested_shapes_fail_cleanly_instead_of_crashing(self):
        changes = [('blocks', None), ('blocks', [None]), ('sources', []),
                   ('sources', [None]), ('glossary', [['only-one']]),
                   ('takeaways', [None]), ('metrics', [None]), ('review', None)]
        for field, value in changes:
            with self.subTest(field=field, value=value):
                a = article(); a[field] = value
                self.reject(collection(a))

    def test_sourcecheck_and_editorial_failures_do_not_become_passed(self):
        for name in ('sourcecheck', 'editorial'):
            a = article(); a['review'][name]['status'] = 'failed'
            report = self.reject(collection(a))
            self.assertEqual(report[name]['status'], 'failed')
            self.assertEqual(report['structural']['status'], 'passed')

    def test_reports_do_not_echo_secret_values(self):
        secret = 'ghp_' + 'A' * 36
        a = article(); a['blocks'][0]['paragraphs'].append(secret)
        report = self.reject(collection(a), 'privacy')
        self.assertNotIn(secret, json.dumps(report))

    def test_history_version_and_time_order(self):
        for history in ([], [{'version': 2, 'at': article()['checked_at'], 'summary': 'bad'}],
                        [{'version': 1, 'at': '2026-10-22T09:30:00+09:00', 'summary': ''}]):
            a = article(); a['update_history'] = history
            self.reject(collection(a), 'structural')


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = Path(self.temp.name) / 'editorial.json'
        self.write(collection())

    def write(self, payload):
        self.target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def args(self, **overrides):
        raw = self.target.read_bytes()
        result = {'target': self.target, 'mode': 'create',
                  'base_sha256': hashlib.sha256(raw).hexdigest(),
                  'base_version': json.loads(raw)['editorial_version'],
                  'edition': 'synthetic-r2', 'now': NOW}
        result.update(overrides)
        return result

    def test_create_then_update_with_revision_history(self):
        e.import_article(article(), **self.args())
        saved = json.loads(self.target.read_text(encoding='utf-8'))
        self.assertEqual(saved['articles'], [article()])
        self.assertEqual(saved['editorial_version'], 'synthetic-r2')
        updated = article(); updated['revision'] = 2; updated['lead'] = '合成テストの改稿です。'
        updated['checked_at'] = '2026-10-23T10:00:00+09:00'
        updated['update_history'].append({'version': 2, 'at': updated['checked_at'], 'summary': '合成テスト改稿'})
        for review in updated['review'].values(): review['checked_at'] = updated['checked_at']
        e.import_article(updated, **self.args(mode='update', edition='synthetic-r3'))
        saved = json.loads(self.target.read_text(encoding='utf-8'))
        self.assertEqual(saved['articles'], [updated])

    def test_create_alongside_legacy_preserves_every_original_article(self):
        originals = legacy_collection()
        self.write(originals)
        before = copy.deepcopy(originals['articles'])
        e.import_article(article(), **self.args())
        after = json.loads(self.target.read_text(encoding='utf-8'))
        self.assertEqual({a['id']: a for a in after['articles'] if a['id'] in e.LEGACY_HASHES},
                         {a['id']: a for a in before})
        self.assertEqual(after['articles'][0], article())

    def test_stale_hash_or_version_cannot_clobber(self):
        for changes in ({'base_sha256': '0' * 64}, {'base_version': 'stale-version'}):
            before = self.target.read_bytes()
            with self.assertRaises(ValueError): e.import_article(article(), **self.args(**changes))
            self.assertEqual(self.target.read_bytes(), before)

    def test_invalid_manuscript_cannot_change_destination(self):
        a = article(); a['sources'][0]['url'] = 'javascript:bad'
        before = self.target.read_bytes()
        with self.assertRaises(ValueError): e.import_article(a, **self.args())
        self.assertEqual(self.target.read_bytes(), before)

    def test_expired_article_import_refused(self):
        a = article(); a['home_until'] = '2026-10-23T10:30:00+09:00'
        before = self.target.read_bytes()
        with self.assertRaises(ValueError): e.import_article(a, **self.args())
        self.assertEqual(self.target.read_bytes(), before)

    def test_create_duplicate_and_update_unknown_refused(self):
        with self.assertRaises(ValueError): e.import_article(article(), **self.args(mode='update'))
        e.import_article(article(), **self.args())
        before = self.target.read_bytes()
        with self.assertRaises(ValueError): e.import_article(article(), **self.args(edition='synthetic-r3'))
        self.assertEqual(self.target.read_bytes(), before)

    def test_update_cannot_reuse_revision_or_rewrite_history(self):
        e.import_article(article(), **self.args())
        before = self.target.read_bytes()
        with self.assertRaises(ValueError):
            e.import_article(article(), **self.args(mode='update', edition='synthetic-r3'))
        updated = article(); updated['revision'] = 2
        updated['checked_at'] = '2026-10-23T10:00:00+09:00'
        updated['update_history'][0]['summary'] = 'rewritten history'
        updated['update_history'].append({'version': 2, 'at': updated['checked_at'], 'summary': '改稿'})
        for review in updated['review'].values(): review['checked_at'] = updated['checked_at']
        with self.assertRaises(ValueError):
            e.import_article(updated, **self.args(mode='update', edition='synthetic-r3'))
        self.assertEqual(self.target.read_bytes(), before)

    def test_edition_must_change(self):
        with self.assertRaises(ValueError): e.import_article(article(), **self.args(edition='synthetic-r1'))


    def test_final_utf8_capacity_boundary_and_unchanged_rejection(self):
        # The input and current library each fit; their serialized merge may not.
        for size in (1_999_999, 2_000_000, 2_000_001):
            self.write(collection())
            a = article()
            planned = collection(a); planned['editorial_version'] = 'synthetic-r2'
            initial = len((json.dumps(planned, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
            padding = size - initial
            a['lead'] += 'あ' * (padding // 3) + 'x' * (padding % 3)
            self.assertLess(len(json.dumps(a, ensure_ascii=False).encode('utf-8')), 2_000_000)
            before = self.target.read_bytes(); sha = hashlib.sha256(before).hexdigest()
            if size <= 2_000_000:
                e.import_article(a, **self.args())
                self.assertEqual(self.target.stat().st_size, size)
                self.assertEqual(e.load_json(self.target)['articles'], [a])
            else:
                with self.assertRaises(ValueError): e.import_article(a, **self.args())
                self.assertEqual(self.target.read_bytes(), before)
                self.assertEqual(hashlib.sha256(self.target.read_bytes()).hexdigest(), sha)
                self.assertEqual(list(self.target.parent.iterdir()), [self.target])

    def test_merge_over_limit_preserves_existing_article_and_hash(self):
        old = article(); old['id'] += '-old'; old['title'] += '旧'; old['source_url'] += '/old'
        old['sources'][0]['url'] = old['source_url']
        old['lead'] += 'あ' * 340_000
        self.write(collection(old))
        new = article(); new['lead'] += 'あ' * 340_000
        self.assertLess(self.target.stat().st_size, e.MAX_BYTES)
        self.assertLess(len(json.dumps(new, ensure_ascii=False).encode()), e.MAX_BYTES)
        before = self.target.read_bytes()
        with self.assertRaises(ValueError): e.import_article(new, **self.args())
        self.assertEqual(hashlib.sha256(self.target.read_bytes()).digest(), hashlib.sha256(before).digest())
        self.assertEqual(e.load_json(self.target)['articles'], [old])
        self.assertEqual(list(self.target.parent.iterdir()), [self.target])

    def test_temporary_write_failure_preserves_original_and_cleans_up(self):
        before = self.target.read_bytes()
        with patch('editorial.os.fsync', side_effect=OSError('synthetic flush failure')):
            with self.assertRaises(OSError): e.import_article(article(), **self.args())
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(list(self.target.parent.iterdir()), [self.target])

    def test_post_replace_directory_failure_is_explicitly_committed_unknown(self):
        before = self.target.read_bytes()
        with patch('editorial.os.fsync', side_effect=[None, OSError('directory sync failed')]):
            with self.assertRaises(e.SaveCommittedError):
                e.import_article(article(), **self.args())
        self.assertNotEqual(self.target.read_bytes(), before)
        self.assertEqual(e.load_json(self.target)['articles'], [article()])
        self.assertEqual(list(self.target.parent.iterdir()), [self.target])

    def test_import_reviewed_date_is_jst_not_input_offset(self):
        a = article(); a['published_at'] = '2026-10-22T23:30:00Z'
        a['checked_at'] = '2026-10-22T23:45:00Z'
        a['sources'][0]['published_at'] = a['published_at']
        a['update_history'][0]['at'] = a['checked_at']
        for review in a['review'].values(): review['checked_at'] = a['checked_at']
        e.import_article(a, **self.args())
        self.assertEqual(e.load_json(self.target)['reviewed_on'], '2026-10-23')

    def test_replace_failure_preserves_bytes(self):
        before = self.target.read_bytes()
        with patch('editorial.os.replace', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError): e.import_article(article(), **self.args())
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.target.parent.iterdir()), ['editorial.json'])

    def test_existing_lock_refuses_without_removing_other_writer_lock(self):
        lock = self.target.with_name(self.target.name + '.lock')
        lock.write_text('other writer', encoding='utf-8')
        before = self.target.read_bytes()
        with self.assertRaises(FileExistsError): e.import_article(article(), **self.args())
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(lock.read_text(encoding='utf-8'), 'other writer')

    def test_detected_concurrent_edit_is_not_clobbered(self):
        expected_args = self.args()
        original_validator = e.require_valid
        external_bytes = b'{"concurrent": "unrelated edit must survive"}\n'
        calls = 0
        def validating_then_editing(*args, **kwargs):
            nonlocal calls
            result = original_validator(*args, **kwargs)
            calls += 1
            if calls == 2:
                self.target.write_bytes(external_bytes)
            return result
        with patch('editorial.require_valid', side_effect=validating_then_editing):
            with self.assertRaises(ValueError): e.import_article(article(), **expected_args)
        self.assertEqual(self.target.read_bytes(), external_bytes)

    def test_symlink_target_refused(self):
        link = self.target.parent / 'linked.json'; link.symlink_to(self.target)
        before = self.target.read_bytes()
        with self.assertRaises(ValueError): e.import_article(article(), **self.args(target=link))
        self.assertEqual(self.target.read_bytes(), before)

    def test_json_parser_refuses_duplicate_keys_and_nonfinite_literals(self):
        for content in ('{"schema_version":1,"schema_version":2}', '{"n":NaN}', '{"n":Infinity}'):
            with self.subTest(content=content):
                source = self.target.parent / 'input.json'; source.write_text(content, encoding='utf-8')
                with self.assertRaises(ValueError): e.load_json(source)

    def test_import_keeps_rss_and_other_files_untouched(self):
        rss = self.target.parent / 'latest.json'; rss.write_bytes(b'{"rss": "untouched"}\n')
        original = rss.read_bytes()
        e.import_article(article(), **self.args())
        self.assertEqual(rss.read_bytes(), original)


class AdditionalBoundaryTests(unittest.TestCase):
    def test_review_verdicts_do_not_claim_truth_verification(self):
        report = e.validate(collection(article()), now=NOW)
        self.assertTrue(report['ok'])
        self.assertEqual(report['sourcecheck']['source_truth'], 'not_verified_by_program')
        self.assertEqual(report['editorial']['editorial_judgment'], 'recorded_attestation')

    def test_numeric_suffix_cannot_contradict_metadata(self):
        a = numeric_article(); a['blocks'][-1]['rows'][0][1] = '100%'
        self.assertFalse(e.validate(collection(a), now=NOW)['ok'])

    def test_offset_minutes_compact_dates_and_hex_loopback_rejected(self):
        with self.assertRaises(ValueError):
            e.timestamp('2026-10-23T09:00:00+08:99')
        self.assertFalse(e.safe_url('https://0x7f.1/a'))
        a = numeric_article(); a['metrics'][0]['period']['start'] = '20260401'
        self.assertFalse(e.validate(collection(a), now=NOW)['ok'])

    def test_display_metadata_scalar_types_fail_cleanly(self):
        for field in ('unit', 'period_label'):
            for value in (True, 42, float('nan'), 10 ** 1000):
                a = numeric_article()
                if field == 'unit': a['metrics'][0]['unit'] = value
                else: a['metrics'][0]['period']['label'] = value
                with self.subTest(field=field, value_type=type(value).__name__):
                    self.assertFalse(e.validate(collection(a), now=NOW)['ok'])


if __name__ == '__main__':
    unittest.main()
