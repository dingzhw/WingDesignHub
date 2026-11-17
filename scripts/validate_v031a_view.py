"""Local representative view/restore checks after the storage service changes."""
from pathlib import Path
from unittest.mock import patch
import importlib.util,json,time
from streamlit.testing.v1 import AppTest
from wingdesignhub.project_archive import read_bundle,build_bundle
from wingdesignhub.feedback_evidence import pack_native

root=Path(__file__).resolve().parents[1];base=root/'local/v031a'
paths=list((base/'representative/local/projects').glob('*.wdh'));assert len(paths)==1
parsed=read_bundle(paths[0].read_bytes());r=parsed['coupled_records'][0]
original=Path.read_bytes;start=time.monotonic()
with patch.object(Path,'read_bytes',lambda self: (_ for _ in ()).throw(AssertionError('unexpected native ZIP read')) if self.name=='native_evidence.zip' else original(self)):
    blob=build_bundle(parsed['project'],root,parsed['records'][0],coupled_record=r,current_run_id=r['run_id'],profile='portable')
seconds=time.monotonic()-start
a=AppTest.from_string(f"from wingdesignhub.project_ui import library\nlibrary({str(root)!r})")
a.session_state['opened_archive']=parsed;a.run(timeout=60)
assert not a.exception
assert any('原生过程证据单独保留' in c.value for c in a.caption)
assert len(a.get('plotly_chart'))>=1
spec=importlib.util.spec_from_file_location('restore',root/'scripts/restore_native_evidence.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
w=base/'restore-probe';(w/'native/a').mkdir(parents=True,exist_ok=True)
(w/'native/a/one').write_bytes(b'unchanged content');(w/'native/two').write_bytes(b'unchanged content')
pack_native(w)
assert m.restore(w/'native_evidence.zip',w/'native_manifest.json',w/'restored')==2
assert (w/'restored/a/one').read_bytes()==(w/'native/a/one').read_bytes()
try:m.restore(w/'native_evidence.zip',w/'native_manifest.json',w/'restored')
except FileExistsError:pass
else:raise AssertionError('overwrite accepted')
result={'portable_build_does_not_read_native_zip':True,'portable_build_s':seconds,'portable_bytes':len(blob),
        'real_archived_ui_no_exception':True,'final_geometry_component_present':True,'detached_status_visible':True,
        'restore_identity':True,'existing_destination_rejected':True}
(base/'final-checks.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(result)
