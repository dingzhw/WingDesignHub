"""Bounded native aerodynamic tables feeding the existing mission and sizing loop."""
from dataclasses import dataclass, field, asdict, replace
from copy import deepcopy
from pathlib import Path
import math
import numpy as np
from .aircraft_drag import DragOptions
from .sizing_physics import G,RHO0,density,speed_schedule,mission_legs,mission,constraints,DesignDomainError
from .sizing import cg_ledger
from .service import write_json


class FeedbackError(DesignDomainError):
    def __init__(self,status,message,**context):
        super().__init__(message);self.status=status;self.context=context


@dataclass(frozen=True)
class FeedbackOptions:
    schedule_cl_ceiling: float=.50
    mass_stations: int=2
    altitude_stations: int=3
    integration_step_s: float=30.
    max_iterations: int=40
    drag: DragOptions=field(default_factory=DragOptions)

    @classmethod
    def from_dict(cls,data):
        data=dict(data)
        if 'drag' in data:data['drag']=DragOptions(**data['drag'])
        result=cls(**data);result.validate();return result

    def validate(self):
        for n,lo,hi in [('schedule_cl_ceiling',.35,.55),('integration_step_s',5.,60.)]:
            x=getattr(self,n)
            if type(x) not in (int,float) or not math.isfinite(x) or not lo<=x<=hi:raise ValueError('气动任务选项越界：'+n)
        if type(self.mass_stations) is not int or self.mass_stations not in (2,3):raise ValueError('质量插值节点须为2或3')
        if type(self.altitude_stations) is not int or self.altitude_stations not in (3,5):raise ValueError('高度插值节点须为3或5')
        if type(self.max_iterations) is not int or not 1<=self.max_iterations<=40:raise ValueError('总体最大迭代次数须为1–40')
        self.drag.validate()


LIMITS=[
    '原生AVL升力面配平与XFOIL翼尾/非升力阻力驱动任务；每轮几何重新计算有界工况表，质量/CG由同一干重台账和剩余燃油决定。',
    '任务为无风、定常直线爬升/平飞/下降；L=mg*cos(gamma)，T=D+mg*sin(gamma)。推力沿航迹通过CG，无滑流、推力线偏置或机身/黏性俯仰矩修正。',
    '任务速度采用显式的低迎角CL上限安排；这不是失速或经济速度预测。实际配平仍须满足±6°迎角、±10°舵偏及真实残差。',
    '桨效率、密度比例可用功率和耗油模型沿用原假设；发动机/桨图、风车阻力和动力影响留待后续节点。',
    '支柱横流、接合部/冷却/粗糙度预算未校准；数值插值及公开翼型对照不等于整机独立物理验证。',
    '固定设计重量使用实际配置装载分析任务，不将未分配预算生成压舱物；FAST-GA结构重量仍为经验估算。',
    '储备按平均巡航耗油率独立携带，不加入已飞航程/航时。起降距离、真实重心包线和结构定尺寸反馈未覆盖。',
]


def dry_ledger(weights,geo,p):
    temporary=cg_ledger(weights,geo,p,{'takeoff_fuel_kg':0.,'trip_fuel_from_takeoff_kg':0.})
    rows=[r for r in temporary['rows'] if r['component']!='takeoff_fuel']
    mass=math.fsum(r['mass_kg'] for r in rows);moment=math.fsum(r['mass_kg']*r['x_m'] for r in rows)
    return rows,mass,moment


def feedback_schedule(design_mass,geo,p,options):
    old=speed_schedule(design_mass,geo,p)
    floor=math.sqrt(2*design_mass*G/(density(p.assumptions.cruise_altitude_m)*geo['wing_area_m2']*options.schedule_cl_ceiling))
    return max(old[0],floor),max(old[1],floor),old[2]


def _bracket(nodes,value,label):
    if not math.isfinite(value) or value<nodes[0]-1e-8 or value>nodes[-1]+1e-8:
        raise FeedbackError('aero_table_out_of_domain',label+'超出当前气动表，禁止外推',value=value,bounds=list(nodes))
    j=int(np.searchsorted(nodes,value));a=max(0,j-1);b=min(j,len(nodes)-1)
    f=0. if a==b else (value-nodes[a])/(nodes[b]-nodes[a])
    return a,b,min(1.,max(0.,f))


