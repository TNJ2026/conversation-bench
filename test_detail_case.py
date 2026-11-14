"""Receipt probes must require previously supplied, non-periodic facts."""
import json
import re
import unittest
from pathlib import Path
import longcase
import longrun


class DetailCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case=json.loads(longcase.DETAIL_CASE.read_text())

    def test_saved_case_is_reproducible_from_its_operator_only_seed(self):
        self.assertEqual(self.case,longcase.build_detail_case(self.case['generation']['private_seed']))
        prompts='\n'.join(t['prompt'] for t in self.case['seed_turns']+self.case['pressure_turns']+self.case['probes'])
        self.assertNotIn(self.case['generation']['private_seed'],prompts)

    def test_receipts_are_unique_and_not_recoverable_from_later_modulo_groups(self):
        lines='\n'.join(t['prompt'] for t in self.case['pressure_turns'])
        receipts=re.findall(r'回执码：([0-9a-f]{16})。',lines)
        self.assertEqual(len(receipts),384)
        self.assertEqual(len(set(receipts)),384)
        last=self.case['pressure_turns'][-1]['prompt']
        lookup={}
        for number,receipt in re.findall(r'工单 QL-(\d+)｜[^\n]*回执码：([0-9a-f]{16})。',last):
            lookup[(int(number)-1)%8]=receipt
        self.assertTrue(all(lookup[(number-1)%8]!=self.case['expected'][f'f{i}']
                            for i,number in enumerate(longcase.PROBE_TICKETS,1)))
        # The final ticket remains an explicit uncompressed-tail control, not a leak of earlier values.
        for anchor,spec in self.case['probe_anchors'].items():
            if spec['source_turn']!='load-12':self.assertNotIn(self.case['expected'][anchor],last)

    def test_changing_the_private_seed_changes_early_answers(self):
        other=longcase.build_detail_case('ab'*32)
        self.assertTrue(all(self.case['expected'][a]!=other['expected'][a] for a in self.case['expected']))

    def test_probe_sources_and_minimum_load_are_enforced(self):
        self.assertEqual(len(self.case['probe_anchors']),10)
        self.assertEqual(longrun.allowed_grades(self.case),('correct','unknown','wrong'))
        for size in (1,11):
            with self.assertRaisesRegex(ValueError,'more load'):
                longrun.validate_prefix(self.case,self.case['seed_turns']+self.case['pressure_turns'][:size])
        longrun.validate_prefix(self.case,self.case['seed_turns']+self.case['pressure_turns'])
        changed=json.loads(json.dumps(self.case));changed['expected']['f1']='0'*16
        with self.assertRaisesRegex(ValueError,'absent'):
            longrun.validate_prefix(changed,changed['seed_turns']+changed['pressure_turns'])

    def test_legacy_v6_cannot_start_new_runs_but_its_rubric_still_rejects_partial(self):
        legacy=json.loads(Path('cases/long-context-compaction-qinglu-v6.json').read_text())
        self.assertNotIn('partial',longrun.allowed_grades(legacy))
        with self.assertRaisesRegex(ValueError,'deprecated'):
            longrun.validate_prefix(legacy,legacy['seed_turns']+legacy['pressure_turns'])


if __name__=='__main__':unittest.main()
