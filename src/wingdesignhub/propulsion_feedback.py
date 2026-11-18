"""Engine/propeller/fuel disciplines in the existing overall sizing iteration."""
from dataclasses import dataclass, field, asdict
from pathlib import Path
import hashlib,json,math,time
import numpy as np
from .aero_feedback import FeedbackOptions,FeedbackError,MissionAeroTable,dry_ledger,feedback_schedule
from .propulsion_model import PropulsionOptions,PropulsiveFlight,propulsion_constraints,PropulsionError
from .engine_fuel import EngineFuelModel
from .sizing_physics import mission,mission_legs
from .sizing import cg_ledger
from .service import write_json


@dataclass(frozen=True)
class CoupledOptions:
    aero: FeedbackOptions=field(default_factory=FeedbackOptions)
    propeller: PropulsionOptions=field(default_factory=PropulsionOptions)
    low_load_policy: str='base_bsfc'

    @classmethod
    def from_dict(cls,data):
        data=dict(data)
        if 'aero' in data:data['aero']=FeedbackOptions.from_dict(data['aero'])
        if 'propeller' in data:data['propeller']=PropulsionOptions.from_dict(data['propeller'])
        obj=cls(**data);obj.validate();return obj

    def validate(self):
        self.aero.validate();self.propeller.validate()
        if self.aero.integration_step_s!=self.propeller.integration_step_s:raise ValueError('总体与推进积分步长须一致')
        if self.low_load_policy not in ('base_bsfc','reject'):raise ValueError('未知低负荷耗油策略')


LIMITS=[
    '需求驱动的重量—燃油—功率迭代：每轮FAST-GA经验重量、OpenVSP外形、AVL配平/XFOIL阻力重算；发动机按连续额定功率定尺寸，尚未离散选具体商品发动机。',
    '推进采用规定转速、理想恒速变距、轴向均匀入流；CCBlade合成桨叶，直径继承模板。桨图缺点及边界不跨越，桨尖Mach≤0.75，无滑流/安装损失或调速器瞬态。',
    '通用发动机转速/高度功率与扭矩/RPM耗油图来自FAST-GA 1.4.0；图内爬升富油系数1.15，其他空中段为1，尚无目标型号独立台架标定。',
    '低负荷可显式采用基础BSFC并单列油量，或严格拒绝；地面/滑跑用基础BSFC。高负荷和转速耗油图越界拒绝；高度只修正可用功率。',
    '气动沿既有小迎角、单向黏性阻力叠加边界；推力沿航迹通过CG，无动力俯仰矩。任务为标准大气、无风的准定常直线段。',
    '储备以平均巡航油耗携带一次，不增加已飞航时/航程；固定重量保留规定设计值，实际装载及剩余预算单列，上限模式不裁剪结果。',
    '部件站位及外形比例是概念假设；经验发动机重量、携油及翼面积联动，不包含真实发动机包络适配、结构定尺寸回写、起降距离或操稳包线。',
]


def mission_kwargs(flight,schedule,p):
    engine=flight.engine;rpm=flight.propeller.rpm
    return {'flight_model':flight,'schedule':schedule,'available_power':lambda h:engine.available(h,rpm),
            'fuel_flow_model':engine.mission_flow(rpm),'fuel_description':engine.description(rpm,p.sizing.bsfc_kg_kwh)}


