"""Synthetic-only public verification tests: no requests or publication."""
import hashlib
import json
from pathlib import Path
import sys
import unittest
from urllib.error import HTTPError
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import chat_brief_verify as verify


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.body = '# Synthetic\n\nOnly a test.'
        self.sha = hashlib.sha256(self.body.encode()).hexdigest()
        self.date = '2026-10-24'
        self.files = {p: b'synthetic' for p in ('index.html','sw.js','assets/app.js','assets/style.css','data/editorial.json','data/earnings.json')}
        self.files['data/chat-briefs/index.json'] = json.dumps({'dates':[self.date]}).encode()
        self.files['data/chat-briefs/'+self.date+'.md'] = self.body.encode()
        self.files['data/chat-briefs/'+self.date+'.json'] = json.dumps({'body_markdown':self.body,'body_sha256':self.sha,'edition_date':self.date}).encode()
        self.manifest={'schema_version':1,'kind':'chat-news-mirror','editions':[{'edition_date':self.date,'body_sha256':self.sha}], 'files':[{'path':p,'sha256':hashlib.sha256(v).hexdigest()} for p,v in self.files.items()], 'absent_paths':['data/latest.json']}
        self.raw=json.dumps(self.manifest).encode()
        self.files[verify.MANIFEST_PATH]=self.raw
        self.calls=[]
    def fetch(self,url):
        self.calls.append(url)
        path=url.removeprefix('https://example.test/brief/')
        if path not in self.files: raise HTTPError(url,404,'missing',None,None)
        return self.files[path]
    def run_verify(self):
        return verify.verify(self.raw,'https://example.test/brief/',self.fetch)
    def test_exact_hashes_and_absence(self):
        self.assertTrue(self.run_verify()['publication_verified'])
        self.assertEqual(len(self.calls),len(set(self.calls)))
    def test_manifest_mismatch(self):
        self.files[verify.MANIFEST_PATH]+=b' '
        with self.assertRaisesRegex(ValueError,'manifest byte mismatch'):self.run_verify()
    def test_body_mismatch(self):
        self.files['data/chat-briefs/'+self.date+'.md']+=b' changed'
        with self.assertRaisesRegex(ValueError,'hash mismatch'):self.run_verify()
    def test_old_path_still_public(self):
        self.files['data/latest.json']=b'old'
        with self.assertRaisesRegex(ValueError,'obsolete public path'):self.run_verify()
    def test_absence_requires_404_not_network_failure(self):
        def failed(url):
            if url.endswith('data/latest.json'): raise TimeoutError('offline')
            return self.fetch(url)
        with self.assertRaises(TimeoutError):verify.verify(self.raw,'https://example.test/brief/',failed)
    def test_unsafe_base_and_paths(self):
        for url in ('http://example.test/','https://user:password@example.test/','https://example.test/?x=1'):
            with self.subTest(url=url),self.assertRaises(ValueError):verify.verify(self.raw,url,self.fetch)
        for path in ('../secret','/secret','a\\b','a?secret','a//b','a/./b'):
            with self.subTest(path=path),self.assertRaises(ValueError):verify.safe_path(path)
    def test_required_files_not_optional(self):
        self.manifest['files']=self.manifest['files'][1:]
        self.raw=json.dumps(self.manifest).encode()
        with self.assertRaisesRegex(ValueError,'omits required'):self.run_verify()


if __name__=='__main__': unittest.main()
