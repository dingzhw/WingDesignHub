"""Native Julia batches and locally generated full-scale airfoil inputs."""
from pathlib import Path
from dataclasses import asdict
import json,math,shutil,tomllib
import numpy as np
from .adapters import execute,sha256,tool_paths
from .service import write_json
from .sizing_physics import density
from .xfoil_polars import PolarSpec,run_polar
from .propulsion_model import PropellerMap,PropulsionError


def runtime(root):
    path=Path(root)/'local/propulsion-tools.json'
    if not path.is_file():raise PropulsionError('ccblade_not_configured','请先配置本机Julia与CCBlade 1.0.0环境（local/propulsion-tools.json）')
    data=json.loads(path.read_text('utf-8'))
    for k in ('julia','project','package'):
        if not Path(data[k]).exists():raise PropulsionError('ccblade_not_configured','找不到已配置的CCBlade环境：'+k)
    if tomllib.loads((Path(data['package'])/'Project.toml').read_text('utf-8'))['version']!='1.0.0':raise PropulsionError('ccblade_version_mismatch','仅验证CCBlade 1.0.0')
    return data


def conditions(speed,height,rpm,collective):
    temp=288.15-.0065*height
    return {'speed_m_s':float(speed),'altitude_m':float(height),'rpm':float(rpm),'collective_deg':float(collective),
        'density_kg_m3':density(height),'sound_speed_m_s':math.sqrt(1.4*287.05*temp),
        'viscosity_pa_s':1.716e-5*(temp/273.15)**1.5*(273.15+110.4)/(temp+110.4)}


def toml_request(data):
    # These typed, internally built records contain primitives/arrays only.
    def value(v):return json.dumps(v,ensure_ascii=False,allow_nan=False)
    lines=[k+' = '+value(v) for k,v in data.items() if not isinstance(v,dict) and k!='points']
    for k,v in data.items():
        if isinstance(v,dict):lines+=['['+k+']']+[key+' = '+value(val) for key,val in v.items()]
    for point in data['points']:lines+=['[[points]]']+[k+' = '+value(v) for k,v in point.items()]
    return '\n'.join(lines)+'\n'


def run_batch(root,work,request):
    cfg=runtime(root);work=Path(work);work.mkdir(parents=True,exist_ok=False)
    write_json(work/'request.json',request)
    (work/'input.toml').write_text(toml_request(request),encoding='utf-8')
    worker=Path(__file__).with_name('ccblade_worker.jl');shutil.copy2(worker,work/'worker.jl')
    execute([cfg['julia'],'--startup-file=no','--compiled-modules=existing','--threads=1',
             '--project='+cfg['project'],str(work/'worker.jl'),str(work/'input.toml'),str(work/'output.toml')],work,timeout=300)
    result=tomllib.loads((work/'output.toml').read_text('utf-8'))
    if len(result['points'])!=len(request['points']):raise PropulsionError('ccblade_output_invalid','CCBlade输出点数不符')
    result['metadata'].update(worker_sha256=sha256(work/'worker.jl'),julia_sha256=sha256(cfg['julia']),
        environment_sha256={n:sha256(Path(cfg['project'])/n) for n in ('Project.toml','Manifest.toml')})
    write_json(work/'result.json',result);return result


def full_scale_airfoil(root,work):
    work=Path(work);work.mkdir(parents=True,exist_ok=False);exe=tool_paths(root)['xfoil']
    execute([exe],work,stdin='PLOP\nG\n\nNACA 4412\nPSAV foil.dat\n\nQUIT\n',timeout=60)
    if not (work/'foil.dat').is_file():raise PropulsionError('propeller_airfoil_missing','XFOIL未生成NACA4412坐标')
    reynolds=[500000.,750000.,1000000.,2000000.];polars=[]
    for re in reynolds:
        spec=PolarSpec(re,0.,tuple(round(x,2) for x in np.arange(-.6,1.201,.1)),panels=240)
        result=run_polar(work/'foil.dat',spec,exe,work/f're_{re:.0f}',cache=Path(root)/'local/xfoil-cache')
        rows=sorted(result['rows'],key=lambda r:r['alpha_deg']);polars.append(rows)
    low=max(r[0]['alpha_deg'] for r in polars);high=min(r[-1]['alpha_deg'] for r in polars)
    alpha=np.linspace(low,high,81)
    table={'reynolds':reynolds,'alpha_deg':alpha.tolist(),
           'cl':[np.interp(alpha,[r['alpha_deg'] for r in rows],[r['cl'] for r in rows]).tolist() for rows in polars],
           'cd':[np.interp(alpha,[r['alpha_deg'] for r in rows],[r['cd'] for r in rows]).tolist() for rows in polars]}
    write_json(work/'table.json',table);return table


def request_base(options,diameter,airfoil):
    return {**asdict(options),'diameter_m':diameter,'airfoil':airfoil,
            'chord75_over_radius':(options.root_chord_m+(options.tip_chord_m-options.root_chord_m)*(.75-.2)/.8)/(diameter/2)}


def build_map(root,work,aero,diameter,options,airfoil=None):
    work=Path(work);work.mkdir(parents=True,exist_ok=False)
    heights=sorted({h for b in aero.tables.values() for h in b['altitudes_m']})
    heights=[heights[0]] if heights[0]==heights[-1] else np.linspace(heights[0],heights[-1],options.altitude_stations).tolist()
    speeds=sorted({b['speed_m_s'] for b in aero.tables.values()})
    tip_mach=max(math.hypot(v,options.rpm*math.pi/30*diameter/2)/conditions(v,h,options.rpm,0)['sound_speed_m_s'] for v in speeds for h in heights)
    if tip_mach>.75:raise PropulsionError('propeller_tip_mach_exceeded','桨尖螺旋Mach超出本模型0.75上限',tip_mach=tip_mach,rpm=options.rpm,diameter_m=diameter)
    airfoil=airfoil or full_scale_airfoil(root,work/'airfoil')
    count=round((options.collective_max_deg-options.collective_min_deg)/options.collective_step_deg)+1
    collectives=np.linspace(options.collective_min_deg,options.collective_max_deg,count).tolist()
    request=request_base(options,diameter,airfoil)
    request['points']=[conditions(v,h,options.rpm,beta) for v in speeds for h in heights for beta in collectives]
    result=run_batch(root,work/'julia',request)
    data={'rpm':options.rpm,'diameter_m':diameter,'blades':options.blades,'hub_fraction':.2,
          'speeds_m_s':speeds,'altitudes_m':heights,'collectives_deg':collectives,'no_extrapolation':True,
          'options':asdict(options),'airfoil':airfoil,'metadata':result['metadata'],'points':result['points'],'max_tip_mach':tip_mach,
          'geometry_role':'independent synthetic full-scale blade; diameter inherited from aircraft, not a scaled APC propeller'}
    write_json(work/'map.json',data);return PropellerMap(data)