class PropulsionFeedback:
    def __init__(self,root,work,project,options,native_factory=None,map_factory=None,engine_factory=None):
        from .feedback_native import NativeFeedbackGeometry
        from .ccblade_adapter import build_map
        self.root=Path(root);self.work=Path(work);self.p=project;self.options=options;options.validate()
        from functools import partial
        self.native_factory=native_factory or partial(NativeFeedbackGeometry,execution_mode=options.aero.execution_mode)
        self.map_factory=map_factory or partial(build_map,use_cache=options.aero.execution_mode=='reuse')
        self.engine_factory=engine_factory or EngineFuelModel;self.history=[];self.last=None;self.limits=LIMITS
        self.maps={};self.airfoil=None
        self.started=time.perf_counter()

    def propeller(self,table,native):
        contract=json.loads((native.geometry_work/'geometry_contract.json').read_text('utf-8'))
        diameter=contract['propeller']['diameter_m']
        # In-process reuse only. Solver, blade options and airfoil stay immutable;
        # unlike the aero table, this axial prop map does not depend on airframe mass.
        identity={'diameter':diameter,'options':asdict(self.options.propeller),
                  'branches':sorted({(b['speed_m_s'],tuple(b['altitudes_m'])) for b in table.tables.values()})}
        key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
        if key not in self.maps:
            prop=self.map_factory(self.root,self.work/'native'/('prop_'+key[:12]),table,diameter,self.options.propeller,self.airfoil)
            self.maps[key]=prop;self.airfoil=prop.data['airfoil']
        return self.maps[key],key

    def evaluate(self,design_mass,geo,fuel_guess,power_guess,mass_model,iteration,dt):
        p=self.p;options=self.options.aero;weights=mass_model.evaluate(design_mass,power_guess,geo,p)
        rows,dry,moment=dry_ledger(weights,geo,p);fuel_x=geo['wing_quarter_x_m']
        upper=max(60.,1.6*fuel_guess);schedule=feedback_schedule(design_mass,geo,p,options)
        ref=dry+min(fuel_guess,upper);cg=(moment+(ref-dry)*fuel_x)/ref
        native=self.native_factory(self.root,self.work/'native'/f'trial_{iteration:03d}',p,geo,cg,design_mass,options.drag)
        legs,_=mission_legs(design_mass,geo,p,schedule);h=p.assumptions.cruise_altitude_m
        branches=[(v,r,sorted([h0,h1])) for _,_,v,h0,h1,r,_ in legs]
        branches += [(p.assumptions.cruise_speed_m_s,0.,[h,h]),(schedule[0],p.sizing.climb_rate_m_s,[0.,h]),(schedule[1],0.,[h,h])]
        merged={}
        for v,r,heights in branches:
            k=MissionAeroTable.key(v,r)
            if k in merged:heights=[min(heights[0],merged[k][2][0]),max(heights[-1],merged[k][2][-1])]
            merged[k]=(v,r,heights)
        table=MissionAeroTable(native,dry,moment,fuel_x,np.linspace(dry,dry+upper,options.mass_stations),
            options.altitude_stations,list(merged.values()),geo['wing_area_m2'])
        prop,key=self.propeller(table,native)
        flight=PropulsiveFlight(table,prop,self.engine_factory(power_guess,self.options.low_load_policy))
        inner=[];fuel=upper
        for j in range(40):
            loaded=dry+fuel;power=propulsion_constraints(loaded,geo,p,flight,schedule)
            rated=power['installed_power_w']
            if not 40000<=rated<=400000:raise PropulsionError('engine_size_out_of_domain','需安装功率超出40–400 kW',required_power_w=rated)
            flight.engine=self.engine_factory(rated,self.options.low_load_policy)
            ms=mission(loaded,geo,rated,p,dt,**mission_kwargs(flight,schedule,p))
            required=ms['takeoff_fuel_kg'];residual=required-fuel
            inner.append({'iteration':j+1,'loaded_takeoff_fuel_kg':fuel,'required_takeoff_fuel_kg':required,'rated_power_w':rated,'residual_kg':residual})
            if required>upper:raise FeedbackError('fuel_guess_too_small','需携油超出试算气动表范围',required_kg=required,upper_kg=upper)
            if abs(residual)<1e-7:break
            fuel=required
        else:raise FeedbackError('fuel_iteration_not_converged','同构型燃油携带量迭代未收敛')
        flight.capture=True;flight.engine.capture=True
        try:ms=mission(loaded,geo,rated,p,dt,**mission_kwargs(flight,schedule,p))
        finally:flight.capture=False;flight.engine.capture=False
        power['basis']='resized sea-level rated engine at selected RPM; 2% constraint sizing margin'
        ledger=cg_ledger(weights,geo,p,ms);updated=mass_model.evaluate(design_mass,rated,geo,p)
        residuals={'power_weight_coupling':abs(rated/power_guess-1),'dry_weight_coupling':abs(updated['owe_kg']/weights['owe_kg']-1),
                   'mission_initial_mass_kg':ledger['loaded_mass_kg']-loaded}
        audit={'iteration':iteration,'native':native.evidence(),'dry_component_ledger':rows,'schedule_m_s':list(schedule),
            'inner_fuel':inner,'coupling_residuals':residuals,'mass_model_power_input_w':power_guess,'updated_power_w':rated,
            'engine':flight.engine.evidence,'propeller_map_key':key,'propeller_map_metadata':prop.data['metadata'],
            'weights':weights,'block_fuel_kg':ms['block_fuel_kg'],'geometry':geo,'cg':ledger}
        self.history.append(audit);self.last={'native':native,'table':table,'schedule':schedule,'loaded':loaded,'geo':geo,
            'power':power,'mission':ms,'weights':weights,'audit':audit,'flight':flight}
        (self.work/'iterations').mkdir(exist_ok=True);write_json(self.work/'iterations'/f'{iteration:03d}.json',audit)
        for name,data in [('aero_table',table.to_dict()),('propeller_map',prop.data),('engine_model',flight.engine.evidence),
                          ('mission_trace',flight.trace),('engine_trace',flight.engine.trace)]:write_json(self.work/(name+'.json'),data)
        print(f"Coupled trial {iteration}: loaded={loaded:.3f} kg, fuel={ms['block_fuel_kg']:.3f} kg, rated={rated/1000:.3f} kW",flush=True)
        return power,ms,weights,ledger,residuals

    def finalize(self,summary):
        audit_started=time.perf_counter();iteration_s=audit_started-self.started
        from .propulsion_service import verify_queries
        last=self.last;table=last['table'];native=last['native'];flight=last['flight'];p=self.p;direct=[]
        for b in table.tables.values():
            for f in ((.5,) if len(b['altitudes_m'])==1 else (.25,.75)):
                mass=table.mass_nodes[0]+(.35+.3*f)*(table.mass_nodes[-1]-table.mass_nodes[0])
                h=b['altitudes_m'][0]+f*(b['altitudes_m'][-1]-b['altitudes_m'][0]);v=b['speed_m_s'];roc=b['roc_m_s']
                predicted=table.query(mass,v,h,roc);actual=native(mass,table.cg(mass),v,h,roc)
                error=abs(predicted['cd']/actual['cd']-1)
                direct.append({'mass_kg':mass,'speed_m_s':v,'altitude_m':h,'roc_m_s':roc,'interpolated_cd':predicted['cd'],
                    'direct_cd':actual['cd'],'relative_cd_error':error,'point_directory':actual['point_directory'],'passed':error<.02})
        prop=flight.propeller
        prop_checks=verify_queries(self.root,self.work/'native/direct_propeller',flight,self.options.propeller,prop.diameter,prop.data['airfoil'])
        fine=mission(last['loaded'],last['geo'],last['power']['installed_power_w'],p,self.options.aero.integration_step_s/2,
                     **mission_kwargs(flight,last['schedule'],p))
        step=abs(fine['block_fuel_kg']/last['mission']['block_fuel_kg']-1)
        engine_rows=[r for r in flight.engine.trace if r['segment'] not in ('taxi','takeoff')]
        if len(engine_rows)!=len(flight.trace):raise ValueError('发动机与桨匹配记录点数不一致')
        match=[{**a,**e,'torque_margin_nm':e['available_power_w']/(e['rpm']*math.pi/30)-a['torque_nm'],
                'torque_balance_error_nm':e['torque_nm']-a['torque_nm']} for a,e in zip(flight.trace,engine_rows)]
        write_json(self.work/'matching_trace.json',match)
        checks={'aero_table_accuracy':all(r['passed'] for r in direct),'propeller_table_accuracy':all(r['passed'] for r in prop_checks),
            'mission_step_accuracy':step<.005,'shaft_torque_balance':all(abs(r['torque_balance_error_nm'])<1e-8 for r in match)}
        audit={'options':asdict(self.options),'native_iterations':len(self.history),'unique_propeller_maps':len(self.maps),
            'speed_schedule_m_s':list(last['schedule']),'direct_aero_checks':direct,'direct_propeller_checks':prop_checks,
            'timestep_half_relative_fuel_error':step,'engine':flight.engine.evidence,
            'propeller':{k:prop.data[k] for k in ('rpm','diameter_m','blades','options','metadata','geometry_role','max_tip_mach')},
            'minimum_torque_margin_nm':min(r['torque_margin_nm'] for r in match),
            'efficiency_range':[min(r['efficiency'] for r in match),max(r['efficiency'] for r in match)],
            'fuel_method_fraction':{k:v/last['mission']['block_fuel_kg'] for k,v in last['mission']['block_fuel_by_method_kg'].items()},
            'physical_validation_passed':False,'checks':checks,'limits':LIMITS}
        summary['propulsion_feedback']=audit;summary['checks'].update(checks);summary['trim_checked']=summary['converged']
        summary['limits']=LIMITS;summary['method']='FAST-GA mass and engine maps + native AVL/XFOIL + CCBlade + shared overall iteration'
        if summary['converged'] and not all(summary['checks'].values()):summary['status']='constraints_not_met'
        write_json(self.work/'coupled_verification.json',audit)
        profile={'execution_mode':self.options.aero.execution_mode,'iteration_s':iteration_s,
                 'final_native_audit_s':time.perf_counter()-audit_started,
                 'audit_scope':'non-node AVL/Newton and direct CCBlade; existing verified XFOIL polar cache allowed',
                 'mesh_and_tolerances_changed':False}
        summary['execution_profile']=profile;write_json(self.work/'execution_profile.json',profile)
