"""Single-owner drag ledger at one immutable inviscid trim state."""
from dataclasses import asdict, dataclass
from pathlib import Path
import json
import math
import sys
import numpy as np
from .adapters import execute
from .service import write_json
from .xfoil_polars import PolarError, PolarSpec, interpolate, run_polar

LIMITS=[
    '常规单发模板、定常附着流、Mach≤0.3、|迎角|≤6°、|舵偏|≤10°；局部 Re 20万–2000万、|cl|≤1.2 是接口边界，并非失速判据。',
    '沿用 AVL 无黏配平的条带 cl 与自由流 Re/Mach；XFOIL 使用 OpenVSP 导出的实际翼型，平尾按同一铰链/舵偏变形。',
    '总阻力由远场诱导阻力、暴露翼尾剖面阻力、非升力部件及显式修正组成；平尾与配平诱导阻力只计一次。',
    '湿面积由原生 CompGeom 计算；翼尾暴露面积按弯度中面采样，支柱投影按机体 x 方向。舵偏对遮蔽边界的微小变化未建模。',
    '非升力部件用全湍流平板摩阻及 Hoerner 顺流体形状系数；支柱采用投影面积与明确假设的横流阻力系数，短整流罩/桨帽存在模型不确定性。',
    '接合部、冷却与粗糙度修正是未校准的显式预算；螺旋桨推力、滑流、旋转桨帽效应和风车阻力另由推进模块处理。',
    '本版单向叠加阻力，不回写升力/俯仰矩或重新黏性配平；轴向推力平衡和总体任务燃油回写留给 V0.2.5。',
    '极曲线缺点/不收敛、缓存损坏或越界不填零、不外推；接口数值验收与整机阻力物理验证分开。',
]


@dataclass(frozen=True)
class DragOptions:
    panels: int = 240
    re_stations: int = 3
    cl_step: float = .1
    ncrit: float = 9.
    trip_top: float = 1.
    trip_bottom: float = 1.
    area_samples: int = 12
    geometry_tessellation: int = 1
    strut_crossflow_cd: float = 1.2
    junction_cd: float = .0015
    cooling_cd: float = .001
    roughness_cd: float = .0005
    cache_only: bool = False

    def validate(self):
        for name, choices in [('panels',(160,240)),('re_stations',(3,5)),('area_samples',(8,12,24)),('geometry_tessellation',(1,2))]:
            if type(getattr(self,name)) is not int or getattr(self,name) not in choices:raise ValueError('阻力离散参数无效：'+name)
        if self.cl_step not in (.1,.05):raise ValueError('cl 步长须为 0.1 或 0.05')
        if type(self.cache_only) is not bool:raise ValueError('cache_only 须为布尔值')
        for k,lo,hi in [('strut_crossflow_cd',.1,2.),('junction_cd',0,.02),('cooling_cd',0,.02),('roughness_cd',0,.02)]:
            x=getattr(self,k)
            if type(x) not in (float,int) or not math.isfinite(x) or not lo<=x<=hi:raise ValueError('阻力假设越界：'+k)
        PolarSpec(1e6,.1,(0.,),self.ncrit,self.trip_top,self.trip_bottom,panels=self.panels).validate()


def make_drag_contract(trim_record, final_contract, options=None):
    o=DragOptions(**options) if isinstance(options,dict) else options or DragOptions();o.validate()
    if trim_record.get('mode')!='aircraft_trim' or trim_record['status']!='trim_checked_with_limits' or not trim_record['summary']['trim']['converged']:
        raise ValueError('阻力计算需要已通过实际残差检查的配平结果')
    s=trim_record['summary']
    for key in ('references','flow','options','flight_state'):
        if final_contract[key]!=s[key]:raise ValueError('配平终态与摘要不一致：'+key)
    if final_contract['options']['aileron_deg'] or final_contract['options']['rudder_deg'] or final_contract['flow']['beta_deg']:
        raise ValueError('本版阻力接口接收对称纵向配平')
    return {'schema_version':1,'model':'trim_drag_ledger_v1','trim_run_id':trim_record['run_id'],
            'geometry_run_id':trim_record['parent_run_id'],'sizing_run_id':trim_record['sizing_run_id'],
            'references':s['references'],'flow':s['flow'],'flight_state':s['flight_state'],
            'controls':s['controls'],'trim_options':s['options'],'induced_cd':s['coefficients']['CDff'],
            'lift_coefficient':s['coefficients']['CLtot'],'options':asdict(o),'limits':LIMITS,
            'correction_source':'uncalibrated conceptual allowances, user-visible assumptions; no aircraft data fitted',
            'ownership':{'induced':'AVL CDff once','profile':'XFOIL CD over exposed wing/tail planform',
                         'body':'Cf FF Swet for longitudinal bodies; crossflow CD Aprojected for struts',
                         'allowances':'junction/cooling/roughness CD; each once'},
            'excluded_from_sum':['legacy sizing CD0','AVL CDtot/CDind duplicate','extra trim drag','wing/tail skin-friction duplication','propulsive force']}


