"""Serial checks of valid CCBlade cache batches and real saved scheme viewing."""
from pathlib import Path
import argparse,json,time,math,os
from wingdesignhub.jobs import read,atomic,code_identity

ROOT=Path(__file__).resolve().parents[1];WORK=ROOT/'local/v032'


def main(action):
    state=read(WORK/'checkpoint.json');assert state['source_hashes']==code_identity()
    run=state['warm']['run_id'];work=ROOT/'runs'/run
    if action=='ccblade':
        from wingdesignhub.ccblade_adapter import run_batch
        os.environ['WDH_COMPUTATION_CACHE_NAMESPACE']='validation-v032-valid-prop'
        source=next((work/'native').glob('prop_*/julia'))
        request=read(source/'request.json');result=read(source/'result.json')
        indices=[i for i,p in enumerate(result['points']) if p['status']=='valid'][:2]
        assert len(indices)==2
        request['points']=[request['points'][i] for i in indices]
        w=WORK/'ccblade-cache';w.mkdir(exist_ok=False);times={};results=[]
        for mode in ('cold','warm'):
            start=time.perf_counter();data=run_batch(ROOT,w/mode,request,use_cache=True)
            times[mode]=time.perf_counter()-start;results.append(data)
        assert results[0]==results[1]
        assert read(w/'warm/cache_reuse.json')['cache_hit']
        for p in results[0]['points']:
            assert p['status']=='valid' and abs(p['shaft_power_w']-p['torque_nm']*p['rpm']*math.pi/30)<1e-8
        atomic(w/'validation.json',{'times_s':times,'identical':True,'power_torque_identity':True,
            'scope':'two valid synthetic propeller conditions; full maps with out-of-domain masks remain uncached'})
        print(times,flush=True)
    elif action=='archive':
        from wingdesignhub.project_archive import read_bundle,build_bundle,save_bundle
        from wingdesignhub.service import get_results
        from wingdesignhub.requirements import DesignProject
        from unittest.mock import patch
        from streamlit.testing.v1 import AppTest
        r=get_results(ROOT,run);seed=get_results(ROOT,r['parent_run_id']);p=DesignProject.from_dict(read(work/'input.json'))
        original=Path.read_bytes;t=time.perf_counter()
        with patch.object(Path,'read_bytes',lambda path:(_ for _ in ()).throw(AssertionError('native ZIP read during portable export'))
                          if path.name=='native_evidence.zip' else original(path)):
            blob=build_bundle(p,ROOT,seed,coupled_record=r,current_run_id=run,profile='portable')
        build_s=time.perf_counter()-t;parsed=read_bundle(blob)
        destination=WORK/'archive';index=save_bundle(blob,destination)
        # Read the actual saved file; do not recompute or rewrite any old run.
        paths=list((destination/'local/projects').glob('*.wdh'));assert len(paths)==1
        reopened=read_bundle(paths[0].read_bytes())
        assert reopened['coupled_records'][0]==r and reopened['manifest']['current_run_id']==run
        assert len(blob)<20*1024*1024 and reopened['evidence_status']=='detached_not_verified'
        a=AppTest.from_string(f"from wingdesignhub.project_ui import library\nlibrary({str(ROOT)!r})")
        a.session_state['opened_archive']=reopened;a.run(timeout=60)
        assert not a.exception and len(a.get('plotly_chart'))>=1
        old=next((ROOT/'local/v031a/representative/local/projects').glob('*.wdh'))
        legacy=read_bundle(old.read_bytes());assert legacy['coupled_records'][0]['run_id']==state['baseline']
        data={'portable_bytes':len(blob),'portable_build_s':build_s,'native_zip_not_read':True,'save_reopen_identical':True,
              'final_geometry_component_visible':True,'ui_no_exception':True,'legacy_v031a_readable':True,
              'historical_seed_role':'same immutable V0.3.1 seed used for cold and warm performance control; archived provenance stays historical'}
        atomic(WORK/'archive-validation.json',data);print(data,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['ccblade','archive']);main(parser.parse_args().action)
