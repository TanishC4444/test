import contextlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from newsbrief import Store, week_key

@contextlib.contextmanager
def isolated_working_directory():
    original = Path.cwd()
    with tempfile.TemporaryDirectory() as directory:
        os.chdir(directory)
        try:
            yield Path(directory)
        finally:
            os.chdir(original)

class StoreTests(unittest.TestCase):
    def test_roundtrip_and_summary_preservation(self):
        with isolated_working_directory():
            store = Store('store.json')
            article = {'link':'https://example.com/demo','text':'Synthetic article','retrieved_at':datetime.now(timezone.utc).isoformat()}
            store.upsert(article)
            store.set_summary(article['link'], 'Synthetic summary')
            store.upsert({**article, 'title':'Updated title'})
            loaded = Store('store.json')
            self.assertTrue(loaded.has(article['link']))
            self.assertEqual(loaded.all()[0]['summary'], 'Synthetic summary')
            self.assertEqual(loaded.unsummarized(), [])
            weekly = json.loads(Path('data', week_key()+'.json').read_text())
            self.assertIn(article['link'], weekly['articles'])

    def test_old_rolling_items_are_trimmed_without_deleting_weekly_archive(self):
        with isolated_working_directory():
            Path('data').mkdir()
            archive = Path('data/2000-W01.json')
            archive.write_text('{"articles":{"old":{"text":"Retained history"}}}')
            Path('store.json').write_text('{"articles":{"old":{"retrieved_at":"2000-01-01T00:00:00+00:00","text":"Old story"}}}')
            self.assertEqual(Store('store.json').all(), [])
            self.assertIn('Retained history', archive.read_text())

if __name__ == '__main__':
    unittest.main()
