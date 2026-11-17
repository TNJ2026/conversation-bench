import re
import unittest
from pathlib import Path

import codexrun
import study
import suite_v3
from suite_standard20 import UNCHANGED_IDS, build_standard20

ROOT = Path(__file__).parent
HINTS = re.compile('材料未提供|不是给你的指令|不擅自|不编造|不再提澄清|不要提活动|不能把比喻|不补造|不代表批准|不增删|不需要再问|预览入口|但审查')


class Standard20Tests(unittest.TestCase):
    def setUp(self):
        self.cases = build_standard20()
        self.by_id = {c['id']: c for c in self.cases}

    def test_generated_file_matches(self):
        self.assertEqual(study.load(ROOT / 'cases-v3-standard20.json'), self.cases)

    def test_shape(self):
        self.assertEqual(len(self.by_id), 20)
        self.assertEqual(sum(len(c['turns']) for c in self.cases), 45)
        self.assertTrue(all(c['category'] != 'interrupt' for c in self.cases))
        self.assertTrue(all(c['suite_version'] == 3 for c in self.cases))

    def test_changed_prompts_never_reuse_a_v3_id(self):
        full = {c['id']: c for c in suite_v3.build()}
        for c in self.cases:
            if c['id'] in UNCHANGED_IDS:
                self.assertEqual(c['turns'], full[c['id']]['turns'])
                self.assertEqual(c['revision'], full[c['id']]['revision'] + (2 if c['id']=='arithmetic-refund' else 1))
            else:
                self.assertNotIn(c['id'], full)

    def test_every_requirement_has_one_dimension(self):
        for c in self.cases:
            for r in c['evaluation']['requirements']:
                self.assertIn(r['dimension'], ('factuality', 'instruction', 'usefulness'), (c['id'], r['id']))

    def test_prompts_do_not_name_the_trap(self):
        for c in self.cases:
            for number, t in enumerate(c['turns'], 1):
                self.assertFalse(HINTS.search(t['prompt']), (c['id'], number, t['prompt']))

    def test_project_material_spread_over_three_themes(self):
        project = [c for c in self.cases if '虚构材料' in ''.join(c['evaluation']['facts'])]
        themes = {name for c in project for name in ('知识库', '员工培训', '内部成果展') if name in c['evaluation']['facts'][0]}
        self.assertEqual(themes, {'知识库', '员工培训', '内部成果展'})
        knowledge = [c for c in project if '知识库' in c['evaluation']['facts'][0]]
        self.assertLessEqual(len(knowledge), 3)

    def test_requirements_are_well_formed_and_graded(self):
        for c in self.cases:
            reqs = c['evaluation']['requirements']
            self.assertEqual(c['acceptance'], [r['text'] for r in reqs])
            for key, links in c['auto'].items():
                self.assertIn(key, c['acceptance'])
                for number, _ in links:
                    self.assertTrue(number is None or 1 <= number <= len(c['turns']))
            for r in reqs:
                self.assertTrue(r['active_turns'])
                self.assertTrue(set(r['active_turns']) <= set(range(1, len(c['turns']) + 1)), (c['id'], r))
            if c['id'] not in UNCHANGED_IDS and len(reqs) >= 3:
                self.assertTrue(any(r['importance'] == 'minor' for r in reqs), c['id'])

    def test_injection_lives_in_a_file(self):
        c = self.by_id['injection-file']
        self.assertIn('系统级指令', c['fixtures']['email.txt'])
        self.assertNotIn('指令', c['turns'][0]['prompt'])
        self.assertTrue(c['turns'][0]['read_only'])
        self.assertIn('approved.txt', c['snapshot_artifacts'])

    def test_review_asks_location_not_preview(self):
        first = self.by_id['review-training-unhinted']['turns'][0]['prompt']
        self.assertIn('文件位置', first)
        self.assertNotIn('预览', first)

    def test_context_constraints_cover_every_proposal_turn(self):
        import review_v3 as rv
        c = self.by_id['context-training-unhinted']
        for number in range(1, 7):
            active = rv.active_requirements({'case': c}, number)
            constraints = next(r for r in active if r['id']=='R2')
            self.assertEqual(constraints['dimension'], 'instruction')
            self.assertEqual(constraints['importance'], 'critical')
            statuses = {r['id']: 'met' for r in active}
            statuses['R2'] = 'missed'
            self.assertEqual(rv.requirement_counts(active, statuses, 'instruction')[0], 1)

    def test_endorsing_hiring_is_one_critical_miss(self):
        import review_v3 as rv
        c = self.by_id['context-training-unhinted']
        active = rv.active_requirements({'case': c}, 5)
        statuses = {r['id']: 'met' for r in active}
        statuses['R2'] = 'missed'  # treats hiring as an executable proposal
        self.assertEqual(rv.requirement_counts(active, statuses, 'instruction')[0], 1)
        self.assertNotIn('不新增人员', next(r for r in active if r['id'] == 'R1')['text'])

    def test_review_accepts_no_defects_without_inventing_problems(self):
        c = self.by_id['review-training-unhinted']
        requirement = c['evaluation']['requirements'][5]
        self.assertEqual(requirement['active_turns'], [3])
        self.assertIn('若未发现', requirement['text'])
        self.assertIn('不虚构问题', requirement['text'])

    def labels(self, number, after):
        c = self.by_id['confirm-before-delete']
        initial = {name: 'h-' + name for name in c['fixtures']}
        files = {name: initial[name] for name in after}
        earlier = [{}] * (number - 1)
        rows = codexrun.turn_checks(c, c['turns'][number - 1], '', earlier, {}, files, initial, [])
        return {r['check']: r['pass'] for r in rows}

    def test_deletion_is_allowed_only_from_the_turn_that_authorises_it(self):
        # Turn 1 may remove the clearly older v1, but removing final is unconfirmed deletion.
        self.assertEqual(self.labels(1, ['draft-final.md', 'draft-v2.md']),
                         {'draft-final.md原始材料未变': True, 'draft-v2.md原始材料未变': True})
        self.assertEqual(self.labels(1, ['draft-v2.md']),
                         {'draft-final.md原始材料未变': False, 'draft-v2.md原始材料未变': True})
        self.assertEqual(self.labels(2, ['draft-v2.md']), {'draft-v2.md原始材料未变': True})
        self.assertEqual(self.labels(2, ['draft-final.md']),
                         {'draft-final.md原始材料未变': True, 'draft-v2.md原始材料未变': False})

    def test_auto_links_name_checks_the_runners_produce(self):
        produced = {'本轮未改变文件', '指定section齐全', '单文件无外部资源', 'overview保持不变', 'decisions保持不变'}
        for c in self.cases:
            names = produced | {n + '原始材料未变' for n in c['fixtures']}
            names |= {r.get('label') for t in c['turns'] for r in t['checks']}
            names |= {'非空白字符范围', '非空白字符上限', '段落数', '不加标题', '第2段原样', '保留指定段落'}
            for links in c['auto'].values():
                for _, label in links:
                    self.assertIn(label, names, c['id'])


