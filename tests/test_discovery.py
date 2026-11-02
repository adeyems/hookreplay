import json
import tempfile
import unittest
from pathlib import Path
from hookreplay import discover_fixtures

class DiscoveryTest(unittest.TestCase):
    def test_sorted_validation_without_import(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'b.json').write_text('{}')
            (root/'a.json').write_text(json.dumps({'version':1,'method':'POST','headers':{},'body_base64':'AP8='}))
            (root/'ignored.txt').write_text('not JSON')
            (root/'nested').mkdir()
            (root/'nested'/'child.json').write_text('{}')
            result=discover_fixtures(root)
            self.assertEqual(result['fixtures'],[{'file':'a.json','valid':True,'body_bytes':2},{'file':'b.json','valid':False}])
            self.assertEqual(len(list(root.iterdir())),4)
    def test_limit_is_not_silent_partial_discovery(self):
        with tempfile.TemporaryDirectory() as folder:
            for i in range(101):(Path(folder)/f'{i}.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'100 JSON'):discover_fixtures(folder)
