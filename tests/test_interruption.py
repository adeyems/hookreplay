import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from hookreplay import Store, replay


class InterruptionTest(unittest.TestCase):
    def test_interrupt_preserves_evidence_and_closes_connection(self):
        for phase in ('request', 'getresponse', 'read'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                store = Store(str(Path(directory) / 'capture.sqlite'))
                event = store.capture({}, b'synthetic')
                connection = Mock()
                response = Mock(status=202)
                response.getheader.return_value = None
                connection.getresponse.return_value = response
                interrupted = response.read if phase == 'read' else getattr(connection, phase)
                interrupted.side_effect = KeyboardInterrupt
                with patch('hookreplay.http.client.HTTPConnection', return_value=connection):
                    with self.assertRaises(KeyboardInterrupt):
                        replay(store, event, 'http://127.0.0.1:1234/')
                connection.close.assert_called_once()
                attempts = store.attempts(event)
                self.assertEqual(len(attempts), 1)
                record = store.attempt(attempts[0]['id'])
                self.assertEqual(record['response_complete'], 0)
                self.assertEqual(record['error'], 'Replay interrupted; delivery unknown')
                self.assertEqual(record['status'], 202 if phase == 'read' else None)
                with self.assertRaises(ValueError):
                    store.name_baseline('interrupted', attempts[0]['id'])
