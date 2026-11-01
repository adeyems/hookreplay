import tempfile
import unittest
from pathlib import Path
from hookreplay import Store, export_fixture, import_fixtures

class BulkTest(unittest.TestCase):
    def test_order_and_atomic_failure(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); store=Store(root/'db')
            ids=[store.capture({}, value) for value in (b'first', b'second')]
            paths=[root/'a.json', root/'b.json']
            for id,path in zip(ids,paths): export_fixture(store,id,path)
            imported=import_fixtures(store,paths[::-1])
            self.assertEqual([store.get(i)['body'] for i in imported],[b'second',b'first'])
            count=len(store.list()); paths[1].write_text('{}')
            with self.assertRaises(ValueError): import_fixtures(store,paths)
            self.assertEqual(len(store.list()),count)
            with self.assertRaises(ValueError): import_fixtures(store,[])
    def test_database_failure_rolls_back_earlier_insertions(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); source=Store(root/'source'); target=Store(root/'target')
            paths=[]
            for index,body in enumerate([b'a',b'b']):
                id=source.capture({},body); path=root/f'{index}.json'; export_fixture(source,id,path); paths.append(path)
            with target.connect() as conn:
                conn.execute("CREATE TRIGGER reject_second BEFORE INSERT ON events WHEN NEW.body=x'62' BEGIN SELECT RAISE(ABORT, 'injected'); END")
            with self.assertRaises(sqlite3.IntegrityError): import_fixtures(target,paths)
            self.assertEqual(target.list(),[])
