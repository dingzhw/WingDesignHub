"""Synthetic disciplines verify the actual shared sizing loop, not physical accuracy."""
from dataclasses import replace,asdict
from types import SimpleNamespace
import math,json
import pytest
from wingdesignhub.propulsion_feedback import CoupledOptions,PropulsionFeedback
from wingdesignhub.propulsion_model import PropellerMap,PropulsionError
from wingdesignhub.requirements import DesignProject,MissionRequirement,WeightRequirement
from wingdesignhub.sizing import solve_design
from wingdesignhub.sizing_physics import density
from wingdesignhub.service import write_json
from test_aero_feedback import AnalyticNative,AnalyticMass


class Native(AnalyticNative):
    def __init__(self,*args):
        super().__init__(*args);write_json(self.geometry_work/'geometry_contract.json',{'propeller':{'diameter_m':1.9}})


class Engine:
    def __init__(self,rated,policy):
        self.rated_power_w=rated;self.capture=False;self.trace=[];self.evidence={'test_substitute':True}
    def available(self,h,rpm):return self.rated_power_w*density(h)/1.225*.95
    def description(self,*args):return {'test_substitute':True}
    def mission_flow(self,rpm):
        def flow(power,rated,segment,a,h):
            value=power*.25/3.6e6
            if self.capture:self.trace.append({'segment':segment,'shaft_power_w':power,'torque_nm':power/(rpm*math.pi/30),
                'rpm':rpm,'available_power_w':self.available(h,rpm)})
            return value,'synthetic_test_bsfc'
        return flow


def prop_map(root,work,aero,diameter,options,airfoil):
    points=[];speeds=sorted({b['speed_m_s'] for b in aero.tables.values()});heights=sorted({h for b in aero.tables.values() for h in b['altitudes_m']})
    for v in speeds:
        for h in heights:
            for beta,thrust in [(0.,100.),(1.,2500.),(2.,5000.)]:
                pw=thrust*v/.85;q=pw/(options.rpm*math.pi/30)
                points.append({'speed_m_s':v,'altitude_m':h,'rpm':options.rpm,'collective_deg':beta,'status':'valid',
                    'thrust_n':thrust,'torque_nm':q,'shaft_power_w':pw,'efficiency':.85})
    return PropellerMap({'rpm':options.rpm,'diameter_m':diameter,'blades':3,'no_extrapolation':True,'speeds_m_s':speeds,
        'altitudes_m':heights,'collectives_deg':[0.,1.,2.],'points':points,'airfoil':{'test_substitute':True},
        'metadata':{'test_substitute':True},'options':asdict(options),'geometry_role':'synthetic test','max_tip_mach':.7})


def run(p,work,monkeypatch,max_iterations=40):
    monkeypatch.setattr('wingdesignhub.propulsion_service.verify_queries',lambda *a:[{'passed':True,'test_substitute':True}])
    work.mkdir(exist_ok=True);model=AnalyticMass();old=solve_design(p,model)
    feedback=PropulsionFeedback(work,work,p,CoupledOptions(),Native,prop_map,Engine)
    return solve_design(p,model,max_iterations,feedback=feedback,initial_summary=old),feedback


@pytest.mark.parametrize('mode,value',[('solve',None),('fixed',1300.),('upper_bound',1500.)])
@pytest.mark.parametrize('kind,distance,duration',[('range_only',8e5,None),('endurance_only',None,14400.),('same_route',8e5,14400.),('transit_loiter',4e5,3600.)])
def test_coupled_three_weights_four_tasks(tmp_path,monkeypatch,mode,value,kind,distance,duration):
    p=replace(DesignProject(),weight=WeightRequirement(mode,value),mission=MissionRequirement(kind,distance,duration)).confirmed()
    r,f=run(p,tmp_path,monkeypatch)
    assert r['status']=='concept_checked_with_limits',r
    assert all(r['checks'].values()) and r['iterations'][-1]['stable_rounds']>=3
    ms=r['mission'];g=r['geometry'];ledger=r['cg']
    assert ledger['loaded_mass_kg']==pytest.approx(r['weights']['owe_kg']+p.payload_kg+ms['takeoff_fuel_kg'],abs=1e-7)
    assert ms['block_fuel_kg']==pytest.approx(sum(ms['block_fuel_by_method_kg'].values()),abs=1e-7)
    assert ms['takeoff_fuel_kg']==pytest.approx(ms['trip_fuel_from_takeoff_kg']+ms['reserve_fuel_kg'])
    assert r['iterations'][-1]['residuals']['power_weight_coupling']<1e-4
    assert f.history[-1]['weights']['categories_kg']['propulsion']==pytest.approx(f.history[-1]['mass_model_power_input_w']*.001)
    if mode=='fixed':assert r['design_mtow_kg']==value and r['mass_budget_margin_kg']>0
    if kind=='transit_loiter':assert next(x for x in ms['segments'] if x['segment']=='loiter')['path_distance_m']==0
    for state in json.loads((tmp_path/'mission_trace.json').read_text('utf-8')):
        assert state['cg_x_m']==pytest.approx(f.last['table'].cg(state['mass_kg']))


def test_engine_mass_fuel_geometry_link_and_infeasible_upper_limit(tmp_path,monkeypatch):
    p=DesignProject().confirmed();a,fa=run(p,tmp_path/'a',monkeypatch)
    q=replace(p,payload_kg=p.payload_kg+60).confirmed();b,fb=run(q,tmp_path/'b',monkeypatch)
    for path in [('design_mtow_kg',),('power','installed_power_w'),('mission','block_fuel_kg'),('geometry','wing_area_m2')]:
        x=a;y=b
        for k in path:x=x[k];y=y[k]
        assert y>x
    assert b['weights']['categories_kg']['propulsion']>a['weights']['categories_kg']['propulsion']
    bad=replace(p,weight=WeightRequirement('upper_bound',700.)).confirmed();r,_=run(bad,tmp_path/'bad',monkeypatch)
    assert r['status']=='constraints_not_met' and r['design_mtow_kg']>700 and not r['checks']['mtow_upper_bound']
    short,_=run(p,tmp_path/'short',monkeypatch,1);assert short['status']=='not_converged'


def test_bad_options_and_failed_engine_domain_no_success_fallback(tmp_path,monkeypatch):
    for data in [{'low_load_policy':'silent'},{'aero':{'integration_step_s':10}}]:
        with pytest.raises(ValueError):CoupledOptions.from_dict(data)
    class FailedEngine(Engine):
        def mission_flow(self,rpm):
            def fail(*args):raise PropulsionError('engine_sfc_out_of_domain','test missing map')
            return fail
    p=DesignProject().confirmed();model=AnalyticMass();old=solve_design(p,model)
    f=PropulsionFeedback(tmp_path,tmp_path,p,CoupledOptions(),Native,prop_map,FailedEngine)
    r=solve_design(p,model,feedback=f,initial_summary=old)
    assert r['status']=='out_of_domain' and r['error_code']=='engine_sfc_out_of_domain' and 'mission' not in r
