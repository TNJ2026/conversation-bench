"""Protocol separation and end-to-end recording without touching real runs."""
import argparse
import contextlib
import copy
import io
import re
import sys
import tempfile
import unittest
from collections import Counter
from itertools import permutations
from pathlib import Path
from unittest.mock import patch
import checks
import study
from suite_common import case, turn

BEGIN=dict(model='test-model',app_version='1',permissions='test',plugins='none',memory='off',
           method='desktop',isolated=True,unexposed=True)
SUBMIT=dict(notes=None,elapsed=None,first_feedback=None,active_seconds=None,corrections=None,
            actions=None,interrupt_delay=None,interruption_observed=False)
FIXED='预算上限20000元；项目负责人待定。'


def args(**kwargs):
    return argparse.Namespace(**({'suite':'v2'} | kwargs))

def page(risks='B',overview='A',decisions='C'):
    return (f'<section id="overview">{overview}</section><section id="risks">{risks}</section>'
            f'<section id="decisions">{decisions}</section>')

def cli(*argv):
    out=io.StringIO()
    with patch.object(sys,'argv',['study.py',*map(str,argv)]), contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        study.main()
    return out.getvalue()

class Run:
    """One temporary project; nothing is written next to the real repository."""
    def __init__(self,root,plan,out):
        self.root,self.plan,self.out=root,plan,out

    def begin(self,job='J001',plan=None,**changes):
        plan=plan or self.plan
        with patch.object(study,'WORKSPACES',self.root/'workspaces'):
            study.begin(args(plan=str(plan),job=job,**(BEGIN|changes)))
        self.path=plan.parent/'records'/(job+'.json')
        self.workspace=Path(self.record()['workspace'])
        return self

    def record(self):
        return study.load(self.path)

    def write(self,name,content):
        (self.workspace/name).write_text(content,encoding='utf-8')

    def submit(self,answer='answer',**changes):
        file=self.root/'answer.txt';file.write_text(answer,encoding='utf-8')
        study.submit(args(record=str(self.path),answer=str(file),**(SUBMIT|changes)))
        return {c['check']:c['pass'] for c in self.record()['turns'][-1]['checks']}

    def graded(self,verdict=True,flip=()):
        """Every criterion with evidence; indexes in `flip` get the opposite verdict."""
        return [{'criterion':c,'pass':not verdict if i in flip else verdict,'evidence':'synthetic test only'}
                for i,c in enumerate(self.record()['case']['acceptance'])]

    def finish(self,outcome='completed',confirm=False,**scores):
        file=self.root/'scores.json';study.save(file,study.form(self.record())|scores)
        study.finish(args(record=str(self.path),scores=str(file),outcome=outcome,confirm_conflicts=confirm))
        return self.record()['status']

    def summary(self):
        """Cells of this plan's first row in the report's summary table."""
        study.report(args(plan=str(self.plan)))
        return re.search('<tr><td>(.*?)</td></tr>',(self.plan.parent/'report.html').read_text()).group(1).split('</td><td>')

    def said(self):
        text=self.out.getvalue();self.out.seek(0);self.out.truncate(0)
        return text

def timed_file_case():
    return case('timed-file-fixture', 'file', 'Timed file fixture',
                [turn('List the draft files.', read_only=True)], [], ('ready', 'partial', 'missing'), [],
                fixtures={f'draft-{i}.md': str(i) for i in range(1, 4)}, fixture_mtime=1700000000)


def read_only_case():
    return case('read-only-fixture', 'file', 'Read-only fixture',
                [turn('Read the workspace listing.', read_only=True)], [], ('ready', 'partial', 'missing'), [],
                fixtures={'email.txt': 'Local test input.'})



def legacy_fixture(key, category, turns, acceptance, **details):
    return dict(id=key, title=key, category=category, revision=1, setup='Synthetic test setup.',
                turns=turns, acceptance=acceptance, auto={}, fixtures={}, **details)


def review_case():
    fixture = legacy_fixture(
        'fixture-review', 'review',
        [turn('Write the fixture HTML.', sections=['overview', 'risks', 'decisions']),
         turn('Revise the risk section.', capture_before=True, revises='risks', keeps_sections=['overview', 'decisions']),
         turn('Review the fixture without writing.', read_only=True, keeps_sections=['overview', 'decisions']),
         turn('Update only the risk section.', revises='risks', keeps_sections=['overview', 'decisions'])],
        ['HTML complete', 'Risk section updated', 'Protected HTML preserved', 'Discussion stayed read-only',
         'Source file preserved'])
    fixture['fixtures'] = {'meeting.txt': 'Synthetic meeting data.'}
    fixture['auto'] = {'Protected HTML preserved': [[None, 'overview保持不变'], [None, 'decisions保持不变']]}
    return fixture


