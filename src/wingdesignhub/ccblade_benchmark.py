"""Original CCBlade 1.0.0 APC tutorial, with public experimental error retained."""
from pathlib import Path
import re,io
import numpy as np
from .ccblade_adapter import runtime,run_batch,conditions
from .adapters import sha256
from .service import write_json


def official_benchmark(root,work):
    cfg=runtime(root);source=Path(cfg['package'])/'docs/src/tutorial.md';text=source.read_text('utf-8')
    def array(name):return np.loadtxt(io.StringIO(re.search(name+r' = \[(.*?)\]',text,re.S)[1]))
    geom=array('propgeom');exp=array('exp');diameter=.254;rpm=5400.
    request={'official':True,'diameter_m':diameter,'hub_fraction':.1,'blades':2,
        'radial_fraction':geom[:,0].tolist(),'chord_m':(geom[:,1]*diameter/2).tolist(),'twist_deg':geom[:,2].tolist(),
        'airfoil_path':str(Path(cfg['package'])/'data/naca4412.dat'),
        'points':[conditions(j*diameter*rpm/60,0,rpm,0.) for j in exp[:,0]]}
    result=run_batch(root,work,request);rows=[]
    for actual,expected in zip(result['points'],exp):
        if actual['status']!='valid':raise ValueError('官方算例没有有效输出：'+str(actual))
        row={'advance_ratio':expected[0]}
        for k,value in zip(('ct','cp','efficiency'),expected[1:]):
            row[k]={'experimental':float(value),'computed':actual[k],'relative_error':actual[k]/value-1}
        rows.append(row)
    output={'role':'official published benchmark and its experimental comparison; not independent of upstream method development',
        'sources':{'tutorial':{'url':'https://flow.byu.edu/CCBlade.jl/stable/tutorial/','sha256':sha256(source)},
                   'airfoil_sha256':sha256(request['airfoil_path'])},
        'conditions':{'propeller':'APC thin electric 10x5','diameter_m':diameter,'rpm':rpm,'density_kg_m3':1.225,
            'airfoil':'upstream NACA4412 AlphaAF, no added Re/Mach corrections'},
        'rows':rows,'diagnostic_band':.20,'all_within_band':all(abs(r[k]['relative_error'])<.20 for r in rows for k in ('ct','cp','efficiency')),
        'physical_validation_of_aircraft_propeller':False,'metadata':result['metadata']}
    write_json(Path(work)/'comparison.json',output);return output