def body_friction(reynolds, fineness):
    if not math.isfinite(reynolds) or reynolds<5e5 or not math.isfinite(fineness) or fineness<1:
        raise ValueError('顺流体公式范围：Re≥50万、长细比≥1')
    # Same average Cf and streamlined-body FF as OpenVSP 3.56 ParasiteDragMgr.cpp.
    return .455/math.log10(reynolds)**2.58, 1+1.5/fineness**1.5+7/fineness**3


def finish_ledger(rows, q, area):
    owners={'lifting_system':'induced',**{n:'profile' for n in ('MainWing','HorizontalTail','VerticalTail')},
            **{n:'body' for n in ('Fuselage','Spinner','NoseFairing','LeftFairing','RightFairing','NoseStrut','LeftStrut','RightStrut')},
            **{n:'allowance' for n in ('junction','cooling','roughness')}}
    keys=[(r['component'],r['contribution']) for r in rows]
    if len(set(keys))!=len(keys):raise ValueError('阻力账目存在重复归属')
    if set(keys)!=set(owners.items()):raise ValueError('阻力账目缺项或部件归属错误')
    if q<=0 or area<=0 or not np.isfinite([q,area,*[r['cd'] for r in rows]]).all() or any(r['cd']<0 for r in rows):
        raise ValueError('阻力账目存在无效值')
    rows=[{**r,'drag_n':r['cd']*q*area} for r in rows]
    return {'cd_total':math.fsum(r['cd'] for r in rows),'drag_n':math.fsum(r['drag_n'] for r in rows), 'rows':rows}


