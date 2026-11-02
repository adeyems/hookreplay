import json
import tempfile
import unittest
from pathlib import Path
from hookreplay import Store, export_collection

class CollectionExportTest(unittest.TestCase):
    def test_order_bytes_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(str(Path(folder)/'data.sqlite'))
            first=store.capture({},b'one');second=store.capture({},b'\x00\xff')
            store.create_collection('demo',[second,first]);output=Path(folder)/'bundle.json'
            self.assertEqual(export_collection(store,'demo',output),2)
            original=output.read_bytes();bundle=json.loads(original)
            self.assertEqual(bundle['name'],'demo')
            self.assertEqual([f['body_base64'] for f in bundle['fixtures']],['AP8=','b25l'])
            self.assertNotIn('event_ids',bundle)
            with self.assertRaises(FileExistsError):export_collection(store,'demo',output)
            self.assertEqual(output.read_bytes(),original)
            missing=Path(folder)/'missing.json'
            with self.assertRaises(ValueError):export_collection(store,'absent',missing)
            self.assertFalse(missing.exists())