class MissionAeroTable:
    def __init__(self,native,dry_mass,dry_moment,fuel_x,mass_nodes,altitude_nodes,branches,area):
        self.native=native;self.dry_mass=dry_mass;self.dry_moment=dry_moment;self.fuel_x=fuel_x
        self.mass_nodes=list(map(float,mass_nodes));self.area=area;self.tables={};self.capture=False;self.trace=[]
        if len(self.mass_nodes)<2 or any(not math.isfinite(x) for x in self.mass_nodes) or any(b<=a for a,b in zip(self.mass_nodes,self.mass_nodes[1:])):
            raise ValueError('质量表节点须为有限递增量')
        for speed,roc,heights in branches:
            key=self.key(speed,roc)
            if key in self.tables:continue
            grid=[float(heights[0])] if heights[0]==heights[-1] else list(map(float,np.linspace(heights[0],heights[-1],altitude_nodes)))
            points=[]
            for mass in self.mass_nodes:
                points.append([native(mass,self.cg(mass),speed,h,roc) for h in grid])
            self.tables[key]={'speed_m_s':speed,'roc_m_s':roc,'altitudes_m':grid,'points':points}

    @staticmethod
    def key(speed,roc):return f'{speed:.9f}/{roc:.9f}'

    @classmethod
    def from_dict(cls,data):
        """Reopen a checked table for bounded Python queries, without a solver launch."""
        obj=cls.__new__(cls);obj.native=None;obj.capture=False;obj.trace=[]
        obj.mass_nodes=data['mass_nodes_kg'];obj.dry_mass=data['dry_mass_kg'];obj.dry_moment=data['dry_moment_kg_m']
        obj.fuel_x=data['fuel_x_m'];obj.area=data['reference_area_m2'];obj.tables=deepcopy(data['branches'])
        if (not data.get('no_extrapolation') or len(obj.mass_nodes)<2 or
            not np.isfinite([*obj.mass_nodes,obj.dry_mass,obj.dry_moment,obj.fuel_x,obj.area]).all() or
            obj.dry_mass<=0 or obj.area<=0 or any(b<=a for a,b in zip(obj.mass_nodes,obj.mass_nodes[1:]))):raise ValueError('气动表参考量无效')
        for key,b in obj.tables.items():
            heights=b['altitudes_m']
            if not heights or not np.isfinite(heights).all() or any(y<=x for x,y in zip(heights,heights[1:])) or key!=obj.key(b['speed_m_s'],b['roc_m_s']):raise ValueError('气动表分支无效')
            if len(b['points'])!=len(obj.mass_nodes):raise ValueError('气动表质量节点不完整')
            for mass,row in zip(obj.mass_nodes,b['points']):
                if len(row)!=len(heights):raise ValueError('气动表高度节点不完整')
                for height,point in zip(heights,row):
                    numbers=[point['cd'],point['alpha_deg'],point['elevator_deg'],*point['components'].values()]
                    if (not np.isfinite(numbers).all() or point['cd']<=0 or any(v<0 for v in point['components'].values()) or
                        abs(point['cd']-sum(point['components'].values()))>1e-10 or point['mass_kg']!=mass or point['altitude_m']!=height or
                        point['speed_m_s']!=b['speed_m_s'] or point['roc_m_s']!=b['roc_m_s'] or abs(point['cg_x_m']-obj.cg(mass))>1e-10):raise ValueError('气动表点与状态不一致')
        if not obj.tables:raise ValueError('气动表没有工况分支')
        return obj

    def cg(self,mass):
        if mass<self.dry_mass-1e-7:raise FeedbackError('fuel_inventory_exhausted','任务耗油超过当前试算携带量',mass_kg=mass,dry_mass_kg=self.dry_mass)
        return (self.dry_moment+(mass-self.dry_mass)*self.fuel_x)/mass

    def query(self,mass,speed,altitude,roc):
        key=self.key(speed,roc)
        if key not in self.tables:raise FeedbackError('aero_table_missing','任务速度/航迹条件没有气动表',speed_m_s=speed,roc_m_s=roc)
        table=self.tables[key];a,b,x=_bracket(self.mass_nodes,mass,'质量');i,j,y=_bracket(table['altitudes_m'],altitude,'高度')
        points=table['points']
        def interp(fn):return (1-x)*((1-y)*fn(points[a][i])+y*fn(points[a][j]))+x*((1-y)*fn(points[b][i])+y*fn(points[b][j]))
        components={k:interp(lambda p:p['components'][k]) for k in ('induced','profile','body','allowance')}
        return {'cd':math.fsum(components.values()),'components':components,
                'alpha_deg':interp(lambda p:p['alpha_deg']),'elevator_deg':interp(lambda p:p['elevator_deg']),
                'cg_x_m':self.cg(mass),'interpolation':'bilinear mass/altitude; exact branch speed and ROC'}

    def __call__(self,mass,area,speed,altitude,roc,assumptions):
        if not math.isclose(area,self.area,rel_tol=1e-12):raise FeedbackError('aero_table_mismatch','任务参考面积与气动表不一致')
        r=self.query(mass,speed,altitude,roc);q=.5*density(altitude)*speed**2
        gamma=math.asin(roc/speed);cl=mass*G*math.cos(gamma)/(q*area);drag=q*area*r['cd']
        thrust=drag+mass*G*math.sin(gamma);power=thrust*speed/assumptions.propeller_efficiency
        if power<=0:raise FeedbackError('descent_requires_braking','当前下降工况需负推力/额外阻力，现有推进模型未覆盖',power_w=power)
        if self.capture:self.trace.append({'mass_kg':mass,'remaining_fuel_kg':mass-self.dry_mass,'speed_m_s':speed,
            'altitude_m':altitude,'roc_m_s':roc,'cl':cl,'drag_n':drag,'thrust_n':thrust,'shaft_power_w':power,**r})
        return power,cl,drag

    def to_dict(self):
        return {'mass_nodes_kg':self.mass_nodes,'dry_mass_kg':self.dry_mass,'dry_moment_kg_m':self.dry_moment,
                'fuel_x_m':self.fuel_x,'reference_area_m2':self.area,'branches':self.tables,
                'no_extrapolation':True,'physical_validation_passed':False}


