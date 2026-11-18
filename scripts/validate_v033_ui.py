"""Real layout-enabled sizing/coupled result and portable archive UI evidence."""
from pathlib import Path
import json
from streamlit.testing.v1 import AppTest
from wingdesignhub.jobs import code_identity
from wingdesignhub.requirements import DesignProject
from wingdesignhub.project_archive import build_bundle,read_bundle,save_bundle,load_saved
from wingdesignhub.service import write_json

root=Path(__file__).resolve().parents[1];work=root/'local/v033/formal3'
read=lambda name:json.loads((work/name).read_text('utf8'))
assert read('freeze.json')==code_identity()
seed=read('seed.json');coupled=read('redesign.json')
assert coupled['status']=='concept_checked_with_limits'
p=DesignProject.from_dict(json.loads((root/'runs'/coupled['run_id']/'input.json').read_text('utf8')))
data=build_bundle(p,root,seed,coupled_record=coupled,current_run_id=coupled['run_id'],profile='portable')
parsed=read_bundle(data);assert parsed['project']==p and parsed['coupled_records']==[coupled]
archive_root=root/'local/v033/portable';saved=save_bundle(data,archive_root)
opened=load_saved(archive_root,saved['archive_id']);assert opened['project']==p
a=AppTest.from_string(f'from wingdesignhub.project_ui import library\nlibrary({str(archive_root)!r})')
a.session_state['opened_archive']=opened;a.run(timeout=60);assert not a.exception
b=AppTest.from_string(f'''from pathlib import Path
import json
from wingdesignhub.requirements import DesignProject
from wingdesignhub.sizing_ui import results
root=Path({str(root)!r})
p=DesignProject.from_dict(json.loads((root/'runs/{coupled['run_id']}/input.json').read_text('utf8')))
r=json.loads((root/'runs/{coupled['run_id']}/result.json').read_text('utf8'))
results(r,p,root)
''')
b.run(timeout=60);assert not b.exception and b.dataframe
c=AppTest.from_string('''from wingdesignhub.layout_ui import editor
import streamlit as st
editor(st.session_state['layout'],'reopened')''')
c.session_state['layout']=opened['project'].sizing.layout;c.run(timeout=30)
assert not c.exception and c.toggle[0].value
write_json(work/'ui-validation.json',{'saved_reopened_equal':True,'archive_id':saved['archive_id'],
    'bundle_bytes':len(data),'archive_ui_no_exception':True,'layout_editor_reopened':True,'actual_result_ui_no_exception':True,
    'current_run_id':coupled['run_id'],'source_matches':parsed['current_source_matches']})
print('archive and layout UI passed',len(data))
