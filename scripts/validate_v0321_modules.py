"""Real unchanged-solver cold/warm/audit checks for the bounded performance patch."""
from pathlib import Path
import json,os,time,shutil,argparse
from wingdesignhub.ccblade_adapter import run_batch
from wingdesignhub.aircraft_drag import solve_drag
from wingdesignhub.adapters import tool_paths

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'runs/4a326e4aa1144d29ba3cac2ca9d2330a/native'


def read(path):return json.loads(path.read_text('utf-8'))


def main(target):
    target=Path(target).resolve();target.mkdir(parents=True,exist_ok=False)
    os.environ['WDH_COMPUTATION_CACHE_NAMESPACE']='validation-v0321-'+target.name
    batch=next(SOURCE.glob('prop_*/julia/request.json'));request=read(batch)
    outputs={};timing={}
    for name,cache in [('native',False),('cold',True),('warm',True)]:
        start=time.perf_counter();outputs[name]=run_batch(ROOT,target/name,request,use_cache=cache);timing[name]=time.perf_counter()-start
    assert outputs['native']==outputs['cold']==outputs['warm']
    mask=[p['status'] for p in outputs['warm']['points']]
    assert 'out_of_domain' in mask and 'valid' in mask and 'solver_failed' not in mask
    assert read(target/'warm/cache_reuse.json')['cache_hit']
    source=SOURCE/'trial_001/point_000';contract=read(source/'drag_contract.json')
    drag={};dt={};areas={}
    for name,cache in [('native',False),('cold',True),('warm',True)]:
        folder=target/('drag-'+name);folder.mkdir()
        for file in ('aircraft.vsp3','geometry_contract.json','trim_strip_loads.json','drag_contract.json'):
            shutil.copy2(source/file,folder/file)
        start=time.perf_counter()
        result=solve_drag(contract,folder,ROOT,tool_paths(ROOT)['xfoil'],polar_workers=3,use_geometry_cache=cache)
        dt[name]=time.perf_counter()-start;drag[name]=result['components'];areas[name]=read(folder/'drag_geometry.json')
    assert drag['native']==drag['cold']==drag['warm'] and areas['native']==areas['cold']==areas['warm']
    assert read(target/'drag-warm/drag_geometry_cache.json')['cache_hit']
    result={'ccblade_s':timing,'drag_s':dt,'points':len(mask),'valid':mask.count('valid'),'out_of_domain':mask.count('out_of_domain'),
            'batch_identical':True,'drag_identical':True,'physical_model_changed':False}
    (target/'validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('target');main(p.parse_args().target)
