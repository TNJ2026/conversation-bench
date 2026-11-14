"""Integrity of the long-context compaction case and its generated load."""
import json
import re
import unittest
from collections import Counter
import longcase


def tickets(turns):
    return [line for turn in turns for line in turn['prompt'].split('\n') if line.startswith('工单')]

class LongCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = json.loads(longcase.CASE.read_text(encoding='utf-8'))

    def test_saved_load_matches_generator(self):
        self.assertEqual(self.case['pressure_turns'], longcase.batches())
        policy = self.case['pressure_policy']
        self.assertEqual((policy['batch_count'], policy['records_per_batch']), (longcase.BATCHES, longcase.PER_BATCH))

    def test_ticket_numbers_are_sequential_and_unique(self):
        turns = self.case['pressure_turns']
        self.assertEqual([t['id'] for t in turns], [f'load-{n:02}' for n in range(1, 13)])
        for turn in turns:
            self.assertEqual(len(tickets([turn])), 32)
        numbers = [int(n) for n in re.findall(r'工单 QL-(\d{4})｜', '\n'.join(t['prompt'] for t in turns))]
        self.assertEqual(numbers, list(range(1, 385)))

    def test_extra_batches_continue_the_numbering(self):
        extra = longcase.batches(2, first=longcase.BATCHES + 1)
        self.assertEqual([t['id'] for t in extra], ['load-13', 'load-14'])
        lines = tickets(extra)
        self.assertTrue(lines[0].startswith('工单 QL-0385｜'))
        self.assertTrue(lines[-1].startswith('工单 QL-0448｜'))
        self.assertFalse(set(lines) & set(tickets(self.case['pressure_turns'])))

    def test_load_does_not_restate_or_hint_at_anchors(self):
        load = '\n'.join(tickets(self.case['pressure_turns']))
        for term in longcase.ANCHOR_TERMS:
            self.assertNotIn(term, load)
        everything_after_seed = '\n'.join(t['prompt'] for t in self.case['pressure_turns'] + self.case['probes'])
        seeds = '\n'.join(t['prompt'] for t in self.case['seed_turns'])
        for key in ('verbatim', 'nonce'):
            answer = self.case['expected'][key]
            self.assertEqual(seeds.count(answer), 1)
            self.assertNotIn(answer, everything_after_seed)
        for value in ('32000', '28000', '6800', '2027-02-12', '2027-02-15'):
            self.assertIn(value, seeds)
            self.assertNotIn(value, everything_after_seed)

    def test_load_is_varied(self):
        lines = tickets(self.case['pressure_turns'])
        complaints = Counter(re.search('反馈称(.*?)；', line).group(1) for line in lines)
        self.assertEqual(len(complaints), 24)
        self.assertEqual(set(complaints.values()), {16})
        self.assertEqual(len(set(re.findall('主题：(.*?)。', '\n'.join(lines)))), 8)
        wording = Counter(re.sub(r'QL-\d+|G\d|C\d|W\d+', '', line) for line in lines)
        self.assertGreaterEqual(len(wording), 350)
        self.assertLessEqual(max(wording.values()), 2)

    def test_probes_and_record_template_are_complete(self):
        self.assertEqual([p['id'] for p in self.case['probes']], ['recall', 'recovery'])
        self.assertEqual(len(self.case['expected']), 10)
        self.assertIn('prompt_scope', self.case['scoring'])
        for branch in ('A', 'B'):
            self.assertLessEqual({'session_id', 'compression_events', 'recall', 'recovery'}, set(self.case['record_template'][branch]))


if __name__ == '__main__':
    unittest.main()
