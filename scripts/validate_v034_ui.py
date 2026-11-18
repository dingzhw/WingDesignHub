"""Actual constrained result, Chinese rendering and portable save/reopen evidence."""
from pathlib import Path
import argparse,json
from streamlit.testing.v1 import AppTest
from wingdesignhub.jobs import code_identity
from wingdesignhub.requirements import DesignProject
from wingdesignhub.project_archive import build_bundle,read_bundle,save_bundle,load_saved
from wingdesignhub.design_cards import make_card,card_html
from wingdesignhub.service import write_json


def main(root,work):
    root=Path(root).resolve();work=Path(work).resolve()
    assert json.loads((work/'freeze.json').read_text('utf8'))==code_identity()
    seed=json.loads((work/'sizing.json').read_text('utf8'))[0]['record'];coupled=json.loads((work/'coupled.json').read_text('utf8'))
    assert coupled['summary']['converged'] and coupled['status']=='constraints_not_met'
    p=DesignProject.from_dict(json.loads((root/'runs'/coupled['run_id']/'input.json').read_text('utf8')))
    data=build_bundle(p,root,seed,coupled_record=coupled,current_run_id=coupled['run_id'],profile='portable')
    parsed=read_bundle(data);assert parsed['project']==p and parsed['coupled_records']==[coupled]
    archive=root/'local/v034/portable';saved=save_bundle(data,archive);opened=load_saved(archive,saved['archive_id'])
    assert opened['project']==p and opened['coupled_records']==[coupled]
    a=AppTest.from_string(f'from wingdesignhub.project_ui import library\nlibrary({str(archive)!r})')
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
    b.run(timeout=60);assert not b.exception
    shown=next(x.value for x in b.dataframe if '状态' in x.value.columns)
    assert set(shown['状态'])=={'不适用','未计算','满足','超限'}
    specialist=AppTest.from_string(f'''from pathlib import Path
import json
from wingdesignhub.coupled_ui import show_files
r=json.loads(Path({str(root/'runs'/coupled['run_id']/'result.json')!r}).read_text('utf8'))
show_files(r,{{}},'specialist')
''').run(timeout=60)
    assert not specialist.exception
    specialist_states=next(x.value for x in specialist.dataframe if '状态' in x.value.columns)
    assert set(specialist_states['状态'])==set(shown['状态'])
    card=make_card(p,coupled);assert not card['eligible'] and card['first_level_complete']
    html=card_html(card)
    assert all(label in html for label in ('不适用','未计算','满足','超限'))
    c=AppTest.from_string('''import streamlit as st
from wingdesignhub.first_level_ui import editor
editor(st.session_state['profile'],'reopened')''')
    c.session_state['profile']=p.sizing.first_level;c.run(timeout=30);assert not c.exception and c.toggle[0].value
    write_json(work/'ui.json',{'saved_reopened_equal':True,'archive_ui_no_exception':True,'actual_result_ui_no_exception':True,
        'four_states_visible':True,'specialist_four_states_visible':True,'exceeded_card_excluded':True,'editor_reopened':True,'bundle_bytes':len(data),
        'archive_id':saved['archive_id'],'current_run_id':coupled['run_id'],'source_matches':parsed['current_source_matches']})


if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--root',default='.');a.add_argument('--work',required=True);v=a.parse_args();main(v.root,v.work)
