"""Task acceptance must measure delivery, not just an average of fact scores."""
import copy
import json
import unittest

import longrun
import taskcase


class TaskCaseTests(unittest.TestCase):
    def test_fixed_revision_preserves_material_but_disambiguates_both_probes(self):
        old=taskcase.build_task_case()
        fixed=json.loads(taskcase.FIXED_CASE.read_text())
        self.assertEqual(fixed,taskcase.build_fixed_task_case())
        self.assertEqual(old['seed_turns'],fixed['seed_turns'])
        self.assertEqual(old['pressure_turns'],fixed['pressure_turns'])
        self.assertEqual(old['expected'],fixed['expected'])
        longrun.validate_prefix(fixed,fixed['seed_turns']+fixed['pressure_turns'])
        for probe in fixed['probes']:
            self.assertIn('实际16位码',probe['prompt'])
            self.assertIn('保留原文大小写',probe['prompt'])
            self.assertIn('无法确认',probe['prompt'])
            self.assertIn('括号',probe['prompt'])
            self.assertIn('示例',probe['prompt'])
            self.assertIn('回执码为',probe['prompt'])
            self.assertNotIn('回执码写成“QL-E017：回执码”',probe['prompt'])
            self.assertNotIn(taskcase.RECEIPT,probe['prompt'])

    def test_receipt_content_survives_presentation_changes_without_loosening_association(self):
        spec=taskcase.build_fixed_task_case()['probe_anchors']['receipt']
        code=taskcase.RECEIPT
        for answer in (f'QL-E017：{code}',f'QL-E017: {code}',
                       f'**QL-E017：回执码 {code}**',f'QL-E017：回执码：`{code}`',
                       f'- **QL-E017**：`{code}`（来源：原始用户凭据）',
                       f'QL-E017：回执码为 {code}',f'QL-E017：回执码是 {code}',
                       f'QL-E017：回执码 *{code}*',f'QL-E017：回执码 _{code}_',
                       f'QL-E017：回执码（{code}）',f'QL-E017：回执码[{code}]',
                       f'QL-E017：回执码【{code}】',f'按格式：QL-E017：{code}'):
            with self.subTest(answer=answer):
                self.assertTrue(longrun.receipt_pair_matches(spec,code,answer))
        for answer in ('QL-E017：回执码','QL-E017：<回执码原文>','QL-E017：无法确认',
                       f'QL-E018：{code}',f'QL-E017：\n{code}',f'其他内容 {code}',
                       f'XQL-E017：{code}',f'QL-E0170：{code}',f'QL-E017：{code}0',
                       'QL-E017：0000000000000000',
                       f'QL-E017：{code}\nQL-E017：0000000000000000',
                       f'QL-E017：{code.upper()}',
                       f'QL-E017：{code}_',
                       f'回答：无法确认（格式示例：QL-E017：{code}）',
                       f'例如 QL-E017：{code}',f'引用：QL-E017：{code}'):
            with self.subTest(answer=answer):
                self.assertFalse(longrun.receipt_pair_matches(spec,code,answer))
        # An example line is ignored; a correct answer elsewhere still counts.
        self.assertTrue(longrun.receipt_pair_matches(
            spec,code,f'示例：QL-E017：0000000000000000\nQL-E017：{code}'))
        legacy=taskcase.build_task_case()['probe_anchors']['receipt']
        self.assertFalse(longrun.receipt_pair_matches(legacy,code,f'QL-E017：回执码 {code}'))
        self.assertTrue(longrun.receipt_pair_matches(legacy,code,f'QL-E017：{code}'))

    def test_formatting_does_not_repair_corrupted_identifiers_or_receipts(self):
        spec=taskcase.build_fixed_task_case()['probe_anchors']['receipt']
        code=taskcase.RECEIPT
        for char in ('_','*','`','**','__'):
            for answer in (f'QL-E017：{code[:8]}{char}{code[8:]}',
                           f'QL-E017：{code[:4]}{char}{code[4:8]}{char}{code[8:]}',
                           f'QL-E0{char}17：{code}'):
                with self.subTest(answer=answer):
                    self.assertFalse(longrun.receipt_pair_matches(spec,code,answer))
        for marker in ('*','**','_','__','`','``'):
            self.assertTrue(longrun.receipt_pair_matches(
                spec,code,f'{marker}QL-E017{marker}：{marker}{code}{marker}'))

    def test_all_actual_values_are_checked_even_when_malformed(self):
        spec=taskcase.build_fixed_task_case()['probe_anchors']['receipt']
        code=taskcase.RECEIPT
        for wrong in ('0'*15,'0'*17,'xyz','无法确认','回执码','<回执码原文>',
                      code[:8]+'_'+code[8:],f'（{code}0）'):
            for separator in ('\n','；'):
                answer=f'QL-E017：{code}{separator}QL-E017：{wrong}'
                with self.subTest(answer=answer):
                    self.assertFalse(longrun.receipt_pair_matches(spec,code,answer))

    def test_multiline_examples_cannot_supply_an_actual_answer(self):
        spec=taskcase.build_fixed_task_case()['probe_anchors']['receipt']
        code=taskcase.RECEIPT
        for heading in ('示例：','### 示例','例如：','比如：','引用：','Example:'):
            for content in (f'QL-E017：{code}',f'\nQL-E017：{code}\n',
                            f'```text\nQL-E017：{code}\n```'):
                answer=f'{heading}\n{content}\n实际答案：无法确认'
                with self.subTest(answer=answer):
                    self.assertFalse(longrun.receipt_pair_matches(spec,code,answer))
        self.assertFalse(longrun.receipt_pair_matches(spec,code,f'> QL-E017：{code}'))
        self.assertTrue(longrun.receipt_pair_matches(
            spec,code,f'示例：\nQL-E017：00000000000000000\n\n实际答案：\nQL-E017：{code}'))

    def test_negative_reference_does_not_open_example_block(self):
        spec=taskcase.build_fixed_task_case()['probe_anchors']['receipt']
        code=taskcase.RECEIPT
        self.assertEqual(longrun.RECEIPT_MATCHER_VERSION,'labelled-receipt-line-v1.1')
        self.assertTrue(longrun.receipt_pair_matches(
            spec,code,f'本轮结论不引用任何文件；以下为核对结果。\nQL-E017：{code}'))
        self.assertFalse(longrun.receipt_pair_matches(
            spec,code,f'引用：\nQL-E017：{code}\n实际答案：无法确认'))
        self.assertTrue(longrun.receipt_pair_matches(spec,code,f'QL-E017：{code}'))

    def test_unknown_match_mode_is_rejected_before_run(self):
        case=taskcase.build_fixed_task_case()
        case['probe_anchors']['receipt']['match_mode']='typo'
        with self.assertRaisesRegex(ValueError,'Unsupported receipt'):
            longrun.validate_prefix(case,case['seed_turns']+case['pressure_turns'])

    def test_saved_material_matches_builder_and_sources_are_admitted(self):
        case=json.loads(taskcase.CASE.read_text())
        self.assertEqual(case,taskcase.build_task_case())
        longrun.validate_prefix(case,case['seed_turns']+case['pressure_turns'])
        with self.assertRaisesRegex(ValueError,'more load'):
            longrun.validate_prefix(case,case['seed_turns']+case['pressure_turns'][:1])
        prompts='\n'.join(t['prompt'] for t in case['seed_turns']+case['pressure_turns'])
        self.assertEqual(prompts.count(taskcase.RECEIPT),1)
        self.assertNotIn(taskcase.RECEIPT,case['probes'][0]['prompt'])
        self.assertNotIn(taskcase.RECEIPT,case['probes'][1]['prompt'])

    def test_missing_or_duplicate_criteria_cannot_silently_raise_success(self):
        case=taskcase.build_task_case()
        for mutation in ('missing','duplicate'):
            other=copy.deepcopy(case)
            if mutation=='missing':other['task_groups']['current_decisions'].remove('budget')
            else:other['task_groups']['next_actions'].append('budget')
            with self.assertRaisesRegex(ValueError,'partition'):
                longrun.validate_prefix(other,other['seed_turns']+other['pressure_turns'])

    def test_unknown_and_wrong_both_prevent_full_delivery(self):
        case=taskcase.build_task_case()
        marks={a:{'grade':'correct'} for a in case['expected']}
        self.assertTrue(longrun.task_outcomes(case,marks,True)['full_delivery_success'])
        for value in ('unknown','wrong'):
            marks['authority']['grade']=value
            out=longrun.task_outcomes(case,marks,True)
            self.assertFalse(out['full_delivery_success'])
            self.assertFalse(out['task_passes']['next_actions'])
            self.assertEqual(out['tasks_completed'],2)


if __name__=='__main__':unittest.main()