def interrupt_case(version=2):
    turns = [turn('Start writing the fixture.', interrupt_with='先停止写文件，回复当前状态。',
                  interrupt_within=5, operator='在目标仍运行时发送后续指令。'),
             turn('Describe the result without writing.', read_only=True)]
    acceptance = ['Intervention was observed', 'Stopped writing', 'Reported the work', 'Stayed read-only']
    if version == 3:
        return case('fixture-interrupt', 'interrupt', 'Synthetic interrupt fixture', turns,
                    [(criterion, 'critical', [1] if i < 3 else [2]) for i, criterion in enumerate(acceptance)],
                    ('complete', 'partial', 'missing'), ['Local test data.'],
                    fixtures={'meeting.txt': '预算上限为虚构测试数据。'})
    fixture = legacy_fixture('fixture-interrupt', 'interrupt', turns, acceptance)
    fixture['fixtures'] = {'meeting.txt': 'Synthetic meeting data.'}
    fixture['auto'] = {'Stayed read-only': [[2, '本轮未改变文件']]}
    return fixture


def synthetic_catalog():
    review = review_case()
    interrupted = interrupt_case()
    lifecycle = legacy_fixture('fixture-lifecycle', 'ambiguity',
                               [turn(f'Lifecycle step {i}.') for i in range(1, 5)],
                               [f'Fixture requirement {i}' for i in range(1, 6)])
    recovery = legacy_fixture('fixture-recovery', 'recovery',
                              [turn(f'Recovery test step {i}.') for i in range(1, 5)],
                              ['Missing context reported', 'Available facts used'])
    recovery.update(fixtures={'meeting.txt': 'Synthetic meeting data.'}, absent=['budget-detail.csv'])
    dates = {'kind': 'dates', 'values': ['2026-12-15', '2026-12-18']}
    long = [{'kind': 'length', 'min': 450, 'max': 550}, dates,
            {'kind': 'paragraphs', 'count': 4}, {'kind': 'no_heading'},
            {'kind': 'paragraph', 'index': 2, 'value': FIXED}]
    short = [{'kind': 'length', 'max': 220}, dates,
             {'kind': 'contains', 'label': '保留固定句', 'values': [FIXED]},
             {'kind': 'preserve', 'turn': 2, 'paragraph': 2}]
    revision = legacy_fixture(
        'fixture-revision', 'revision',
        [turn('Write a layout fixture.', long), turn('Repeat with the same layout.', long),
         turn('Produce a shorter answer.', short), turn('Review the revision.'), turn('Finish the fixture.', short)],
        ['First layout', 'Length check', 'Fixed wording', 'Discussion', 'Final response'])
    revision['auto'] = {'Fixed wording': [[3, '保留固定句'], [5, '保留指定段落']]}
    extra = legacy_fixture('fixture-ordering', 'order', [turn('Keep the input.')], ['Input preserved'])
    return [lifecycle, review, interrupted, recovery, revision, extra]



@contextlib.contextmanager
def project(*case_ids,products=('dsh',)):
    with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()) as out:
        root=Path(directory)/'project';root.mkdir()
        catalog={c['id']:c for c in synthetic_catalog()}
        selected = [catalog[item] if isinstance(item, str) else item for item in case_ids]
        study.save(root/'cases-v2.json', selected)
        study.save(root/'cases-v3-advanced5.json', selected)
        study.save(root/'cases-v3-challenge3.json', [])
        study.save(root/'cases-v3-guard4.json', [])
        plan=root/'studies'/'test'/'plan.json'
        # WORKSPACES covers every begin in the test, including ones issued through the CLI.
        with patch.object(study,'ROOT',root), patch.object(study,'WORKSPACES',root/'workspaces'):
            study.create(args(cases=None,products=list(products),repeat=1,seed=42,mode='default',output=str(plan)))
            yield Run(root,plan,out)

class CatalogTests(unittest.TestCase):
    def test_every_rule_kind_is_implemented(self):
        for c in synthetic_catalog():
            for turn in c['turns']:
                for rule in turn['checks']:
                    self.assertIn(rule['kind'],checks.KINDS,c['id'])

    def test_linked_checks_name_real_criteria_and_turns(self):
        for c in synthetic_catalog():
            self.assertLessEqual(set(c['auto']),set(c['acceptance']),c['id'])
            for pairs in c['auto'].values():
                for number,_ in pairs:
                    self.assertTrue(number is None or 1<=number<=len(c['turns']),c['id'])

