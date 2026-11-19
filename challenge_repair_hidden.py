"""Evaluator-only tests. Run with submitted code inside an isolated review environment."""
import copy
import io
import unittest

from allocation import read_receipts, replay


class ReceiptReplayChecks(unittest.TestCase):
    def test_exact_retry_with_opening_balance(self):
        a = dict(receipt='R17', order='A', sku='pen', quantity=4)
        initial = {('A', 'pen'): 11, ('B', 'clip'): 2}
        rows = [a, dict(a)]
        saved = copy.deepcopy(rows)
        self.assertEqual(replay(initial, rows), {('A', 'pen'): 15, ('B', 'clip'): 2})
        self.assertEqual(initial, {('A', 'pen'): 11, ('B', 'clip'): 2})
        self.assertEqual(rows, saved)

    def test_same_quantity_is_not_identity(self):
        rows = read_receipts(io.StringIO('receipt,order,sku,quantity\nr,A,pen,3\ns,A,pen,3\nr,A,clip,3\nr,B,pen,3\n'))
        self.assertEqual(replay({}, rows), {('A', 'pen'): 6, ('A', 'clip'): 3, ('B', 'pen'): 3})

    def test_conflicting_quantity_fails(self):
        a = dict(receipt='R', order='A', sku='pen', quantity=4)
        with self.assertRaises(ValueError):
            replay({}, [a, dict(a, quantity=5)])

    def test_non_adjacent_retry_counts_once(self):
        # The incident batch replays R7 after R8; a fix that only compares neighbours misses it.
        rows = read_receipts(io.StringIO('receipt,order,sku,quantity\nR7,A1,pen,3\nR8,A1,pen,3\nR7,A1,pen,3\n'))
        self.assertEqual(replay({('A1', 'pen'): 1}, rows), {('A1', 'pen'): 7})

    def test_non_adjacent_conflict_fails(self):
        a = dict(receipt='R', order='A', sku='pen', quantity=4)
        other = dict(receipt='S', order='A', sku='pen', quantity=4)
        with self.assertRaises(ValueError):
            replay({}, [a, other, dict(a, quantity=5)])

    def test_dedupe_state_does_not_leak_between_calls(self):
        rows = [dict(receipt='r', order='A', sku='pen', quantity=2)] * 2
        self.assertEqual(replay({}, rows), {('A', 'pen'): 2})
        self.assertEqual(replay({}, rows), {('A', 'pen'): 2})


if __name__ == '__main__':
    unittest.main()
