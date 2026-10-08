import copy
import importlib.util
import unittest

class LedgerTests(unittest.TestCase):
    def model(self):
        self.assertIsNotNone(importlib.util.find_spec('model'), 'transition model missing')
        from model import Model
        return Model()

    def test_01_funding(self):
        m = self.model()
        m.create(1, 'creator-0', 120, 10)
        s = m.snapshot()
        self.assertEqual(s['locked'], {'1': 120})
        self.assertEqual(s['liabilities'], 120)
        self.assertEqual(s['token_balance'], 120)
        self.assertEqual(m.events[0]['event'], 'BountyCreated')

    def test_02_failed_withdraw_rolls_back(self):
        m = self.model()
        self.assertTrue(hasattr(m, 'award'), 'settlement transition missing')
        m.create(1, 'creator-0', 120, 10)
        m.create(2, 'creator-0', 80, 10)
        m.award(1, 'winner-0', 'creator-0')
        m.award(2, 'winner-0', 'creator-0')
        before = copy.deepcopy(m.snapshot())
        events = copy.deepcopy(m.events)
        self.assertFalse(m.withdraw('winner-0', 'recipient-0', fail=True))
        self.assertEqual(m.snapshot(), before)
        self.assertEqual(m.events, events)
        self.assertEqual(m.attempts[-1]['transient_credit'], 0)
        self.assertEqual(m.attempts[-1]['restored_credit'], 200)
        self.assertTrue(m.withdraw('winner-0', 'recipient-0'))
        m.create(3, 'creator-0', 50, 10)
        with self.assertRaisesRegex(ValueError, 'too early'):
            m.expire(3, now=10)
        m.expire(3, now=10+604801)
        self.assertEqual(m.credits['creator-0'], 50)
        m.donate('donor-0', 17)
        self.assertEqual(m.snapshot()['token_balance']-m.snapshot()['liabilities'], 17)

    def test_03_independent_reconciliation(self):
        self.assertIsNotNone(importlib.util.find_spec('reconcile'), 'independent reconciler missing')
        from reconcile import reconcile, Failure
        import json
        from pathlib import Path
        abi = json.loads(Path('escrow-abi.json').read_text())
        m = self.model()
        m.create(1, 'creator-0', 120, 10)
        m.award(1, 'winner-0', 'creator-0')
        m.donate('donor-0', 17)
        from model import block_hash
        fixture = dict(events=m.events, snapshot=m.snapshot(), anchor={'number':m.block, 'hash':block_hash(m.block)},
                       headers={str(i):block_hash(i) for i in range(1,m.block+1)})
        result = reconcile(fixture, abi)
        self.assertEqual(result['credits'], {'winner-0':120})
        self.assertEqual(result['surplus'],17)
        mutations = [
            ('duplicate', lambda f: f['events'].append(copy.deepcopy(f['events'][0])), 'duplicate'),
            ('missing award', lambda f: f['events'].pop(2), 'locked\\[1\\]'),
            ('bad block', lambda f: f['events'][0].update(block_number=999), 'block_number'),
            ('bad hash', lambda f: f['events'][0].update(block_hash='0x'+'f'*64), 'block_hash'),
            ('snapshot', lambda f: f['snapshot'].update(token_balance=1), 'token_balance'),
            ('negative', lambda f: f['events'][2]['args'].update(amount=-1), 'uint'),
            ('float', lambda f: f['events'][2]['args'].update(amount=120.0), 'uint'),
            ('unauthorized', lambda f: f['events'][2].update(actor='attacker-0'), 'unauthorized'),
            ('extra', lambda f: f['events'][0].update(extra=True), 'fields'),
        ]
        for name, mutate, expected in mutations:
            with self.subTest(name=name):
                f=copy.deepcopy(fixture); mutate(f)
                with self.assertRaisesRegex(Failure, expected): reconcile(f, abi)

if __name__ == '__main__':
    unittest.main()
