"""Curated dates add membership without rewriting immutable articles."""
import unittest
from test_editorial import collection, article, NOW
import editorial as e

class BriefingDates(unittest.TestCase):
    def test_valid_membership(self):
        a=article(); p=collection(a); p['briefings']={'2026-10-23':[a['id']]}
        self.assertTrue(e.validate(p,now=NOW)['ok'])
    def test_invalid_membership(self):
        a=article()
        for mapping in [[], {'2026-02-30':[]}, {'2026-10-24':[a['id']]}, {'2026-10-22':[a['id']]}, {'2026-10-23':['unknown']}, {'2026-10-23':[a['id'],a['id']]}, {'2026-10-23':'bad'}]:
            with self.subTest(mapping=mapping):
                p=collection(a);p['briefings']=mapping
                self.assertFalse(e.validate(p,now=NOW)['ok'])
    def test_utc_publication_uses_jst(self):
        a=article(); a['published_at']='2026-10-22T23:30:00Z'
        p=collection(a);p['briefings']={'2026-10-22':[a['id']]}
        issues=e.validate(p,now=NOW)['structural']['issues']
        self.assertTrue(any('JST' in str(x) for x in issues))
if __name__=='__main__':unittest.main()
