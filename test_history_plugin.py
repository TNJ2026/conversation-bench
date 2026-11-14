from pathlib import Path
import argparse
import contextlib
import io
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import history_plugin
import longrun


class HistoryPluginTests(unittest.TestCase):
    def test_create_freezes_opt_in_and_rejects_sdk_before_creating_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            args=argparse.Namespace(output=str(root/'run'/'plan.json'),model='fixture',provider='fixture',
                load_batches=1,seed=42,transport='sdk',history_plugin=True,effort='low',timeout=5,
                dsh_bin='fixture',app_version='fixture')
            with self.assertRaisesRegex(ValueError,'requires --transport web'):
                longrun.create(args)
            self.assertFalse((root/'run').exists())
            args.transport='web'
            with patch.object(longrun,'__file__',str(root/'project'/'longrun.py')),contextlib.redirect_stdout(io.StringIO()):
                longrun.create(args)
            state=longrun.load(Path(args.output));meta=state['config']['history_plugin']
            self.assertEqual(meta['activation'],'recovery-only')
            self.assertEqual(meta['sha256'],history_plugin.hashes(Path(meta['snapshot'])))

    def test_frozen_plugin_is_staged_and_changes_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);meta=history_plugin.freeze(root)
            home=root/'homes'/'A';home.mkdir(parents=True)
            patch=history_plugin.stage(home,meta)
            self.assertEqual(patch.parent/'index.cjs',home/'bench-current-history'/'index.cjs')
            self.assertEqual(history_plugin.hashes(patch.parent),meta['sha256'])
            (patch.parent/'index.cjs').write_text('changed')
            with self.assertRaisesRegex(ValueError,'changed'):
                history_plugin.stage(home,meta)
            (Path(meta['snapshot'])/'index.cjs').write_text('changed')
            with self.assertRaisesRegex(ValueError,'Frozen'):
                history_plugin.stage(home,meta)

    def test_plugin_cannot_be_staged_through_a_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);meta=history_plugin.freeze(root);home=root/'home';home.mkdir()
            target=root/'other';target.mkdir();(home/'bench-current-history').symlink_to(target)
            with self.assertRaisesRegex(ValueError,'symlink'):
                history_plugin.stage(home,meta)

    def test_evidence_only_counts_plugin_tools(self):
        meta={'name':'test','version':'0','sha256':{},'activation':'recovery-only'}
        events=[{'seq':1,'type':'tool/call','data':{'name':'current_history_search'}},
                {'seq':2,'type':'tool/call','data':{'name':'bash'}}]
        self.assertEqual(history_plugin.evidence(meta,events)['calls'],[{'seq':1,'name':'current_history_search'}])

    def test_runner_rejects_unverified_or_wrong_phase_plugin_labels(self):
        state={'config':{'history_plugin':{'name':'test','version':'0','sha256':{},'activation':'recovery-only'}}}
        result={'finish_reason':'completed','events':[],'answer':'fixture'}
        with self.assertRaisesRegex(ValueError,'loading evidence'):
            longrun.validate_result(state,'A/recovery','fixture',result)
        result['history_plugin']={'registered':True}
        with self.assertRaisesRegex(ValueError,'outside'):
            longrun.validate_result(state,'A/recall','fixture',result)

    @unittest.skipUnless(shutil.which('node'),'Node is required for native plugin tests')
    def test_native_plugin_isolation_and_read_contract(self):
        result=subprocess.run(['node','--test',str(history_plugin.SOURCE/'test.cjs')],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
