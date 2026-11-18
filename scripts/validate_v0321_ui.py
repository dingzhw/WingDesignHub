"""Real completed comparison cards and archive viewing, without a second solve."""
from pathlib import Path
import json
from streamlit.testing.v1 import AppTest
from wingdesignhub.project_archive import read_bundle
from wingdesignhub.jobs import read,atomic,code_identity

root=Path(__file__).resolve().parents[1];work=root/'local/v0321'
state=read(work/'checkpoint.json');assert state['source_hashes']==code_identity()
run=state['warm']['run_id']
source=f"""from pathlib import Path
from wingdesignhub.service import get_results
from wingdesignhub.jobs import read
from wingdesignhub.design_comparison import ComparisonRequest
from wingdesignhub.comparison_ui import show_results
root=Path({str(root)!r})
state=read(root/'local/v0321/checkpoint.json')
show_results(get_results(root,{run!r}),ComparisonRequest.from_dict(state['request']),root)
"""
a=AppTest.from_string(source).run(timeout=60)
assert not a.exception and len(a.metric)==12
bundle=next((work/'archive-warm/local/projects').glob('*.wdh'))
parsed=read_bundle(bundle.read_bytes())
b=AppTest.from_string(f"from wingdesignhub.project_ui import library\nlibrary({str(root)!r})")
b.session_state['opened_archive']=parsed;b.run(timeout=60)
assert not b.exception
out={'real_cards_visible':True,'metric_count':len(a.metric),'reopened_archive_visible':True,
     'no_extra_solve':True,'status':parsed['records'][0]['status']}
atomic(work/'ui-validation.json',out);print(json.dumps(out))
