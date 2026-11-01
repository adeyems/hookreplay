import tempfile
import unittest
from pathlib import Path
from hookreplay import Store

class CollectionTest(unittest.TestCase):
    def test_order_persistence_and_atomic_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'events.sqlite'
            store = Store(path)
            a, b = store.capture({}, b'a'), store.capture({}, b'b')
            store.create_collection('demo', [b, a])
            self.assertEqual(Store(path).collections(), [{'name': 'demo', 'event_ids': [b, a]}])
            for name, ids in [('demo', [a]), ('bad name', [a]), ('missing', [a, 999]), ('dup', [a, a]), ('empty', [])]:
                with self.assertRaises(ValueError): store.create_collection(name, ids)
            self.assertEqual(len(store.collections()), 1)