class AeroFeedback:
    def __init__(self,root,work,project,options,native_factory=None):
        from .feedback_native import NativeFeedbackGeometry
        self.root=Path(root);self.work=Path(work);self.p=project;self.options=options;options.validate()
        self.native_factory=native_factory or NativeFeedbackGeometry;self.history=[];self.last=None
        self.limits=LIMITS

    def evaluate(self,design_mass,geo,fuel_guess,power_guess,mass_model,iteration,dt):
        p=self.p;weights=mass_model.evaluate(design_mass,power_guess,geo,p)
        rows,dry,moment=dry_ledger(weights,geo,p);fuel_x=geo['wing_quarter_x_m']
        upper=max(60.,1.6*fuel_guess);schedule=feedback_schedule(design_mass,geo,p,self.options)
        ref_mass=dry+min(fuel_guess,upper);cg=(moment+(ref_mass-dry)*fuel_x)/ref_mass
        native=self.native_factory(self.root,self.work/'native'/f'trial_{iteration:03d}',p,geo,cg,design_mass,self.options.drag)
        legs,_=mission_legs(design_mass,geo,p,schedule);h=p.assumptions.cruise_altitude_m
        branches=[]
        for _,_,speed,h0,h1,roc,_ in legs:branches.append((speed,roc,sorted([h0,h1])))
        branches += [(p.assumptions.cruise_speed_m_s,0.,[h,h]),(schedule[0],p.sizing.climb_rate_m_s,[0.,h]),(schedule[1],0.,[h,h])]
        # Merge repeated branch domains before generating any native points.
        merged={}
        for speed,roc,heights in branches:
            k=MissionAeroTable.key(speed,roc)
            if k in merged:heights=[min(heights[0],merged[k][2][0]),max(heights[-1],merged[k][2][-1])]
            merged[k]=(speed,roc,heights)
        table=MissionAeroTable(native,dry,moment,fuel_x,np.linspace(dry,dry+upper,self.options.mass_stations),
                              self.options.altitude_stations,list(merged.values()),geo['wing_area_m2'])
        inner=[];fuel=upper
        for j in range(40):
            loaded=dry+fuel;power=constraints(loaded,geo,p,flight_model=table,schedule=schedule)
            ms=mission(loaded,geo,power['installed_power_w'],p,dt,flight_model=table,schedule=schedule)
            required=ms['takeoff_fuel_kg'];residual=required-fuel
            inner.append({'iteration':j+1,'loaded_takeoff_fuel_kg':fuel,'required_takeoff_fuel_kg':required,'residual_kg':residual})
            if required>upper:raise FeedbackError('fuel_guess_too_small','任务所需油量超出试算表覆盖量',required_kg=required,upper_kg=upper)
            if abs(residual)<1e-7:break
            fuel=required
        else:raise FeedbackError('fuel_iteration_not_converged','同构型燃油携带量迭代未收敛')
        table.capture=True;table.trace=[]
        ms=mission(loaded,geo,power['installed_power_w'],p,dt,flight_model=table,schedule=schedule);table.capture=False
        ledger=cg_ledger(weights,geo,p,ms)
        updated=mass_model.evaluate(design_mass,power['installed_power_w'],geo,p)
        residuals={'power_weight_coupling':abs(power['installed_power_w']/power_guess-1),
                   'dry_weight_coupling':abs(updated['owe_kg']/weights['owe_kg']-1),
                   'mission_initial_mass_kg':ledger['loaded_mass_kg']-loaded}
        audit={'iteration':iteration,'native':native.evidence(),'dry_component_ledger':rows,
               'schedule_m_s':list(schedule),'inner_fuel':inner,'coupling_residuals':residuals,
               'mass_model_power_input_w':power_guess,'updated_power_w':power['installed_power_w']}
        self.history.append(audit);self.last={'native':native,'table':table,'schedule':schedule,'loaded':loaded,'geo':geo,
                                           'power':power,'mission':ms,'weights':weights,'audit':audit}
        folder=self.work/'iterations';folder.mkdir(exist_ok=True)
        write_json(folder/f'{iteration:03d}.json',audit)
        write_json(self.work/'aero_table.json',table.to_dict());write_json(self.work/'mission_trace.json',table.trace)
        print(f"Overall trial {iteration}: loaded={loaded:.3f} kg, block fuel={ms['block_fuel_kg']:.3f} kg, power={power['installed_power_w']/1000:.3f} kW",flush=True)
        return power,ms,weights,ledger,residuals

    def finalize(self,summary):
        if self.last is None:return
        last=self.last;table=last['table'];native=last['native'];p=self.p;direct=[]
        # Fresh interior conditions, distinct from the interpolation nodes.
        for branch in table.tables.values():
            fractions=(.5,) if len(branch['altitudes_m'])==1 else (.25,.75)
            for fraction in fractions:
                mass=table.mass_nodes[0]+(.35+.3*fraction)*(table.mass_nodes[-1]-table.mass_nodes[0])
                h=branch['altitudes_m'][0]+fraction*(branch['altitudes_m'][-1]-branch['altitudes_m'][0]);v=branch['speed_m_s'];roc=branch['roc_m_s']
                predicted=table.query(mass,v,h,roc);actual=native(mass,table.cg(mass),v,h,roc)
                error=abs(predicted['cd']/actual['cd']-1)
                direct.append({'mass_kg':mass,'speed_m_s':v,'altitude_m':h,'roc_m_s':roc,'interpolated_cd':predicted['cd'],
                               'direct_cd':actual['cd'],'relative_cd_error':error,'point_directory':actual['point_directory'],'passed':error<.02})
        checks=all(x['passed'] for x in direct)
        old_ms=mission(last['loaded'],last['geo'],last['power']['installed_power_w'],p,self.options.integration_step_s,schedule=last['schedule'])
        old_power=constraints(last['loaded'],last['geo'],p,schedule=last['schedule'])
        fine=mission(last['loaded'],last['geo'],last['power']['installed_power_w'],p,self.options.integration_step_s/2,flight_model=table,schedule=last['schedule'])
        step_error=abs(fine['block_fuel_kg']/last['mission']['block_fuel_kg']-1)
        audit={'options':asdict(self.options),'native_iterations':len(self.history),'final_geometry_directory':str(native.geometry_work.relative_to(self.work)),
               'dry_component_ledger':last['audit']['dry_component_ledger'],'speed_schedule_m_s':list(last['schedule']),
               'same_condition_comparison':{'conditions':'same geometry, takeoff mass, speed schedule, efficiency, BSFC model and installed power for mission',
                   'legacy_block_fuel_kg':old_ms['block_fuel_kg'],'native_block_fuel_kg':last['mission']['block_fuel_kg'],
                   'legacy_required_installed_power_w':old_power['installed_power_w'],'native_required_installed_power_w':last['power']['installed_power_w']},
               'direct_checks':direct,'timestep_half_relative_fuel_error':step_error,
               'table_verified':checks,'timestep_verified':step_error<.005,'mission_polar_updated':True,
               'physical_validation_passed':False,'limits':LIMITS}
        audit['fixed_design_sensitivity']=assumption_sensitivity(table,last['loaded'],last['geo'],last['power']['installed_power_w'],p,last['schedule'],self.options)
        summary['aerodynamic_feedback']=audit;summary['trim_checked']=summary['converged'];summary['limits']=LIMITS
        summary['checks']['aero_table_accuracy']=checks;summary['checks']['mission_step_accuracy']=step_error<.005
        if summary['converged'] and (not checks or step_error>=.005):summary['status']='constraints_not_met'
        write_json(self.work/'feedback_verification.json',audit)


