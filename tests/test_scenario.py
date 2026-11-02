import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from hookreplay import Store, replay_scenario
class ScenarioTest(unittest.TestCase):
    def test_explicit_order_duplicates_and_delays(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(str(Path(folder)/'store.db'))
            a=store.capture({},b'a');b=store.capture({},b'b')
            scenario={'version':1,'steps':[{'event_id':b,'delay_ms':3},{'event_id':a,'delay_ms':0},{'event_id':b,'delay_ms':5}]}
            waits=[]
            with patch('hookreplay.replay',side_effect=[200,OSError('synthetic'),503]) as send:
                result=replay_scenario(store,'http://127.0.0.1:1234/',scenario,waits.append)
            self.assertEqual([c.args[1] for c in send.call_args_list],[b,a,b])
            self.assertEqual(waits,[.003,0,.005])
            self.assertFalse(result['http_success'])
            self.assertEqual(result['unreported_steps'],0)
            self.assertTrue(result['results'][1]['network_error'])
    def test_preflight_prevents_partial_execution_and_interrupt_reports_remaining(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(str(Path(folder)/'store.db'));a=store.capture({},b'a')
            scenario={'version':1,'steps':[{'event_id':a,'delay_ms':0},{'event_id':999,'delay_ms':0}]}
            with patch('hookreplay.replay') as send:
                with self.assertRaises(ValueError):replay_scenario(store,'http://127.0.0.1/',scenario)
                send.assert_not_called()
            scenario['steps'][1]['event_id']=a
            with patch('hookreplay.replay',return_value=200) as send:
                result=replay_scenario(store,'http://127.0.0.1/',scenario,sleep=lambda _: (_ for _ in ()).throw(KeyboardInterrupt()))
                send.assert_not_called()
            self.assertTrue(result['stopped']);self.assertEqual(result['unreported_steps'],2)
            with self.assertRaises(ValueError):replay_scenario(store,'http://127.0.0.1:0/',scenario)
