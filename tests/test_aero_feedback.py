"""Analytic substitutes verify coupling semantics; native evidence is a separate stage run."""
from dataclasses import replace,asdict
from pathlib import Path
import json,math
import pytest
from wingdesignhub.aero_feedback import FeedbackOptions,FeedbackError,MissionAeroTable,AeroFeedback
from wingdesignhub.requirements import DesignProject,MissionRequirement,WeightRequirement
from wingdesignhub.sizing import solve_design
from wingdesignhub.sizing_physics import G,density,geometry,mission
from wingdesignhub.service import write_json


def linear_point(mass,cg,speed,h,roc):
    components={'induced':mass/1e6,'profile':.006+h/1e7,'body':.02,'allowance':.003}
    return {'mass_kg':mass,'cg_x_m':cg,'speed_m_s':speed,'altitude_m':h,'roc_m_s':roc,
            'cd':sum(components.values()),'components':components,'alpha_deg':2.,'elevator_deg':-3.,'point_directory':'analytic-test'}


def test_bilinear_table_and_three_force_balances_independently():
    table=MissionAeroTable(linear_point,900.,2700.,3.2,[1000.,1400.],3,[(60.,3.,[0.,2000.])],15.)
    mass=1100.;h=750.;r=table.query(mass,60.,h,3.)
    assert r['cd']==pytest.approx(.030175)
    assert r['cg_x_m']==pytest.approx((2700.+200.*3.2)/1100.)
    a=DesignProject().sizing;power,cl,drag=table(mass,15.,60.,h,3.,a)
    q=.5*density(h)*60**2;gamma=math.asin(3/60)
    assert q*15*cl==pytest.approx(mass*G*math.cos(gamma))
    assert power*a.propeller_efficiency/60-drag==pytest.approx(mass*G*math.sin(gamma))
    assert drag==pytest.approx(q*15*.030175)
    for mm,v,z,roc in [(999,60,750,3),(1401,60,750,3),(1100,61,750,3),(1100,60,-1,3),(1100,60,750,2)]:
        with pytest.raises(FeedbackError):table.query(mm,v,z,roc)
    with pytest.raises(FeedbackError,match='携带量'):table.cg(899.)
    with pytest.raises(FeedbackError,match='面积'):table(1100.,16.,60.,750.,3.,a)


@pytest.mark.parametrize('data',[{'mass_stations':True},{'altitude_stations':4},{'schedule_cl_ceiling':.8},{'integration_step_s':float('nan')},{'max_iterations':41},{'drag':{'strut_crossflow_cd':-1}}])
def test_invalid_feedback_options(data):
    with pytest.raises(ValueError):FeedbackOptions.from_dict(data)


class AnalyticNative:
    def __init__(self,root,work,p,geo,cg,mass,options):
        self.geometry_work=work/'geometry';self.geometry_work.mkdir(parents=True)
        self.area=geo['wing_area_m2'];self.options=options

    def __call__(self,mass,cg,speed,h,roc):
        r=linear_point(mass,cg,speed,h,roc)
        cl=mass*G*math.sqrt(1-(roc/speed)**2)/(.5*density(h)*speed**2*self.area)
        r['components']['induced']=cl**2/(math.pi*7.5*.8)
        r['components']['body']=.012+self.options.strut_crossflow_cd*.008
        r['cd']=sum(r['components'].values());return r

    def evidence(self):return {'test_substitute':True}


class AnalyticMass:
    def evaluate(self,mass,power,geo,p):
        cats={'airframe':mass*.2,'propulsion':power*.001,'systems':80.,'furniture':50.,'unusable_fuel':geo['tank_capacity_kg']*.02}
        return {'owe_kg':sum(cats.values()),'categories_kg':cats}


@pytest.mark.parametrize('mode,value',[('solve',None),('fixed',1300.),('upper_bound',1500.)])
@pytest.mark.parametrize('kind,distance,duration',[('range_only',8e5,None),('endurance_only',None,14400.),('same_route',8e5,14400.),('transit_loiter',4e5,3600.)])
def test_feedback_weight_task_matrix_and_fuel_cg_closure(tmp_path,mode,value,kind,distance,duration):
    p=replace(DesignProject(),weight=WeightRequirement(mode,value),mission=MissionRequirement(kind,distance,duration)).confirmed()
    model=AnalyticMass();old=solve_design(p,model);assert old['converged']
    feedback=AeroFeedback(tmp_path,tmp_path,p,FeedbackOptions(),AnalyticNative)
    r=solve_design(p,model,40,30,feedback=feedback,initial_summary=old)
    assert r['status']=='concept_checked_with_limits',r
    assert all(r['checks'].values()) and r['iterations'][-1]['stable_rounds']>=3
    assert r['required_loaded_mass_kg']==pytest.approx(r['weights']['owe_kg']+p.payload_kg+r['mission']['takeoff_fuel_kg'],abs=1e-7)
    states=json.loads((tmp_path/'mission_trace.json').read_text('utf-8'))
    for state in states:
        assert state['remaining_fuel_kg']>=0
        assert state['cg_x_m']==pytest.approx(feedback.last['table'].cg(state['mass_kg']))
    ms=r['mission']
    assert ms['takeoff_fuel_kg']==pytest.approx(ms['trip_fuel_from_takeoff_kg']+ms['reserve_fuel_kg'])
    assert ms['block_fuel_kg']==pytest.approx(ms['takeoff_fuel_kg']+ms['taxi_out_fuel_kg'])
    if mode=='fixed':assert r['design_mtow_kg']==value and r['required_loaded_mass_kg']<value
    if kind=='transit_loiter':assert next(x for x in ms['segments'] if x['segment']=='loiter')['path_distance_m']==0
    assert r['trim_checked'] and not r['physical_validation_passed']


