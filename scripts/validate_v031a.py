"""Frozen V0.3.1 representative artifact acceptance; does not rerun sizing."""
from pathlib import Path
import json,time,hashlib,shutil
from zipfile import ZipFile
from wingdesignhub.project_archive import build_bundle,read_bundle,save_bundle,load_saved
from wingdesignhub.requirements import DesignProject
from wingdesignhub.feedback_evidence import pack_native,check_native
from wingdesignhub.adapters import execute

root=Path(__file__).resolve().parents[1];out=root/'local/v031a/representative';out.mkdir(parents=True,exist_ok=True)
rid='3b8a708c07d54eb7bed4698717ec9bae';work=root/'runs'/rid
record=json.loads((work/'result.json').read_text('utf-8'))
parent=json.loads((root/'runs'/record['parent_run_id']/'result.json').read_text('utf-8'))
project=DesignProject.from_dict(json.loads((work/'input.json').read_text('utf-8')))
start=time.monotonic()
bundle=build_bundle(project,root,parent,coupled_record=record,current_run_id=rid,profile='portable')
seconds=time.monotonic()-start
parsed=read_bundle(bundle)
assert parsed['evidence_status']=='detached_not_verified'
assert parsed['coupled_records'][0]==record
for name in record['artifact_hashes']:
    if name!='native_evidence.zip':assert parsed['files'][f'runs/{rid}/{name}']==(work/name).read_bytes()
idx=save_bundle(bundle,out);assert save_bundle(bundle,out)==idx
assert load_saved(out,idx['archive_id'])['bundle_sha256']==parsed['bundle_sha256']
old_path=root/'local/v031/workflow/local/projects/9229cffb0caf48618ed0b82060262869.wdh'
old=read_bundle(old_path.read_bytes())
assert old['coupled_records']==parsed['coupled_records']
assert old['files']['reports/report.html']==parsed['files']['reports/report.html']
manifest=pack_native(out,native_root=work/'native')
check_native((out/'native_evidence.zip').read_bytes(),manifest)
old_manifest=json.loads((work/'native_manifest.json').read_text('utf-8'))
assert manifest['files']==old_manifest['files']
with ZipFile(out/'native_evidence.zip') as z:
    # Validate every logical file's original bytes through its content hash.
    for name,h in manifest['files'].items():assert hashlib.sha256(z.read('objects/'+h)).hexdigest()==h
# Replay only the historical failing XFOIL input to test early resource rejection.
probe=out/'bounded-xfoil';probe.mkdir(exist_ok=True)
original=root/'local/v031/diagnostics/polar'
shutil.copy2(original/'foil.dat',probe/'foil.dat')
cmd=json.loads((original/'command.json').read_text('utf-8'))
start=time.monotonic()
try:execute(cmd['argv'],probe,(original/'stdin.txt').read_text('ascii'),timeout=60,output_limit=1024*1024)
except RuntimeError as exc:
    assert '容量' in str(exc),str(exc)
else:raise AssertionError('expected historical failure')
result={'stage':'V0.3.1-A','representative_run':rid,'portable_bytes':len(bundle),'portable_build_s':seconds,
        'portable_under_20_MiB':len(bundle)<20*1024**2,'old_bundle_bytes':old_path.stat().st_size,
        'native_unique_archive_bytes':(out/'native_evidence.zip').stat().st_size,
        'native_old_archive_bytes':(work/'native_evidence.zip').stat().st_size,
        'logical_files_preserved':len(manifest['files']),'results_geometry_reports_identical':True,
        'old_bundle_readable':True,'save_deduplicated':True,
        'failure_probe_s':time.monotonic()-start,'failure_capture':json.loads((probe/'command.json').read_text('utf-8')),
        'scope':'artifact identity, archive recovery and real failure resource control; no new whole-aircraft numerical validation'}
assert result['portable_under_20_MiB']
(out/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
