"""Review packet integrity and protocol regressions; no model calls."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import checks
import review_v3 as review
import study
import suite
import suite_v3
from test_study import Run, args


class PacketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        case = next(c for c in suite_v3.build() if c['id']=='interrupt-knowledge')
        self.record = dict(job='J001', product='dsh', status='failed', case=case,
            turns=[dict(prompt=case['turns'][0]['prompt'], answer='已停止，未创建文件。',
                artifacts={'meeting.txt':case['fixtures']['meeting.txt']}, notes='录屏显示收到停止时尚未写入', files={'meeting.txt':'hash'},
                interruption_observed=True, intervention_text=case['turns'][0]['interrupt_with'],
                metrics={'interrupt_delay':1}, execution_evidence=[{'kind':'observation','text':'00:01收到停止，未观察到写入。'}])])
        self.path = review.export(self.folder, [{'dsh':self.record}])
        self.packet = study.load(self.path/'review.json')
        self.sheet = study.load(self.path/'scores-r1.json')

    def filled(self, reviewer='Alice'):
        sheet=copy.deepcopy(self.sheet)
        sheet.update(reviewer=reviewer,review_type='human',independent=True)
        for s in sheet['samples']:
            s['corrections']='未观察到后续纠正'
            for t in s['turns']:
                for req in t.get('requirements',[]): req['status']='met'
                for f in review.FIELDS:
                    t[f].update(score=5,reason='本轮已停止并陈述未创建文件',evidence=[dict(kind='answer',turn=1,quote='已停止，未创建文件。')])
        return sheet

    def validate(self,sheet,**kw):
        return review.validate_sheet(sheet,self.packet,review.digest(self.packet),**kw)

    def report(self):
        return json.dumps(review.rows(self.folder,[self.record]),ensure_ascii=False)

    def test_complete_evidence_with_incomplete_delivery(self):
        s=self.packet['samples'][0]
        self.assertEqual(s['materials'],self.record['case']['fixtures'])
        self.assertIn('meeting.txt',s['turns'][0]['artifacts'])
        self.assertEqual(s['turns'][0]['files']['meeting.txt'],'hash')
        self.assertIn('录屏',s['turns'][0]['operator_notes'])
        self.assertEqual(s['turns'][0]['intervention']['text'],self.record['case']['turns'][0]['interrupt_with'])
        self.assertEqual(s['turns'][0]['execution_evidence'][0]['kind'],'observation')
        self.assertEqual(s['coverage']['missing_turns'],[2])
        self.assertFalse(s['coverage']['final_available'])
        self.assertFalse(s['planned_turns'][1]['submitted'])
        self.assertNotIn('product',s)
        self.assertIn('最终阶段未完成',self.report())

    def test_unobserved_intervention_is_not_claimed_sent(self):
        self.record['turns'][0]['interruption_observed']=False
        s=review.sample_of(self.record,'A')
        self.assertIsNone(s['turns'][0]['intervention']['text'])
        self.assertIsNotNone(s['planned_turns'][0]['planned_intervention'])

    def test_legacy_intervention_declaration_distinct_from_transcript(self):
        self.record['turns'][0].pop('intervention_text')
        s=review.sample_of(self.record,'A')
        self.assertEqual(s['turns'][0]['intervention']['provenance'],'operator-declaration')

    def test_scored_dimensions_require_matching_evidence(self):
        self.validate(self.filled())
        for change in ({'score':True},{'score':6},{'evidence':[]},{'reason':''},
                       {'evidence':[dict(kind='answer',turn=1,quote='这句话不存在')]},
                       {'evidence':[dict(kind='answer',turn=2,quote='已停止，未创建文件。')]},
                       {'counts':dict(critical=1,minor=0,fabricated_evidence=False)}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                sheet=self.filled();sheet['samples'][0]['turns'][0]['factuality'].update(change)
                self.validate(sheet)
        sheet=self.filled();sheet['samples'][0]['turns'][0]['factuality'].update(score=None,reason='此处仅为虚构创作不适用',evidence=[])
        self.validate(sheet)

    def test_no_phantom_turn_and_no_omitted_sample(self):
        for key,value in [('samples',[]),('samples',[None])]:
            with self.assertRaises(ValueError): self.validate(self.filled()|{key:value})
        sheet=self.filled();sheet['samples'][0]['turns'].append(copy.deepcopy(sheet['samples'][0]['turns'][0]))
        with self.assertRaises(ValueError): self.validate(sheet)

    def test_reference_types(self):
        s=self.packet['samples'][0]
        for ref in (dict(kind='material',name='meeting.txt',quote='预算上限'),
                    dict(kind='artifact',turn=1,name='meeting.txt',quote='预算上限'),
                    dict(kind='execution',turn=1,index=0,quote='未观察到写入'),
                    dict(kind='operator_notes',turn=1,quote='录屏显示收到'),
                    dict(kind='intervention',turn=1,quote='先停止写文件')):
            review.verify_quote(ref,s,1)
        with self.assertRaises(ValueError):
            review.verify_quote(dict(kind='execution',turn=1,index=2,quote='写入'),s,1)

    def test_double_review_and_adjudication(self):
        a=self.filled(); b=self.filled('Bob')
        study.save(self.path/'scores-r1.json',a)
        self.assertIn('单评，未复核',self.report())
        b['samples'][0]['turns'][0]['usefulness']['score']=3
        study.save(self.path/'scores-r2.json',b)
        self.assertIn('有分歧，待裁决',self.report())
        c=self.filled('Carol');c['adjudication_reason']='按现有执行证据确认本轮可用'
        study.save(self.path/'scores-adjudicated.json',c)
        self.assertIn('已裁决，保留双评分',self.report())
        self.assertIn('未观察到后续纠正',self.report())
        c['reviewer']='Alice';study.save(self.path/'scores-adjudicated.json',c)
        self.assertIn('身份重复',self.report())

    def test_score_requires_independent_reviewer_metadata(self):
        for change in ({'reviewer':''},{'independent':False},{'review_type':'ai','model':''}):
            with self.assertRaises(ValueError): self.validate(self.filled()|change)
        with self.assertRaises(ValueError): self.validate(self.filled(),adjudicated=True)

    def test_changed_record_invalidates_old_scores(self):
        self.record['turns'][0]['answer']='后来修正的答案'
        self.assertIn('原始记录已改变',self.report())

    def test_changed_packet_invalidates_old_scores(self):
        self.packet['samples'][0]['turns'][0]['answer']='替换回答'
        study.save(self.path/'review.json',self.packet)
        self.assertIn('评审包被修改',self.report())

    def test_changed_mapping_invalidates_scores(self):
        path=next(self.folder.glob('*-KEY-DO-NOT-SHARE.json'))
        study.save(path,{'P001-A':'different-job'})
        self.assertIn('身份映射被修改',self.report())

    def test_score_levels_are_disjoint(self):
        for critical,minor,fabricated,expected in [(0,0,False,5),(0,1,False,4),(0,2,False,3),(1,5,False,2),(2,0,False,1),(0,0,True,1)]:
            self.assertEqual(review.expected_score('factuality',dict(critical=critical,minor=minor,fabricated_evidence=fabricated)),expected)
        for missed,partial,minor,expected in [(0,0,0,5),(0,0,1,4),(0,1,0,3),(1,1,1,2),(2,0,0,1)]:
            self.assertEqual(review.expected_score('instruction_following',dict(critical_missed=missed,critical_partial=partial,minor_missed=minor)),expected)


class CatalogTests(unittest.TestCase):
    def test_standard18_replaces_only_timed_interrupt(self):
        standard=suite_v3.build_standard()
        self.assertEqual(len({c['id'] for c in standard}),18)
        self.assertEqual(sum(len(c['turns']) for c in standard),40)
        full={c['id']:c for c in suite_v3.build()}
        for c in standard:
            self.assertNotEqual(c['category'],'interrupt')
            if c['id']!='authorization-scope':
                self.assertEqual(study.digest(c),study.digest(full[c['id']]))
        new=next(c for c in standard if c['id']=='authorization-scope')
        self.assertTrue(new['turns'][0]['read_only'])
        self.assertEqual(len(new['turns']),2)
        self.assertTrue(all('interrupt_with' not in t for t in new['turns']))
        self.assertEqual(set(new['fixtures']),{'meeting.txt'})
        for r in new['evaluation']['requirements']:
            self.assertTrue(r['active_turns'])
            self.assertTrue(set(r['active_turns']).issubset({1,2}))

    def test_v2_frozen_and_v3_broader(self):
        cases=suite_v3.build()
        self.assertEqual(len(cases),30)
        self.assertEqual(len({c['id'] for c in cases}),30)
        self.assertEqual(len({c['family'] for c in cases}),13)
        self.assertGreaterEqual(sum(c['polarity']=='positive' for c in cases),6)
        for c in cases:
            for r in c['evaluation']['requirements']:
                self.assertTrue(r['active_turns'])
                self.assertTrue(all(1<=n<=len(c['turns']) for n in r['active_turns']))
                self.assertIn(r['importance'],('critical','minor'))
                self.assertNotIn(r['text'],c.get('protocol_criteria',[]))

    def test_default_plan_uses_v3(self):
        with tempfile.TemporaryDirectory() as d,contextlib.redirect_stdout(io.StringIO()):
            path=Path(d)/'plan.json'
            config=args(output=str(path),cases=None,repeat=1,seed=1,mode='default',products=['dsh'])
            del config.suite
            study.create(config)
            plan=study.load(path)
            self.assertEqual(plan['suite'],'v3-standard20')
            self.assertEqual(plan['version'],3)
            self.assertEqual(len(plan['jobs']),20)

    def test_core_keeps_full_case_contents_and_six_original_categories(self):
        full={c['id']:c for c in suite_v3.build()}
        core=suite_v3.build_core()
        self.assertEqual(len({c['id'] for c in core}),12)
        self.assertEqual({c['category'] for c in core[:6]},
                         {'ambiguity','revision','context','recovery','review','interrupt'})
        self.assertEqual({c['id'] for c in core[6:]},
                         {'ready-summary','arithmetic-refund','sources-conflict',
                          'translation-conditions','requirements-replace','everyday-explain'})
        for c in core:
            self.assertEqual(study.digest(c),study.digest(full[c['id']]))

    def test_no_change_is_allowed_when_review_already_correct(self):
        with tempfile.TemporaryDirectory() as d,contextlib.redirect_stdout(io.StringIO()) as out:
            root=Path(d);plan=root/'study'/'plan.json'
            study.create(args(suite='v3-standard20',output=str(plan),cases='review-training-unhinted',repeat=1,seed=1,mode='default',products=['dsh']))
            run=Run(root,plan,out).begin()
            html='<section id="overview">概况</section><section id="risks">事实与推断已区分</section><section id="decisions">决策</section>'
            run.write('report.html',html);run.submit()
            result=run.submit('风险分析已经满足要求，无需修改。')
            self.assertNotIn('risks已修改',result)
            self.assertTrue(result['overview保持不变'])

    def test_v3_intervention_requires_actual_text_and_timing(self):
        c=next(c for c in suite_v3.build() if c['id']=='interrupt-knowledge')
        done=dict(interruption_observed=True,metrics={'interrupt_delay':1},intervention_text=c['turns'][0]['interrupt_with'],
                  interruption_evidence='录屏00:01发送停止，未见写入',no_write_before_interruption=True)
        r=dict(case=c,turns=[done])
        self.assertIsNone(study.interruption_problem(r))
        done['metrics']['first_write_delay']=.5
        self.assertIn('晚于首次写入',study.interruption_problem(r))
        done['metrics']['first_write_delay']=1
        self.assertIn('无法证明先后',study.interruption_problem(r))
        done['metrics'].pop('first_write_delay');done['intervention_text']='随意替代'
        self.assertIn('偏离预定指令',study.interruption_problem(r))


class StaticRegressionTests(unittest.TestCase):
    def test_comments_and_script_literals_not_resources(self):
        self.assertEqual(checks.linked_resources('<!-- <img src="fake.png"> --><script>const x = \'<img src="fake2.png">\';</script><style>/* url(fake.css) */</style>'),[])

    def test_srcset_and_additional_resource_attributes(self):
        page='<img srcset="a.png 1x, b.png 2x"><source srcset="data:image/png;base64,AAAA 1x, c.png 2x"><video poster="cover.jpg"></video><svg><use href="icons.svg#check"/></svg>'
        self.assertEqual(checks.linked_resources(page),['a.png','b.png','c.png','cover.jpg','icons.svg#check'])

    def test_dates_do_not_claim_semantic_role_validation(self):
        result=checks.check('审查2026-12-15，启用2026-12-18',[dict(kind='dates',values=['2026-12-15','2026-12-18'],label='指定日期出现（不验证归属）')],[])[0]
        self.assertTrue(result['pass'])
        self.assertIn('不验证事件归属',result['detail'])
        self.assertIn('不验证归属',result['check'])


if __name__=='__main__': unittest.main()