def solve_drag(contract, work, root, xfoil):
    work=Path(work);o=DragOptions(**contract['options']);f=contract['flow'];ref=contract['references']
    execute([sys.executable,'-X','utf8','-m','wingdesignhub.drag_geometry_worker',str(work)],work,timeout=180)
    geom=json.loads((work/'drag_geometry.json').read_text('utf-8'))
    gc=json.loads((work/'geometry_contract.json').read_text('utf-8'))
    strips=json.loads((work/'trim_strip_loads.json').read_text('utf-8'))['strips']
    exposure={(s['surface'],s['strip_id']):s for s in geom['strips']}
    if len(exposure)!=len(strips):raise ValueError('暴露面积与条带数量不一致')
    re_per_m=f['density_kg_m3']*f['speed_m_s']/f['dynamic_viscosity_pa_s'];rows=[];queries=[];coverage=[]
    rows.append({'component':'lifting_system','contribution':'induced','method':'AVL CDff at accepted trim','cd':contract['induced_cd']})
    for name in ('MainWing','HorizontalTail','VerticalTail'):
        active=[s for s in strips if s['surface'].replace(' (YDUP)','')==name and exposure[(s['surface'],s['strip_id'])]['exposed_area_m2']>0]
        if not active:raise ValueError('升力面没有暴露面积：'+name)
        res=[s['chord_m']*re_per_m for s in active];cls=[s['cl'] for s in active]
        if min(res)<2e5 or max(res)>2e7 or min(cls)<-1.2 or max(cls)>1.2:
            raise PolarError('polar_out_of_domain','条带超出本版 XFOIL 范围', surface=name, reynolds=[min(res),max(res)], cl=[min(cls),max(cls)])
        # Cover each queried cell; do not demand unrelated near-stall padding points.
        lo=max(-1.2,math.floor(min(cls)/o.cl_step)*o.cl_step)
        hi=min(1.2,math.ceil(max(cls)/o.cl_step)*o.cl_step)
        grid=tuple(round(float(v),8) for v in np.arange(lo,hi+o.cl_step/2,o.cl_step))
        re_grid=np.geomspace(min(res),max(res),o.re_stations);re_grid[0]=min(res);re_grid[-1]=max(res)
        flap=contract['trim_options']['elevator_deg'] if name=='HorizontalTail' else 0.
        polars=[]
        for i,reynolds in enumerate(re_grid):
            spec=PolarSpec(float(reynolds),f['mach'],grid,o.ncrit,o.trip_top,o.trip_bottom,flap,.7,o.panels)
            try:polar=run_polar(work/geom['airfoils'][name]['file'],spec,xfoil,work/'polars'/name/str(i),Path(root)/'local'/'cache'/'xfoil',o.cache_only)
            except PolarError as exc:
                exc.context.update(surface=name,station=i);raise
            polars.append(polar)
        coverage.append({'surface':name,'reynolds':list(map(float,re_grid)),'cl_grid':list(grid),'flap_deg':flap,
                         'mach':f['mach'],'polar_count':len(polars),'cache_hits':sum(p['cache_hit'] for p in polars),
                         'recovered_points':sum(len(p.get('recovery',[])) for p in polars),
                         'foil_sha256':geom['airfoils'][name]['sha256']})
        total=0.;area=0.
        for s in active:
            a=exposure[(s['surface'],s['strip_id'])]['exposed_area_m2'];reynolds=s['chord_m']*re_per_m
            query=interpolate(polars,reynolds,s['cl']);cd=query['cd']*a/ref['area_m2'];total+=cd;area+=a
            queries.append({'surface':s['surface'],'strip_id':s['strip_id'],'cl':s['cl'],'reynolds':reynolds,
                            'area_m2':a,'cd_aircraft':cd,**query})
        rows.append({'component':name,'contribution':'profile','method':'XFOIL exposed strips','cd':total,'exposed_area_m2':area})
    dimensions={'Fuselage':(gc['fuselage']['length_m'],gc['fuselage']['length_m']/math.sqrt(gc['fuselage']['width_m']*gc['fuselage']['height_m'])),
                'Spinner':(.45,1.5),**{name:(gc['gear']['fairing_length_m'],gc['gear']['fairing_fineness']) for name in ('NoseFairing','LeftFairing','RightFairing')}}
    for name,(length,fr) in dimensions.items():
        cf,ff=body_friction(re_per_m*length,fr);wet=geom['wetted_area_m2'][name]
        rows.append({'component':name,'contribution':'body','method':'Schlichting average Cf; Hoerner streamlined body FF',
                     'cf':cf,'form_factor':ff,'reynolds':re_per_m*length,'fineness':fr,'wet_area_m2':wet,'cd':cf*ff*wet/ref['area_m2']})
    for name,area in geom['strut_projected_area_m2'].items():
        rows.append({'component':name,'contribution':'body','method':'declared crossflow CD times exposed frontal area',
                     'projected_area_m2':area,'crossflow_cd':o.strut_crossflow_cd,'cd':o.strut_crossflow_cd*area/ref['area_m2']})
    for name in ('junction','cooling','roughness'):
        rows.append({'component':name,'contribution':'allowance','method':contract['correction_source'],'cd':getattr(o,name+'_cd')})
    ledger=finish_ledger(rows,f['dynamic_pressure_pa'],ref['area_m2'])
    strut_fraction=sum(r['cd'] for r in rows if r['component'].endswith('Strut'))/ledger['cd_total']
    write_json(work/'drag_ledger.json',ledger);write_json(work/'profile_queries.json',queries);write_json(work/'polar_coverage.json',coverage)
    return {'status':'drag_checked_with_limits','passed':True,'ledger':ledger,'flow':f,'references':ref,
            'flight_state':contract['flight_state'],'options':contract['options'],'polar_coverage':coverage,
            'lift_to_drag':contract['lift_coefficient']/ledger['cd_total'],
            'strut_drag_fraction':strut_fraction,
            'diagnostics':[f'支柱横流假设贡献总阻力的 {strut_fraction:.1%}；概念外形和系数需在任务反馈时作为不确定性保留。'],
            'components':{k:sum(r['cd'] for r in rows if r['contribution']==k) for k in ('induced','profile','body','allowance')},
            'mission_polar_updated':False,'viscous_retrimmed':False,'axial_force_balanced':False,
            'physical_validation_passed':False,'limits':LIMITS}
