"""Serial, frozen-source first-level release evidence. Native tools are optional stages."""
from pathlib import Path
from dataclasses import replace
import argparse,json,time,math
from wingdesignhub.service import write_json
from wingdesignhub.jobs import code_identity
from wingdesignhub.requirements import DesignProject,WeightRequirement,MissionRequirement
from wingdesignhub.first_level_config import default_first_level
from wingdesignhub.layout import default_layout
from wingdesignhub.sizing_physics import flight_power,geometry
from wingdesignhub.field_performance import takeoff,landing


def make_project(**changes):
    c=default_first_level();c.update(changes)
    p=DesignProject(name='V0.3.4 需求驱动单发概念方案')
    return replace(p,sizing=replace(p.sizing,layout=default_layout(),first_level=c)).confirmed()


def main(root,work,stage):
    root=Path(root).resolve();work=Path(work).resolve();work.mkdir(parents=True,exist_ok=True)
    frozen=code_identity();f=work/'freeze.json'
    if f.exists():assert json.loads(f.read_text('utf8'))==frozen,'frozen sources changed'
    else:write_json(f,frozen)
    if stage=='fixed':
        ref=json.loads((root/'validation/first_level_reference.json').read_text('utf8'));rows=[]
        for case in ref['cases']:
            p=make_project();c=p.sizing.first_level.copy();h=case['pressure_altitude_ft']*.3048
            temp=(case['temperature_f']-32)*5/9;c.update(field_altitude_m=h,temperature_delta_k=temp-(15-.0065*h))
            a=replace(p.sizing,aspect_ratio=35**2/170,first_level=c)
            if case['id']=='takeoff_clean':c.update(takeoff_cl_max=a.cl_max_clean,takeoff_cd_increment=0.)
            p=replace(p,sizing=a).confirmed();mass=case['mass_lb']*.45359237;s=170*.3048**2;power=180*745.699872
            if case['id']=='takeoff_clean':
                val=takeoff(mass,s,power,p,diameter_m=76*.0254);metric=val['total_m']/.3048;interval=case['distance_ft_interval']
            elif case['id']=='landing':
                val=landing(mass,s,p);metric=val['total_m']/.3048;interval=case['distance_ft_interval']
            else:
                speed=case['speed_ias_kts']*.514444444444;lo=0.;hi=10.
                for _ in range(50):
                    mid=(lo+hi)/2
                    if flight_power(mass,s,speed,0.,mid,a)[0]>power:hi=mid
                    else:lo=mid
                metric=(lo+hi)/2/.00508;interval=case['roc_fpm_interval'];val={'roc_m_s':(lo+hi)/2,'speed_m_s':speed}
            rows.append({'case':case,'model':val,'model_in_source_units':metric,'reference_interval':interval,
                'relative_difference_interval':[metric/interval[1]-1,metric/interval[0]-1],
                'project':p.to_dict(),'role':ref['role'],'physical_validation_passed':False})
        base=make_project();old=root/'runs/4e6c872c43534117ae70bfa585f7eba4'
        s=json.loads((old/'summary.json').read_text('utf8'))
        from wingdesignhub.first_level import evaluate
        sensitivities=[]
        for name,kw in [('baseline',{}),('disk_low',{'disk_power_factor':.55}),('disk_high',{'disk_power_factor':.75}),
                         ('braking_low',{'braking_friction':.2}),('moment_zero',{'moment_bias_abs':0.}),('hot_high',{'field_altitude_m':2000.,'temperature_delta_k':20.})]:
            q=make_project(**kw);sensitivities.append({'name':name,'first_level':evaluate(s,q)})
        write_json(work/'fixed.json',{'reference_registration':ref,'public_rows':rows,'historical_fixed_run':old.name,
            'fixed_sensitivities':sensitivities,'basis':'fixed geometry/mass/power; not rerun native aerodynamic evidence'})
    elif stage=='sizing':
        assert (work/'fixed.json').is_file()
        from wingdesignhub.sizing_service import run_sizing
        rows=[]
        cases=[('baseline',make_project()),('landing_tight',make_project(landing_limit_m=500.)),
               ('takeoff_tight',make_project(takeoff_limit_m=550.)),('impossible_takeoff',make_project(takeoff_limit_m=100.))]
        p=make_project();cases += [('fixed_mass',replace(p,weight=WeightRequirement('fixed',1500.)).confirmed()),
           ('upper_bound',replace(p,weight=WeightRequirement('upper_bound',900.)).confirmed()),
           ('endurance',replace(p,mission=MissionRequirement('endurance_only',None,14400.)).confirmed()),
           ('loiter',replace(p,mission=MissionRequirement('transit_loiter',400000.,3600.)).confirmed())]
        for name,q in cases:
            start=time.perf_counter();r=run_sizing(q,root);rows.append({'name':name,'elapsed_s':time.perf_counter()-start,'record':r})
            write_json(work/'sizing.json',rows);print(name,r['status'],r.get('summary',{}).get('design_mtow_kg'),flush=True)
    elif stage=='coupled':
        from wingdesignhub.coupled_service import run_coupled
        rows=json.loads((work/'sizing.json').read_text('utf8'));seed=rows[0]['record'];assert seed['summary']['converged']
        p=DesignProject.from_dict(json.loads((root/'runs'/seed['run_id']/'input.json').read_text('utf8')))
        start=time.perf_counter();r=run_coupled(p,root,seed['run_id']);write_json(work/'coupled.json',r)
        write_json(work/'coupled_time.json',{'elapsed_s':time.perf_counter()-start})
        print(r['status'],r.get('error',''),flush=True)
        assert r.get('summary',{}).get('converged'), '原生代表任务未收敛：'+r.get('error',r['status'])
    assert code_identity()==frozen,'source changed during formal validation'


if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--root',default='.');a.add_argument('--work',required=True)
    a.add_argument('--stage',choices=['fixed','sizing','coupled'],required=True);v=a.parse_args();main(v.root,v.work,v.stage)