def assumption_sensitivity(table,mass,geo,installed_power,p,schedule,options):
    """Same airframe, loading and installed engine. Report demand, not a resized design."""
    rows=[]
    cases=[('baseline',1.,0.,p.sizing.propeller_efficiency),
           ('strut_cd_0.8',.8/options.drag.strut_crossflow_cd,0.,p.sizing.propeller_efficiency),
           ('strut_cd_1.6',1.6/options.drag.strut_crossflow_cd,0.,p.sizing.propeller_efficiency),
           ('allowance_plus_0.001',1.,.001,p.sizing.propeller_efficiency),
           ('propeller_efficiency_minus_0.05',1.,0.,p.sizing.propeller_efficiency-.05)]
    for name,ratio,extra,eta in cases:
        data=table.to_dict();data=deepcopy(data)
        for branch in data['branches'].values():
            for row in branch['points']:
                for point in row:
                    point['components']['body']+=point.get('strut_cd',0.)*(ratio-1)
                    point['components']['allowance']+=extra;point['cd']=sum(point['components'].values())
        scenario=MissionAeroTable.from_dict(data);pp=replace(p,sizing=replace(p.sizing,propeller_efficiency=eta))
        row={'case':name,'strut_cd':options.drag.strut_crossflow_cd*ratio,'allowance_delta_cd':extra,'propeller_efficiency':eta}
        try:
            ms=mission(mass,geo,installed_power,pp,options.integration_step_s,flight_model=scenario,schedule=schedule)
            power=constraints(mass,geo,pp,flight_model=scenario,schedule=schedule)
            row.update(status='calculated',required_block_fuel_kg=ms['block_fuel_kg'],required_installed_power_w=power['installed_power_w'],
                       mission_max_power_fraction=ms['max_power_fraction'],carried_fuel_margin_kg=mass-scenario.dry_mass-ms['takeoff_fuel_kg'])
        except DesignDomainError as exc:row.update(status='out_of_domain',diagnostic=str(exc))
        rows.append(row)
    return {'basis':'fixed geometry, initial mass/CG/fuel, installed power, speed schedule and dry mass; recompute mission and power demand only',
            'reoptimized':False,'calibration_performed':False,'rows':rows}