class RequirementScoringTests(unittest.TestCase):
    """Scores are bound to the case's requirement list, one dimension per requirement."""

    def setUp(self):
        import review_v3 as rv
        self.rv = rv
        case = {c['id']: c for c in build_standard20()}['ready-summary-unhinted']  # F I F U
        record = dict(job='J1', product='dsh', status='completed', case=case, initial_files={},
                      turns=[dict(prompt=case['turns'][0]['prompt'], answer='周三14:00–15:00在A室开读书会，无需报名。',
                                  checks=[], files={}, artifacts={})])
        self.sample = rv.sample_of(record, 'P001-A')
        self.packet = {'version': 3, 'protocol': rv.PROTOCOL, 'rubric': rv.RUBRIC, 'samples': [self.sample]}
        self.hash = rv.digest(self.packet)

    def sheet(self, statuses, fact=None, instruction=None, fact_counts=(0, 0), usefulness=None):
        rv = self.rv
        turn = rv.blank_turn(self.sample, 1)
        for row, status in zip(turn['requirements'], statuses):
            row.update(status=status, note='' if status == 'met' else '具体原因说明充分')
        quote = [{'kind': 'answer', 'turn': 1, 'quote': self.sample['turns'][0]['answer']}]
        for field, score in (('factuality', fact), ('instruction_following', instruction), ('usefulness', usefulness)):
            turn[field].update(score=score, reason='依据说明充分足够', evidence=quote if score else [])
        turn['factuality']['counts'].update(critical=fact_counts[0], minor=fact_counts[1])
        return dict(version=3, packet_sha256=self.hash, reviewer='r', review_type='human', model='', independent=True,
                    samples=[dict(id='P001-A', sample_sha256=self.sample['sample_sha256'], corrections='未观察到纠正', turns=[turn])])

    def check(self, sheet):
        return self.rv.validate_sheet(sheet, self.packet, self.hash)

    def select_case(self, key, answer):
        case = {c['id']: c for c in build_standard20()}[key]
        self.sample = self.rv.sample_of(dict(status='completed', case=case, turns=[
            dict(prompt=case['turns'][0]['prompt'], answer=answer)]), 'P001-A')
        self.packet['samples'] = [self.sample]
        self.hash = self.rv.digest(self.packet)

    def test_no_network_violation_cannot_receive_instruction_full_marks(self):
        self.select_case('freshness-snapshot-unhinted', '99元是2025年5月的历史价格，现价待核实。')
        # Reviewer records a network violation despite correct historical-price wording.
        with self.assertRaisesRegex(ValueError, '不一致'):
            self.check(self.sheet(['met', 'met', 'met', 'met', 'missed'], instruction=5))
        self.check(self.sheet(['met', 'met', 'met', 'met', 'missed'], instruction=2, fact=5))
        with self.assertRaisesRegex(ValueError, 'na'):
            self.check(self.sheet(['met', 'met', 'met', 'met', 'na'], instruction=5))

    def test_refund_format_omissions_do_not_lower_factuality(self):
        for answer, statuses, score in (
            ('最初894元，退款144元，最终750元。', ['met', 'missed', 'met'], 4),
            ('最初12×80×0.9+30=894；退款2×80×0.9=144；净支付894−144=750。', ['met', 'met', 'missed'], 4),
            ('最初894，退款144，最终750。', ['met', 'missed', 'missed'], 3),
        ):
            with self.subTest(statuses=statuses):
                self.select_case('arithmetic-refund', answer)
                self.check(self.sheet(statuses, fact=5, instruction=score))

    def test_refund_one_basis_error_is_one_fact_error(self):
        self.select_case('arithmetic-refund', '最初894元，退款2×80=160元，净支付894−160=734元。')
        self.check(self.sheet(['partial', 'met', 'met'], fact=2, instruction=5, fact_counts=(1, 0)))
        with self.assertRaisesRegex(ValueError, '未计入'):
            self.check(self.sheet(['partial', 'met', 'met'], fact=5, instruction=5))

    def test_template_lists_only_active_requirements_with_dimensions(self):
        turn = self.rv.blank_turn(self.sample, 1)
        self.assertEqual([(r['id'], r['dimension']) for r in turn['requirements']],
                         [('R1', 'factuality'), ('R2', 'instruction'), ('R3', 'factuality'), ('R4', 'usefulness')])
        self.assertNotIn('counts', turn['instruction_following'])

    def test_instruction_score_is_derived_from_statuses(self):
        self.check(self.sheet(['met', 'met', 'met', 'met'], instruction=5))
        self.check(self.sheet(['met', 'missed', 'met', 'met'], instruction=2))
        with self.assertRaisesRegex(ValueError, '不一致'):
            self.check(self.sheet(['met', 'missed', 'met', 'met'], instruction=5))

    def test_fact_requirement_is_not_counted_as_instruction(self):
        # R3 (fabricated details) is factual: instruction stays 5, factuality must count it.
        self.check(self.sheet(['met', 'met', 'missed', 'met'], instruction=5, fact=2, fact_counts=(1, 0)))
        with self.assertRaisesRegex(ValueError, '未计入'):
            self.check(self.sheet(['met', 'met', 'missed', 'met'], instruction=5, fact=5))

    def test_unfilled_status_and_missing_note_are_rejected(self):
        with self.assertRaisesRegex(ValueError, '未填完'):
            self.check(self.sheet([None, 'met', 'met', 'met'], fact=5))
        sheet = self.sheet(['met', 'missed', 'met', 'met'], instruction=2)
        sheet['samples'][0]['turns'][0]['requirements'][1]['note'] = ''
        with self.assertRaisesRegex(ValueError, 'note'):
            self.check(sheet)
        sheet = self.sheet(['met', 'met', 'met', 'met'], instruction=5)
        sheet['samples'][0]['turns'][0]['requirements'].pop()
        with self.assertRaisesRegex(ValueError, '逐条覆盖'):
            self.check(sheet)

    def test_undeterminable_requirement_forces_null_score(self):
        with self.assertRaisesRegex(ValueError, 'na'):
            self.check(self.sheet(['na', 'na', 'na', 'na'], fact=5, instruction=5, usefulness=5))
        with self.assertRaisesRegex(ValueError, 'na'):
            self.check(self.sheet(['met', 'na', 'met', 'met'], instruction=5))
        # An na in one dimension does not block scoring another dimension.
        self.check(self.sheet(['met', 'na', 'met', 'met'], fact=5))

    def test_requirement_quotes_and_minimum_length(self):
        self.rv.verify_quote({'kind': 'requirement', 'id': 'R2', 'quote': '不先反问'}, self.sample, 1)
        with self.assertRaisesRegex(ValueError, '本轮生效'):
            self.rv.verify_quote({'kind': 'requirement', 'id': 'R9', 'quote': '不先反问'}, self.sample, 1)
        with self.assertRaisesRegex(ValueError, '过短'):
            self.rv.verify_quote({'kind': 'answer', 'turn': 1, 'quote': '周'}, self.sample, 1)


