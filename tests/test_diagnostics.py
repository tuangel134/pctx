import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from pctx.storage import init_context
from pctx.diagnostics import diagnose

class DiagnosticTests(unittest.TestCase):
    def test_real_process_readonly_permissions_and_unchanged_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);init_context(root)
            before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
            result=diagnose(root)
            self.assertTrue(result['ok'],result);self.assertTrue(result['write_rejected']);self.assertTrue(result['process_closed'])
            self.assertEqual(before,{p:p.read_bytes() for p in root.rglob('*') if p.is_file()})
            self.assertTrue(diagnose(root,allow_write=True)['ok'])
            self.assertFalse(diagnose(root,command=['/nonexistent/pctx'])['ok'])
    def test_missing_root_and_timed_out_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            self.assertFalse(diagnose(root)['ok']);init_context(root)
            import sys
            result=diagnose(root,timeout=.05,command=[sys.executable,'-c','import time;time.sleep(5)'])
            self.assertFalse(result['ok']);self.assertTrue(result['process_closed'])
    def test_portable_diagnostic_uses_its_own_isolated_archive(self):
        import subprocess, sys
        from pctx.portable import build_portable
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);init_context(root)
            archive=build_portable(root)['path']
            result=subprocess.run([sys.executable,'-I',archive,'--root',str(root),'diagnose'],cwd=root,capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue(json.loads(result.stdout)['ok'])
