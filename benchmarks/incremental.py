"""Measure identical deterministic source fixtures against selected PCTX source."""
import argparse, inspect, json, os, sys, tempfile, time
from pathlib import Path
source=os.environ.get('PCTX_BENCHMARK_COMPILER_ROOT')
sys.path.insert(0,source or str(Path(__file__).resolve().parents[1]))
from pctx import __version__
from pctx.storage import init_context
from pctx.scan import scan_project
from pctx.architecture import refresh_architecture, load_architecture


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='pctx-incremental-') as directory:
        root=Path(directory);(root/'src').mkdir();(root/'pyproject.toml').write_text('[project]\nname="fixture"\nversion="1.0"\n')
        for n in range(160):
            (root/f'src/m{n:03}.py').write_text('from . import m001\n' + '# deterministic parser workload\n' * 3000)
        init_context(root);measurements=[]
        def measure(name,full=False):
            started=time.perf_counter()
            kw={'full':full} if 'full' in inspect.signature(scan_project).parameters else {}
            scan=scan_project(root,**kw)
            kw={'full':full} if 'full' in inspect.signature(refresh_architecture).parameters else {}
            architecture=refresh_architecture(root,**kw)
            measurements.append({'step':name,'seconds':round(time.perf_counter()-started,6),
                'files':scan['files'],'scan_analysis':scan.get('analysis'), 'architecture_analysis':architecture.get('analysis')})
        measure('cold');measure('unchanged')
        file=root/'src/m000.py';stat=file.stat();text=file.read_text();file.write_text(text.replace('m001','m002',1));os.utime(file,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        measure('one_changed_same_size_mtime');expected=load_architecture(root)['generated']['edges']
        measure('full_verification',True);same=expected==load_architecture(root)['generated']['edges']
        (root/'src/m159.py').unlink();measure('one_deleted')
        report={'fixture_version':1,'pctx_version':__version__,'measurements':measurements,
                'incremental_equals_full':same,'hash_policy':'all discovered content rehashed; parser reuse only',
                'source_bytes_per_file':len(text.encode())}
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n')
        assert same
        if measurements[1]['architecture_analysis']:
            assert measurements[1]['architecture_analysis']['processed']==0
            assert measurements[2]['architecture_analysis']['processed']==1
        print(json.dumps(report))
if __name__=='__main__':main()
