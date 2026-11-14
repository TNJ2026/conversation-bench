"""Protocol separation and end-to-end recording without touching real runs."""
import argparse
import contextlib
import copy
import io
import tempfile
import unittest
from collections import Counter
from itertools import permutations
from pathlib import Path
from unittest.mock import patch
import checks
import study
import suite


def args(**kwargs):
    return argparse.Namespace(**kwargs)

class StudyTests(unittest.TestCase):
    def test_catalog_has_three_cases_per_category(self):
        catalog=suite.build()
        self.assertEqual(len({c['id'] for c in catalog}),18)
        for category in ('ambiguity','revision','context','recovery','review','interrupt'):
            self.assertEqual(sum(c['category']==category for c in catalog),3)
        for c in catalog:
            if c['category']=='revision':
                self.assertEqual(c['turns'][0]['checks'][0]['min'],450)
                self.assertNotIn('220',c['turns'][-1]['prompt'])

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
            root=Path(directory);study.save(root/'cases-v2.json',suite.build())
            selection=['dsh','chatgpt','hermes']
            with patch.object(study,'ROOT',root):
                for name in ('first','second'):
                    study.create(args(cases=None,products=selection,repeat=1,seed=42,
                                      mode='default',output=str(root/name/'plan.json')))
            first=study.load(root/'first/plan.json');second=study.load(root/'second/plan.json')
            self.assertEqual(first['products'],selection)
            self.assertEqual(first['jobs'],second['jobs'])
            self.assertEqual(len(first['jobs']),54)
            orders=[]
            for start in range(0,54,3):
                group=first['jobs'][start:start+3]
                self.assertEqual(len({j['case_hash'] for j in group}),1)
                self.assertEqual({j['product'] for j in group},set(selection))
                orders.append(tuple(j['product'] for j in group))
            self.assertEqual(set(orders),set(permutations(selection)))
            for position in range(3):
                self.assertEqual(Counter(order[position] for order in orders),
                                 Counter({product:6 for product in selection}))

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
            catalog=suite.build();case=next(c for c in catalog if c['id']=='review-knowledge')
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
                    study.begin(args(plan=str(plan),job=job['id'],model='test-model',app_version='1',permissions='test',plugins='none',memory='off',method='desktop',isolated=True,unexposed=True))
                    rp=study.record_path(plan,job);record=study.load(rp); workspace=Path(record['workspace'])
                    self.assertEqual(set(p.name for p in workspace.iterdir()),{'meeting.txt'})
                    answer=root/'answer.txt';answer.write_text('<script>bad()</script>')
                    page='<section id="overview">A</section><section id="risks">B</section><section id="decisions">C</section>'
                    for i in range(4):
                        (workspace/'report.html').write_text(page.replace('>A<','>changed<') if i==3 and job['product']=='chatgpt' else page)
                        study.submit(args(record=str(rp),answer=str(answer),notes=None,elapsed=None,first_feedback=None,active_seconds=None,corrections=None,actions=None,interrupt_delay=None,interruption_observed=False))
                    record=study.load(rp)
                    self.assertEqual(all(c['pass'] for c in record['turns'][-1]['checks']),job['product']!='chatgpt')
                    scores=study.form(record);scores['valid']=True
                    for item in scores['acceptance']:item.update({'pass':True,'evidence':'synthetic test only'})
                    sp=root/'score.json';study.save(sp,scores)
                    study.finish(args(record=str(rp),scores=str(sp),outcome='completed'))
                    with self.assertRaises(SystemExit):
                        study.finish(args(record=str(rp),scores=str(sp),outcome='completed'))
                study.report(args(plan=str(plan)))
                report=(plan.parent/'report.html').read_text()
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
                scores=study.load(export.parent/'scores.json')['samples']
                self.assertEqual({s['id'] for s in scores},{s['id'] for s in samples})
                self.assertTrue(all(s['factuality'] is None for s in scores))
                self.assertEqual(len(list(plan.parent.glob('*-KEY-DO-NOT-SHARE.json'))),1)
                key=study.load(next(plan.parent.glob('*-KEY-DO-NOT-SHARE.json')))
                self.assertEqual(set(key.values()),{j['id'] for j in jobs})

if __name__=='__main__':unittest.main()