class StudyTests(unittest.TestCase):
    def test_length_minimum_rejects_trivially_short_draft(self):
        rule=[{'kind':'length','min':450,'max':550}]
        self.assertFalse(checks.check('a'*200,rule,[])[0]['pass'])
        self.assertTrue(checks.check('a'*500,rule,[])[0]['pass'])
        self.assertFalse(checks.check('a'*551,rule,[])[0]['pass'])

    def test_pairing_excludes_selftest_invalid_and_mismatched_cases(self):
        base={'protocol':{'method':'desktop','isolated':True,'unexposed':True},'valid':True,'status':'completed','case_hash':'abc','repeat':1,'mode':'default','product':'dsh'}
        other=copy.deepcopy(base);other['product']='chatgpt'
        self.assertEqual(len(study.pair_records([base,other])),1)
        for change in ({'valid':False},{'case_hash':'different'},{'status':'running'},{'protocol':{'method':'selftest','isolated':True,'unexposed':True}}):
            self.assertEqual(study.pair_records([base,other|change]),[])
        self.assertEqual(len(study.pair_records([base,other|{'status':'failed'}])),1)

    def test_product_selection_validation(self):
        self.assertEqual(study.product_list(' DSH, Hermes '),['dsh','hermes'])
        for value in ('', ' ', ',hermes', 'hermes,', 'dsh,,hermes',
                      'hermes,hermes', 'Hermes,HERMES', 'unknown'):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                study.product_list(value)

    def test_three_product_plan_is_balanced_and_reproducible(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root=Path(directory);study.save(root/'cases-v2.json',synthetic_catalog())
            selection=['dsh','chatgpt','hermes']
            with patch.object(study,'ROOT',root):
                for name in ('first','second'):
                    study.create(args(cases=None,products=selection,repeat=1,seed=42,
                                      mode='default',output=str(root/name/'plan.json')))
            first=study.load(root/'first/plan.json');second=study.load(root/'second/plan.json')
            self.assertEqual(first['products'],selection)
            self.assertEqual(first['jobs'],second['jobs'])
            self.assertEqual(len(first['jobs']),18)
            orders=[]
            for start in range(0,18,3):
                group=first['jobs'][start:start+3]
                self.assertEqual(len({j['case_hash'] for j in group}),1)
                self.assertEqual({j['product'] for j in group},set(selection))
                orders.append(tuple(j['product'] for j in group))
            self.assertEqual(set(orders),set(permutations(selection)))
            for position in range(3):
                self.assertEqual(Counter(order[position] for order in orders),
                                 Counter({product:2 for product in selection}))

    def test_three_way_group_requires_each_selected_product(self):
        base={'protocol':{'method':'desktop','isolated':True,'unexposed':True},
              'valid':True,'status':'completed','case_hash':'abc','repeat':1,
              'mode':'default','product':'dsh'}
        other=base|{'product':'chatgpt'};hermes=base|{'product':'hermes'}
        products=['dsh','chatgpt','hermes']
        self.assertEqual(study.pair_records([base,other],products),[])
        group=study.pair_records([base,other,hermes],products)
        self.assertEqual(list(group[0]),products)
        for change in ({'valid':False},{'case_hash':'other'},{'repeat':2},
                       {'mode':'controlled'},{'status':'running'},
                       {'protocol':{'method':'selftest','isolated':True,'unexposed':True}}):
            with self.subTest(change=change):
                self.assertEqual(study.pair_records([base,other,hermes|change],products),[])
        self.assertEqual(len(study.pair_records([base,other,hermes|{'status':'failed'}],products)),1)
        self.assertEqual(study.pair_records([base,other,hermes,copy.deepcopy(hermes)],products),[])
        self.assertEqual(study.pair_records([hermes],['hermes']),[])
        self.assertEqual(len(study.pair_records([base,hermes],['dsh','hermes'])),1)

    def test_plan_run_score_report_blind(self):
        self.exercise_plan(legacy=True)

    def test_dsh_hermes_report_and_blind(self):
        self.exercise_plan(['dsh','hermes'])

    def test_three_way_report_and_blind(self):
        self.exercise_plan(['dsh','chatgpt','hermes'])

    def test_hermes_only_run_and_report(self):
        self.exercise_plan(['hermes'])

    def exercise_plan(self, products=None, legacy=False):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root=Path(directory)/'project'; root.mkdir()
            catalog=synthetic_catalog();case=next(c for c in catalog if c['id']=='fixture-review')
            study.save(root/'cases-v2.json',[case])
            plan=root/'studies'/'test'/'plan.json'
            with patch.object(study,'ROOT',root):
                config=dict(cases=None,repeat=1,seed=42,mode='default',output=str(plan))
                if products is not None:config['products']=products
                study.create(args(**config))
                saved=study.load(plan)
                if legacy:
                    self.assertEqual(saved.pop('products'),['dsh','chatgpt'])
                    study.save(plan,saved)
                products=products or ['dsh','chatgpt']
                jobs=saved['jobs']
                self.assertEqual(len(jobs),len(products))
                self.assertEqual(study.plan_products(saved),products)
                for job in jobs:
                    with patch.object(study,'WORKSPACES',root/'workspaces'):
                        study.begin(args(plan=str(plan),job=job['id'],**BEGIN))
                    rp=study.record_path(plan,job);record=study.load(rp); workspace=Path(record['workspace'])
                    self.assertEqual(set(p.name for p in workspace.iterdir()),{'meeting.txt'})
                    answer=root/'answer.txt';answer.write_text('<script>bad()</script>')
                    # The discussion turn (index 2) leaves the file as the previous turn wrote it.
                    for i,risks in enumerate(('draft','revised','revised','final')):
                        overview='changed' if i==3 and job['product']=='chatgpt' else 'A'
                        (workspace/'report.html').write_text(page(risks,overview))
                        study.submit(args(record=str(rp),answer=str(answer),**SUBMIT))
                    record=study.load(rp)
                    for turn in record['turns'][:3]:
                        self.assertTrue(all(c['pass'] for c in turn['checks']))
                    self.assertEqual(all(c['pass'] for c in record['turns'][-1]['checks']),job['product']!='chatgpt')
                    scores=study.form(record);scores['valid']=True
                    for item in scores['acceptance']:item.update({'pass':True,'evidence':'synthetic test only'})
                    sp=root/'score.json';study.save(sp,scores)
                    finish=lambda confirm:study.finish(args(record=str(rp),scores=str(sp),outcome='completed',confirm_conflicts=confirm))
                    changed=job['product']=='chatgpt'
                    if changed:
                        # Passing "sections kept verbatim" contradicts the failed overview check.
                        with self.assertRaisesRegex(SystemExit,'overview保持不变'):
                            finish(False)
                        self.assertEqual(study.load(rp)['status'],'running')
                    finish(changed)
                    with self.assertRaises(SystemExit):
                        finish(True)
                study.report(args(plan=str(plan)))
                report=(plan.parent/'report.html').read_text()
                self.assertEqual('<td>1 处</td>' in report,'chatgpt' in products)
                self.assertEqual('冲突：' in report,'chatgpt' in products)
                self.assertNotIn('匿名文本评审',report)
                self.assertNotIn('<script>',report)
                self.assertIn('&lt;script&gt;',report)
                for product in products:self.assertIn(product,report)
                if len(products)==1:
                    self.assertIn('单应用计划只记录测试结果',report)
                    with self.assertRaisesRegex(SystemExit,'单应用'):
                        study.blind(args(plan=str(plan)))
                    self.assertEqual(list(plan.parent.glob('blind-*')),[])
                    return
                self.assertIn('有效完整对照 1 组',report)
                study.blind(args(plan=str(plan)))
                export=next(plan.parent.glob('blind-*/review.json'))
                text=export.read_text()
                self.assertNotIn('"product"',text)
                self.assertNotIn('test-model',text)
                samples=study.load(export)['samples']
                self.assertEqual(len(samples),len(products))
                self.assertEqual({s['id'] for s in samples},
                                 {'P001-'+chr(ord('A')+i) for i in range(len(products))})
                scores=study.load(export.parent/'scores-r1.json')['samples']
                self.assertEqual({s['id'] for s in scores},{s['id'] for s in samples})
                self.assertTrue(all(t['factuality']['score'] is None for s in scores for t in s['turns']))
                key=study.load(next(plan.parent.glob('*-KEY-DO-NOT-SHARE.json')))
                self.assertEqual(set(key.values()),{j['id'] for j in jobs})
                self.assertEqual(samples[0]['materials'],case['fixtures'])
                self.assertIn('report.html',samples[0]['turns'][0]['artifacts'])
                self.assertEqual(samples[0]['coverage']['submitted_turns'],4)
                study.report(args(plan=str(plan)))
                self.assertIn('V3逐轮独立评审',(plan.parent/'report.html').read_text())
                # Historical score files remain readable, but explicitly marked legacy.
                sheet={'samples':[{'id':'P001-A','factuality':4,'usefulness':9,'evidence':'第二轮把预计日期写成确定'}]}
                study.save(export.parent/'scores.json',sheet)
                study.report(args(plan=str(plan)))
                report=(plan.parent/'report.html').read_text()
                self.assertIn('无效值',report)
                self.assertIn('以上为历史版评分',report)

class ReviewCaseTests(unittest.TestCase):
    def test_comment_tags_do_not_block_unchanged_sections_at_finish(self):
        with project('fixture-review') as run:
            run.begin()
            overview='概况<!-- 示例：<section> -->原文保持'
            run.write('report.html',page('事实与推测已分开',overview))
            self.assertTrue(all(run.submit().values()))
            run.write('report.html',page('事实与推测已分开；补充依据',overview))
            self.assertTrue(all(run.submit().values()))
            self.assertTrue(all(run.submit('仅讨论，不修改文件。').values()))
            run.write('report.html',page('事实与推测已分开；补充依据与解释',overview))
            self.assertTrue(all(run.submit().values()))
            self.assertEqual(run.finish(valid=True,acceptance=run.graded()),'completed')
            self.assertEqual(run.summary()[7],'无')

    def test_untouched_risk_section_fails_both_revision_turns(self):
        with project('fixture-review') as run:
            run.begin();run.write('report.html',page())
            first=run.submit()
            self.assertTrue(first['指定section齐全'] and first['单文件无外部资源'])
            self.assertFalse(run.submit()['risks已修改'])
            self.assertTrue(run.submit()['本轮未改变文件'])
            last=run.submit()
            self.assertFalse(last['risks已修改'])
            self.assertTrue(last['overview保持不变'] and last['decisions保持不变'])

    def test_first_turn_requires_every_section_and_a_self_contained_file(self):
        with project('fixture-review') as run:
            run.begin()
            run.write('report.html','<script src="https://cdn.example.com/x.js"></script>'+page().replace('id="decisions"','id="other"'))
            result=run.submit()
            self.assertFalse(result['指定section齐全'])
            self.assertFalse(result['单文件无外部资源'])
        with project('fixture-review') as run:
            run.begin()
            result=run.submit()
            self.assertFalse(result['指定section齐全'])
            self.assertNotIn('单文件无外部资源',result)

    def test_change_after_a_nested_section_is_detected(self):
        with project('fixture-review') as run:
            run.begin()
            nested='<section>inner</section>'
            run.write('report.html',page(overview=nested+'before'));run.submit()
            run.write('report.html',page('revised',overview=nested+'after'))
            result=run.submit()
            self.assertFalse(result['overview保持不变'])
            self.assertTrue(result['decisions保持不变'] and result['risks已修改'])

    def test_discussion_turn_write_and_source_change_are_detected(self):
        with project('fixture-review') as run:
            run.begin();run.write('report.html',page());run.submit()
            run.write('report.html',page('revised'));run.submit()
            run.write('scratch.txt','written during the discussion turn')
            self.assertFalse(run.submit()['本轮未改变文件'])
            run.write('meeting.txt','tampered')
            self.assertFalse(run.submit()['meeting.txt原始材料未变'])

    def test_artifact_in_another_encoding_is_recorded_for_manual_review(self):
        with project('fixture-review') as run:
            run.begin()
            (run.workspace/'report.html').write_bytes(page(overview='项目概况').encode('gbk'))
            result=run.submit()
            self.assertIsNone(result['report.html编码'])
            self.assertTrue(result['指定section齐全'])
            self.assertIn('项目概况',run.record()['turns'][0]['artifacts']['report.html'])

class FileCaseTests(unittest.TestCase):
    def test_removal_is_allowed_only_after_authorized_turn(self):
        fixture = timed_file_case()
        fixture['turns'] += [turn('Remove draft-2.md.', may_remove=['draft-2.md'])]
        initial = {name: name for name in fixture['fixtures']}
        remaining = {name: value for name, value in initial.items() if name != 'draft-2.md'}
        early = study.fixture_checks(fixture, 1, remaining, initial)
        permitted = study.fixture_checks(fixture, 2, remaining, initial)
        self.assertIn(False, [check['pass'] for check in early])
        self.assertEqual(len(permitted), 2)
        self.assertTrue(all(check['pass'] for check in permitted))

    def test_fixture_write_order_is_shuffled_only_for_timed_cases(self):
        timed = timed_file_case()
        orders=set(); newest=set()
        with tempfile.TemporaryDirectory() as d:
            for i in range(40):
                w=Path(d)/str(i); w.mkdir(); written=[]
                study.write_fixtures(timed, w, written.append)
                orders.add(tuple(p.name for p in written))
                self.assertEqual(len({p.stat().st_mtime_ns for p in w.iterdir()}), 1)
                # The final ctime order, which an agent can list with ls -c, must follow the shuffled order.
                # Filesystems with coarse timestamps give equal ctimes, which carry no order cue either.
                ctimes=[p.stat().st_ctime_ns for p in written]
                self.assertEqual(ctimes,sorted(ctimes))
                newest.add(written[-1].name)
            self.assertGreater(len(orders), 1)
            self.assertEqual(newest, set(timed['fixtures']))
            plain=read_only_case(); written=[]
            study.write_fixtures(plain, Path(d)/'plain', written.append)
            self.assertEqual([p.name for p in written], list(plain['fixtures']))

    def test_deletion_fixture_times_are_equal_before_display(self):
        with project(timed_file_case()) as run:
            run.begin()
            self.assertEqual(len({p.stat().st_mtime_ns for p in run.workspace.glob('draft-*.md')}), 1)

    def test_recovery_new_budget_file_requires_human_source_review(self):
        for content,answer,fabricated in (
                ('# 新建空白模板，不是原始材料\nitem,cost\n', '原文件缺失，另建空白模板，未读取到预算数据。', False),
                ('item,cost\nall,19999\n', '我读取了原预算文件，已核实成本19999元。', True)):
            with self.subTest(fabricated=fabricated), project('fixture-recovery') as run:
                run.begin()
                self.assertEqual(run.submit(),{'meeting.txt原始材料未变':True,'缺失材料文件状态':True})
                run.write('budget-detail.csv',content)
                self.assertIsNone(run.submit(answer)['缺失材料文件状态'])
                run.submit(answer);run.submit(answer)
                # File presence alone cannot decide whether the missing source was fabricated.
                self.assertEqual(run.finish(valid=True,acceptance=run.graded(flip=[0] if fabricated else [])), 'completed')
                self.assertEqual(run.summary()[7],'无')

    def test_desktop_snapshot_records_symlinks_without_following(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as outside:
            w=Path(d);(w/'a.txt').write_text('a');(Path(outside)/'secret.txt').write_text('s')
            before=study.snapshot(w)
            (w/'dir').symlink_to(outside,target_is_directory=True);(w/'f').symlink_to(w/'a.txt')
            after=study.snapshot(w)
            self.assertEqual(set(after)-set(before),{'dir','f'})
            self.assertNotIn('dir/secret.txt',after)

    def test_desktop_snapshot_records_empty_directories(self):
        with tempfile.TemporaryDirectory() as d:
            w=Path(d);(w/'a.txt').write_text('a')
            before=study.snapshot(w)
            (w/'new'/'inner').mkdir(parents=True)
            after=study.snapshot(w)
            # Only the innermost directory is empty; its parent is implied by the key.
            self.assertEqual(set(after)-set(before),{'new/inner/'})
            (w/'new'/'inner'/'x.txt').write_text('x')
            self.assertNotIn('new/inner/',study.snapshot(w))

    def test_empty_directory_breaks_read_only_turn(self):
        with project('fixture-review') as run:
            run.begin();run.write('report.html',page());run.submit();run.submit()
            (run.workspace/'scratch').mkdir()
            self.assertFalse(run.submit()['本轮未改变文件'])

    def test_recovery_detects_a_broken_symlink_as_a_new_path(self):
        with project('fixture-recovery') as run:
            run.begin()
            (run.workspace/'budget-detail.csv').symlink_to(run.workspace/'not-present.csv')
            self.assertIsNone(run.submit()['缺失材料文件状态'])

    def test_interrupt_timing_stays_out_of_the_application_checks(self):
        with project('fixture-interrupt') as run:
            run.begin();run.submit(interruption_observed=True,interrupt_delay=1.5)
            with self.assertRaisesRegex(SystemExit,'没有预定干预'):
                run.submit(interruption_observed=True)
            run.write('report.md','written after being told to stay read-only');run.submit()
            with self.assertRaisesRegex(SystemExit,'本轮未改变文件'):
                run.finish(valid=True,acceptance=run.graded())
            self.assertEqual(run.finish(valid=True,confirm=True,acceptance=run.graded()),'completed')
            cells=run.summary()
            self.assertEqual(cells[3:6],['2/2','通过 2／未通过 1／待人工 0','干预时点：符合'])
            self.assertEqual(cells[7],'1 处')

    def test_late_or_misplaced_interruption_cannot_be_valid(self):
        with project('fixture-interrupt') as run:
            run.begin();run.submit(interruption_observed=True,interrupt_delay=9.0);run.submit()
            with self.assertRaisesRegex(SystemExit,'超过上限'):
                run.finish(valid=True,acceptance=run.graded())
            self.assertEqual(run.finish(valid=False,invalid_reason='干预晚于时限'),'invalid')
            self.assertEqual(run.summary()[4:6],['通过 3／未通过 0／待人工 0','干预时点：不符合'])

    def test_interrupt_timing_and_read_only_turn(self):
        for changes,expected in (({'interruption_observed':True,'interrupt_delay':1.5},True),
                                 ({'interruption_observed':True,'interrupt_delay':9.0},False),
                                 ({'interruption_observed':True},None)):
            with self.subTest(changes=changes), project('fixture-interrupt') as run:
                run.begin()
                self.assertIn('在目标仍运行时发送',run.said())
                self.assertIs(run.submit(**changes)['干预时点'],expected)
                run.write('report.md','written after being told to stay read-only')
                self.assertFalse(run.submit()['本轮未改变文件'])

    def test_interrupt_without_observation_cannot_be_valid(self):
        with project('fixture-interrupt') as run:
            run.begin()
            self.assertNotIn('干预时点',run.submit())
            self.assertTrue(run.submit()['本轮未改变文件'])
            with self.assertRaisesRegex(SystemExit,'干预'):
                run.finish(valid=True,acceptance=run.graded())
            self.assertEqual(run.finish(valid=False,invalid_reason='任务在干预前已完成'),'invalid')

    def test_revision_run_tracks_layout_and_the_fixed_sentence(self):
        dates='启用日期2026-12-15，安全审查2026年12月18日完成。'
        draft=lambda second:'\n\n'.join([dates+'字'*140,second,'字'*160,'字'*160])
        rewritten='预算约两万元，负责人是张三。'
        with project('fixture-revision') as run:
            run.begin()
            self.assertTrue(all(run.submit(draft(FIXED)).values()))
            drifted=run.submit(draft(rewritten))
            self.assertFalse(drifted.pop('第2段原样'))
            self.assertTrue(all(drifted.values()))
            # Keeping the rewritten paragraph satisfies "preserve" but not the fixed sentence.
            self.assertEqual(run.submit(dates+rewritten),
                             {'非空白字符上限':True,'保留指定日期':True,'保留固定句':False,'保留指定段落':True})
            self.assertEqual(run.submit('只讨论，不交付。'),{})
            self.assertEqual(run.submit(dates+FIXED),
                             {'非空白字符上限':True,'保留指定日期':True,'保留固定句':True,'保留指定段落':False})
            with self.assertRaisesRegex(SystemExit,'保留固定句'):
                run.finish(valid=True,acceptance=run.graded())
            self.assertEqual(run.finish(valid=True,acceptance=run.graded(flip=[2])),'completed')

    def test_same_named_plan_directories_get_separate_workspaces(self):
        with project('fixture-review') as run:
            first=run.begin().workspace
            other=run.root.parent/'elsewhere'/'test'/'plan.json'
            study.create(args(cases=None,products=['dsh'],repeat=1,seed=42,mode='default',output=str(other)))
            second=run.begin(plan=other).workspace
            self.assertNotEqual(first,second)
            self.assertEqual({p.name for p in second.iterdir()},{'meeting.txt'})
            self.assertEqual({p.name for p in first.iterdir()},{'meeting.txt'})

class LifecycleTests(unittest.TestCase):
    def test_create_rejects_bad_input_and_existing_plans(self):
        with project('fixture-lifecycle') as run:
            config=dict(cases=None,products=['dsh'],repeat=1,seed=42,mode='default')
            for change in ({'cases':'no-such-case'},{'repeat':0},{'output':str(run.plan)}):
                with self.subTest(change=change), self.assertRaises(SystemExit):
                    study.create(args(**({'output':str(run.root/'new'/'plan.json')}|config|change)))
            self.assertFalse((run.root/'new').exists())

    def test_begin_and_submit_refuse_to_overwrite_or_overrun(self):
        with project('fixture-lifecycle') as run:
            with self.assertRaises(SystemExit):
                run.begin('J999')
            run.begin()
            with self.assertRaises(SystemExit):
                run.begin()
            with self.assertRaisesRegex(SystemExit,'回答为空'):
                run.submit('  \n')
            for _ in range(4):
                run.submit()
            with self.assertRaisesRegex(SystemExit,'请 finish'):
                run.submit()
            self.assertEqual(len(run.record()['turns']),4)
            with self.assertRaisesRegex(SystemExit,'评完全部'):
                run.finish(valid=True,acceptance=run.graded(flip=[1])[:1]+run.graded(None)[1:])
            run.finish(valid=True,acceptance=run.graded())
            with self.assertRaisesRegex(SystemExit,'已结案'):
                run.submit()

    def test_next_follows_the_plan(self):
        with project('fixture-lifecycle',products=('dsh','hermes')) as run:
            first=study.load(run.plan)['jobs'][0]
            run.said();study.next_job(args(plan=str(run.plan)))
            fresh=run.said()
            self.assertIn(first['id']+' | '+first['product'],fresh)
            self.assertIn('begin',fresh)
            run.begin();run.submit();run.said()
            study.next_job(args(plan=str(run.plan)))
            self.assertIn('当前第 2 轮',run.said())
            run.finish('failed',valid=True,acceptance=run.graded(None));run.said()
            study.next_job(args(plan=str(run.plan)))
            self.assertIn('J002',run.said())
            run.begin('J002');run.finish('failed',valid=False,invalid_reason='材料放错');run.said()
            study.next_job(args(plan=str(run.plan)))
            self.assertIn('均已结案',run.said())

    def test_finish_writes_a_template_and_validates_scores(self):
        with project('fixture-lifecycle') as run:
            run.begin();run.submit()
            study.finish(args(record=str(run.path),scores=None,outcome='completed'))
            template=study.load(run.path.with_name('J001-scores.json'))
            criteria=run.record()['case']['acceptance']
            self.assertEqual([x['criterion'] for x in template['acceptance']],criteria)
            self.assertIsNone(template['valid'])
            self.assertEqual(set(template['rubric']),{'clarity','cooperation','note'})
            self.assertEqual(run.record()['status'],'running')
            # Unassessed items carry the reason; `change` applies to the first criterion.
            graded=lambda **change:[{'criterion':c,'pass':None,'evidence':'第一轮后停止响应，未到该项'}|(change if i==0 else {}) for i,c in enumerate(criteria)]
            for scores,message in (({},'valid'),
                                   ({'valid':'true'},'valid'),
                                   ({'valid':False},'无效原因'),
                                   ({'valid':False,'invalid_reason':None},'无效原因'),
                                   ({'valid':True,'acceptance':None},'验收条目'),
                                   ({'valid':True,'acceptance':graded()[1:]},'验收条目'),
                                   ({'valid':True,'acceptance':graded(**{'pass':'yes'})},'true / false / null'),
                                   ({'valid':True},'evidence'),
                                   ({'valid':True,'acceptance':graded(evidence='')},'evidence'),
                                   ({'valid':True,'acceptance':graded(**{'pass':True,'evidence':None})},'evidence'),
                                   ({'valid':True,'acceptance':graded(**{'pass':True,'evidence':'ok'})},'evidence'),
                                   ({'valid':True,'acceptance':graded(),'clarity':6},'主观分'),
                                   ({'valid':True,'acceptance':graded(),'clarity':True},'主观分'),
                                   ({'valid':True,'acceptance':graded(),'cooperation':2.5},'主观分'),
                                   ({'valid':True,'acceptance':graded(),'clarity':2},'clarity_evidence'),
                                   ({'valid':True,'acceptance':graded()},'轮次未完成')):
                with self.subTest(scores=scores), self.assertRaisesRegex(SystemExit,message):
                    run.finish(**scores)
            self.assertEqual(run.record()['status'],'running')
            self.assertEqual(run.finish('failed',valid=True,clarity=2,clarity_evidence='第一轮后不再回应追问',
                                        acceptance=graded(**{'pass':False})),'failed')
            self.assertEqual(run.summary()[3:],['1/4','无','—','通过 0／未通过 1／未评 4（共 5 条）','无','2 / 未评'])

    def test_command_line_defaults_and_number_validation(self):
        with project('fixture-lifecycle') as run, patch.object(study, 'DEFAULT_SUITE', 'v3-combined10'):
            self.assertEqual(cli('list').split('\t')[0],'fixture-lifecycle')
            cli('begin','--plan',run.plan,'--job','J001','--model','m')
            run.path=run.plan.parent/'records'/'J001.json'
            record=run.record()
            self.assertEqual(record['protocol'],{'method':'selftest','isolated':False,'unexposed':False})
            self.assertFalse(study.eligible(record|{'valid':True}))
            answer=run.root/'answer.txt';answer.write_text('answer',encoding='utf-8')
            base=('submit','--record',run.path,'--answer',answer)
            for bad in (('--elapsed','-1'),('--first-feedback','nan'),('--active-seconds','inf'),
                        ('--corrections','-1'),('--actions','1.5')):
                with self.subTest(bad=bad), self.assertRaises(SystemExit):
                    cli(*base,*bad)
            self.assertEqual(run.record()['turns'],[])
            cli(*base,'--elapsed','48','--first-feedback','3','--corrections','0')
            metrics=run.record()['turns'][0]['metrics']
            self.assertEqual((metrics['elapsed'],metrics['first_feedback'],metrics['corrections']),(48.0,3.0,0))
            self.assertIsNone(metrics['active_seconds'])
            self.assertIn('当前第 2 轮',cli('next','--plan',run.plan))
            with self.assertRaises(SystemExit):
                cli('create','--products','hermes,hermes','--output',run.root/'again'/'plan.json')
            cli('create','--products','hermes','--output',run.root/'solo'/'plan.json')
            self.assertEqual(study.load(run.root/'solo'/'plan.json')['products'],['hermes'])

if __name__=='__main__':unittest.main()


class IsolationTests(unittest.TestCase):
    def test_begin_never_writes_next_to_repository(self):
        real=study.ROOT.parent/'conversation-bench-workspaces'
        existed=real.exists()
        with project('fixture-review') as run:
            run.begin()
            self.assertTrue(run.workspace.is_relative_to(run.root))
        self.assertEqual(real.exists(),existed)