def test_feedback_nonconvergence_and_weight_limit_preserved(tmp_path):
    model=AnalyticMass();p=replace(DesignProject(),weight=WeightRequirement('upper_bound',700.)).confirmed()
    old=solve_design(p,model);feedback=AeroFeedback(tmp_path,tmp_path,p,FeedbackOptions(),AnalyticNative)
    r=solve_design(p,model,40,feedback=feedback,initial_summary=old)
    assert r['status']=='constraints_not_met' and r['design_mtow_kg']>700
    other=tmp_path/'one';other.mkdir()
    short=solve_design(p,model,1,feedback=AeroFeedback(tmp_path,other,p,FeedbackOptions(),AnalyticNative),initial_summary=old)
    assert short['status']=='not_converged'


def test_native_failure_is_not_substituted_by_old_polar(tmp_path):
    class Missing(AnalyticNative):
        def __call__(self,*args):raise FeedbackError('aero_table_missing','explicit test gap',station=2)
    p=DesignProject().confirmed();model=AnalyticMass();old=solve_design(p,model)
    r=solve_design(p,model,feedback=AeroFeedback(tmp_path,tmp_path,p,FeedbackOptions(),Missing),initial_summary=old)
    assert r['status']=='out_of_domain' and r['error_code']=='aero_table_missing' and 'mission' not in r


def test_native_evidence_integrity_and_no_path_extraction(tmp_path):
    from wingdesignhub.feedback_evidence import pack_native,check_native
    (tmp_path/'native').mkdir();(tmp_path/'native'/'stdout.log').write_text('real evidence fixture',encoding='utf-8')
    m=pack_native(tmp_path);data=(tmp_path/'native_evidence.zip').read_bytes();check_native(data,m)
    with pytest.raises(ValueError,match='哈希'):check_native(data+b'corrupt',m)
    assert not (tmp_path/'stdout.log').exists()


def test_idle_floor_rejects_unbalanced_native_descent():
    p=DesignProject().confirmed();g=geometry(1200.,100.,p)
    with pytest.raises(ValueError,match='怠速'):
        mission(1200.,g,150000.,p,flight_model=lambda *a:(100.,.3,5.))


def test_table_driven_fuel_against_independent_exponential_solution():
    p=replace(DesignProject(),mission=MissionRequirement('endurance_only',None,7200.),
              assumptions=replace(DesignProject().assumptions,cruise_altitude_m=0.)).confirmed()
    g=geometry(1200.,120.,p);area=g['wing_area_m2'];v=p.assumptions.cruise_speed_m_s
    table=MissionAeroTable(linear_point,900.,2700.,3.2,[900.,1400.],3,[(v,0.,[0.,0.])],area)
    ms=mission(1200.,g,150000.,p,30.,flight_model=table)
    factor=(.5*1.225*v*v)*area*v/p.sizing.propeller_efficiency*p.sizing.bsfc_kg_kwh/3.6e6
    a=factor*.029;b=factor*1e-6;m0=1200.-ms['takeoff_roll_fuel_kg']
    exact=(m0+a/b)*math.exp(-b*7200)-a/b
    assert ms['segments'][0]['end_mass_kg']==pytest.approx(exact,abs=1e-6)
    assert ms['reserve_fuel_kg']==pytest.approx((m0-exact)/7200*p.assumptions.reserve_duration_s,abs=1e-6)
    reloaded=MissionAeroTable.from_dict(table.to_dict())
    assert reloaded.query(1100.,v,0.,0.)==table.query(1100.,v,0.,0.)
    data=table.to_dict();data['branches'][table.key(v,0.)]['points'][0][0]['cg_x_m']+=1
    with pytest.raises(ValueError,match='状态'):MissionAeroTable.from_dict(data)
