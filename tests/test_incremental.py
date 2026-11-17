import json, os, tempfile, unittest
from pathlib import Path
from pctx.storage import init_context
from pctx.scan import scan_project
from pctx.architecture import refresh_architecture, load_architecture
from pctx.compile import compile_context

class IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);init_context(self.root)
        (self.root/'package.json').write_text('{"name":"fixture"}')
        (self.root/'src').mkdir()
        for n in range(6):(self.root/f'src/module{n}.py').write_text('from . import module1\n')
    def test_reuse_small_change_full_and_corrupt_cache(self):
        scan_project(self.root);refresh_architecture(self.root)
        warm=refresh_architecture(self.root)
        self.assertEqual(warm['analysis']['processed'],0);self.assertEqual(warm['analysis']['reused'],6)
        file=self.root/'src/module2.py'; stat=file.stat()
        file.write_text('from . import module3\n');os.utime(file,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        changed=refresh_architecture(self.root)
        self.assertEqual(changed['analysis']['processed'],1)
        expected=load_architecture(self.root)['generated']['edges']
        full=refresh_architecture(self.root,full=True)
        self.assertEqual(full['analysis']['processed'],6)
        self.assertEqual(expected,load_architecture(self.root)['generated']['edges'])
        (self.root/'.project-context/.cache/imports.json').write_text('{broken')
        self.assertEqual(refresh_architecture(self.root)['analysis']['processed'],6)
    def test_exclusion_delete_and_coverage(self):
        scan_project(self.root)
        (self.root/'.pctxignore').write_text('src/module2.py\n')
        (self.root/'src/module3.py').unlink()
        report=scan_project(self.root,max_files=2)
        self.assertTrue(report['truncated'])
        text, info=compile_context(self.root,task='inspect',budget=1800)
        self.assertIn('Scan coverage: INCOMPLETE',text)
        self.assertEqual(info['scan_coverage']['status'],'INCOMPLETE')
        full=scan_project(self.root,full=True)
        snapshot=json.loads((self.root/'.project-context/.cache/snapshot.json').read_text())
        self.assertNotIn('src/module2.py',snapshot['files']);self.assertNotIn('src/module3.py',snapshot['files'])
        self.assertFalse(full['truncated'])
    def test_watcher_groups_burst_and_remembers_add_delete(self):
        from unittest.mock import patch
        from pctx.service import ProjectWatcher
        watcher=ProjectWatcher(self.root,interval=1)
        samples=[{'changed':['added.py'],'content_digest':'a','initialized':True},
                 {'changed':['added.py','deleted.py'],'content_digest':'b','initialized':True},
                 {'changed':['added.py','deleted.py'],'content_digest':'b','initialized':True}]
        with patch.object(watcher.stop_event,'wait',side_effect=[False,False,False,True]), patch('pctx.service.changes',side_effect=samples), patch('pctx.service.read_snapshot',return_value={'git':{}}), patch('pctx.service.git_snapshot',return_value={}), patch('pctx.service.refresh_project') as refresh:
            watcher._run()
        refresh.assert_called_once_with(self.root,observed_changes=['added.py','deleted.py'])
    def test_parser_version_invalidates_cache(self):
        from unittest.mock import patch
        refresh_architecture(self.root)
        with patch('pctx.incremental.PARSER_VERSION',999):
            self.assertEqual(refresh_architecture(self.root)['analysis']['processed'],6)
