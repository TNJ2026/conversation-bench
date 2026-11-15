"""Admission and comparison integrity for fresh layout/version transfer cases."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import longcase
import longrun
import transfercase


class TransferCaseTests(unittest.TestCase):
    def test_three_saved_instances_are_reproducible_and_hide_the_operator_seed(self):
        fingerprints=set()
        for p in sorted((transfercase.CASE_DIR/'transfer-v9').glob('case-*.json')):
            c=json.loads(p.read_text());seed=c['generation']['private_seed']
            self.assertEqual(c,transfercase.build_case(seed))
            longrun.validate_prefix(c,c['seed_turns']+c['pressure_turns'])
            self.assertEqual(len(c['expected']),13)
            self.assertEqual(len(c['probe_anchors']),10)
            prompts='\n'.join(t['prompt'] for t in c['seed_turns']+c['pressure_turns']+c['probes'])
            self.assertNotIn(seed,prompts)
            fingerprints.add(longrun.digest(c))
        self.assertEqual(len(fingerprints),3)

    def test_layout_and_repeated_hit_challenges_require_original_sources(self):
        c=transfercase.build_case('7a'*32)
        q=c['probe_anchors']
        self.assertIn('\n',q['f1']['source_quote'])
        self.assertIn('NEIGHBOR-A',q['f2']['source_quote'])
        self.assertIn('NEIGHBOR-C',q['f2']['source_quote'])
        self.assertGreater(len(q['f4']['source_quote']),1000)
        self.assertEqual(sum(q['f5']['ticket'] in t['prompt'] for t in c['pressure_turns']),12)
        self.assertEqual(q['f5']['source_turn'],'load-12')
        self.assertIn('Ω',q['f6']['ticket'])
        for a,spec in q.items():
            # Only the signed source contains the final code; no later tail can infer it.
            self.assertEqual(sum(c['expected'][a] in t['prompt'] for t in c['pressure_turns']),1)
            answer=spec['ticket']+'：'+c['expected'][a]
            self.assertTrue(longrun.receipt_pair_matches(spec,c['expected'][a],answer))
        other=transfercase.build_case('7b'*32)
        self.assertTrue(all(c['expected'][a]!=other['expected'][a] for a in q))

    def test_missing_or_edited_source_and_short_load_are_rejected(self):
        c=transfercase.build_case('7a'*32)
        for replacement in ('not in the admitted prompt',''):
            other=copy.deepcopy(c);other['probe_anchors']['f1']['source_quote']=replacement
            with self.assertRaisesRegex(ValueError,'verbatim probe'):
                longrun.validate_prefix(other,other['seed_turns']+other['pressure_turns'])
        other=copy.deepcopy(c);other['expected']['f1']='0'*16
        with self.assertRaisesRegex(ValueError,'verbatim probe'):
            longrun.validate_prefix(other,other['seed_turns']+other['pressure_turns'])
        with self.assertRaisesRegex(ValueError,'more load'):
            longrun.validate_prefix(c,c['seed_turns']+c['pressure_turns'][:11])
        with self.assertRaisesRegex(ValueError,'freeze exactly'):
            longcase.extra_batches(c,1,13)

    def prepare(self,root):
        paths=[transfercase.CASE_DIR/'transfer-v9'/f'case-{n}.json' for n in (1,2,3)]
        with patch.object(longrun,'__file__',str(root/'project'/'longrun.py')),contextlib.redirect_stdout(io.StringIO()):
            return transfercase.prepare_comparison(root/'comparison',paths,73)

    def test_preparation_freezes_paired_materials_and_both_plugin_versions_without_running(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(longrun,'run') as run:
            path=self.prepare(Path(temp));schedule=longrun.load(path)
            self.assertEqual(len(schedule['jobs']),6);run.assert_not_called()
            for pair in (1,2,3):
                jobs=[j for j in schedule['jobs'] if j['pair']==pair]
                self.assertEqual({j['plugin_version'] for j in jobs},{'0.1.0','0.1.1'})
                self.assertEqual(len({j['case_hash'] for j in jobs}),1)
                for j in jobs:
                    state=longrun.load(j['record']);self.assertEqual(state['status'],'ready')
                    self.assertEqual(state['config']['history_plugin']['version'],j['plugin_version'])
            self.assertEqual(len({j['case_hash'] for j in schedule['jobs']}),3)

    def test_suite_resumes_only_completed_jobs_and_stops_for_uncertain_outcomes(self):
        with tempfile.TemporaryDirectory() as temp:
            path=self.prepare(Path(temp));jobs=longrun.load(path)['jobs'];seen=[]
            state=longrun.load(jobs[0]['record']);state['status']='completed';longrun.save(Path(jobs[0]['record']),state)
            def run(record):
                seen.append(str(record));s=longrun.load(record);s['status']='completed';longrun.save(record,s)
            with patch.object(longrun,'run',side_effect=run):transfercase.run_comparison(path)
            self.assertEqual(seen,[j['record'] for j in jobs[1:]])
            state=longrun.load(jobs[-1]['record']);state['status']='attention';state['pending']={'action':'unknown'}
            longrun.save(Path(jobs[-1]['record']),state)
            with patch.object(longrun,'run') as run:
                with self.assertRaisesRegex(ValueError,'investigation'):transfercase.run_comparison(path)
                run.assert_not_called()

    def test_changed_config_is_rejected_before_any_target_run(self):
        with tempfile.TemporaryDirectory() as temp:
            path=self.prepare(Path(temp));jobs=longrun.load(path)['jobs'];record=Path(jobs[-1]['record'])
            state=longrun.load(record);state['config']['effort']='high';longrun.save(record,state)
            with patch.object(longrun,'run') as run:
                with self.assertRaisesRegex(ValueError,'inputs changed'):transfercase.run_comparison(path)
                run.assert_not_called()

    def test_changed_runner_is_rejected_before_any_target_run(self):
        with tempfile.TemporaryDirectory() as temp:
            path=self.prepare(Path(temp));schedule=longrun.load(path)
            key=next(iter(schedule['runner_files_sha256']))
            schedule['runner_files_sha256'][key]='0'*64;longrun.save(path,schedule)
            with patch.object(longrun,'run') as run:
                with self.assertRaisesRegex(ValueError,'runner changed'):transfercase.run_comparison(path)
                run.assert_not_called()


if __name__=='__main__':unittest.main()