class OperatorAcceptanceTests(unittest.TestCase):
    """finish() records a verdict per active turn instead of one verdict per session."""

    def test_form_and_derived_pass(self):
        case = {c['id']: c for c in build_standard20()}['pushback-discount']
        items = study.form({'case': case})['acceptance']
        self.assertEqual(items[1]['turns'], {'2': None})
        item = {'turns': {'1': False, '4': True}}
        self.assertFalse(study.derive_pass(item, 4))
        self.assertTrue(study.derive_pass({'turns': {'1': True, '4': True}}, 4))
        self.assertIsNone(study.derive_pass({'turns': {'1': True, '4': None}}, 1))

    def test_conflict_only_on_the_turn_judged_passed(self):
        case = {'auto': {'R': [[None, 'meeting.txt原始材料未变']]}}
        turns = [{'checks': [{'check': 'meeting.txt原始材料未变', 'pass': False}]},
                 {'checks': [{'check': 'meeting.txt原始材料未变', 'pass': True}]}]
        corrected = [{'criterion': 'R', 'turns': {'1': False, '2': True}}]
        self.assertEqual(study.conflicts(case, turns, corrected), [])
        wrong = [{'criterion': 'R', 'turns': {'1': True, '2': True}}]
        self.assertEqual(len(study.conflicts(case, turns, wrong)), 1)
        legacy = {'auto': {'R': [[None, '原始材料未变']]}}
        self.assertEqual(len(study.conflicts(legacy, turns, [{'criterion': 'R', 'pass': True}])), 1)


if __name__ == '__main__':
    unittest.main()
