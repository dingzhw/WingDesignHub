"""Native FAST-GA/OpenMDAO mass breakdown with direct total payload inputs.

Only constructor-required propeller maps are read from the pinned public SR22
file. They are unused by BasicICEngine.compute_weight; no SR22 geometry, mass,
mission or material calibration is carried into the new aircraft.
"""
import ast
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from .adapters import sha256
from .configuration import geometry_parameters, domain_ledger


def mass_inputs(mass, power, geo, project):
    a=project.sizing;h=project.assumptions.cruise_altitude_m;v=project.assumptions.cruise_speed_m_s
    d={}
    def add(name,value,unit=None):d[name]=(value,unit)
    for n,x in [('MTOW',mass),('MFW',geo['tank_capacity_kg']),('payload',project.payload_kg),('max_payload',project.payload_kg)]:add('data:weight:aircraft:'+n,x,'kg')
    add('data:TLAR:v_cruise',v,'m/s');add('data:TLAR:v_max_sl',v*1.2,'m/s')
    add('data:mission:sizing:cs23:characteristic_speed:vd',v*1.4,'m/s')
    add('data:mission:sizing:cs23:sizing_factor:ultimate_aircraft',5.7)
    add('data:mission:sizing:main_route:cruise:altitude',h,'m')
    add('data:geometry:cabin:seats:passenger:NPAX_max',a.seats-2)
    add('data:geometry:wing_configuration',1.);add('data:geometry:has_T_tail',0.)
    parameters=geometry_parameters(geo)
    for component, spec in parameters.items():
        area=geo[component+'_area_m2']
        ar,taper,thick=(spec[k] for k in ('aspect_ratio','taper_ratio','thickness_ratio'))
        for field,value,unit in [('area',area,'m**2'),('aspect_ratio',ar,None),('taper_ratio',taper,None),('thickness_ratio',thick,None),('sweep_25',0.,'deg')]:
            add('data:geometry:'+component+':'+field,value,unit)
        add('data:weight:airframe:'+component+':k_factor',1.)
    add('data:geometry:wing:span',geo['wing_span_m'],'m')
    for field,key in [('length','fuselage_length_m'),('maximum_width','fuselage_width_m'),('maximum_height','fuselage_height_m')]:add('data:geometry:fuselage:'+field,geo[key],'m')
    add('data:weight:airframe:fuselage:k_factor',1.)
    wet=2.05*(geo['wing_area_m2']+geo['horizontal_tail_area_m2']+geo['vertical_tail_area_m2'])+np.pi*1.275*a.fuselage_length_m*.85
    add('data:geometry:aircraft:wet_area',wet,'m**2')
    add('data:geometry:landing_gear:type',0.);add('data:geometry:landing_gear:height',.75,'m')
    add('data:geometry:propulsion:engine:count',1.);add('data:geometry:propulsion:engine:layout',3.)
    add('data:propulsion:IC_engine:max_power',power,'W');add('data:propulsion:IC_engine:strokes_nb',4.)
    add('data:propulsion:fuel_type',1.)
    add('settings:weight:aircraft:MLW_MZFW_ratio',1.06)
    add('settings:propulsion:IC_engine:k_factor_sfc',1.)
    add('settings:weight:propulsion:engine:k_factor',1.)
    add('settings:wingdesignhub:unusable_fuel_fraction',a.unusable_fuel_fraction)
    return d


class FastGAMassModel:
    def __init__(self):self.problem=None;self.context=None;self.last_inputs={};self.audit={}

    def __enter__(self):
        from .fastga_compat import compatibility
        self.context=compatibility();self.context.__enter__()
        import fastoad.api as oad
        from .fastga_plugins.unusable_fuel import SERVICE_UNUSABLE_FUEL_MASS,UNUSABLE_PROVIDER
        oad.RegisterSubmodel.active_models[SERVICE_UNUSABLE_FUEL_MASS]=UNUSABLE_PROVIDER
        return self

    def __exit__(self,*args):
        if self.problem is not None:self.problem.cleanup()
        return self.context.__exit__(*args)

    def _setup(self, values):
        import fastga
        import openmdao.api as om
        from fastga.models.weight.mass_breakdown.mass_breakdown import MassBreakdown
        source=Path(fastga.__file__).parent/'source_data_files/Cirrus_SR22.xml'
        maps={}
        def visit(e,path):
            name=':'.join(path)
            if not list(e) and name.startswith('data:aerodynamics:propeller:'):
                unit=e.get('units');maps[name]=(ast.literal_eval(e.text.strip()),None if unit=='unitless' else unit)
            for child in e:visit(child,path+[child.tag])
        visit(ET.parse(source).getroot(),[])
        supplied={**maps,**values};bindings={}
        class Root(om.Group):
            def setup(self):
                self.add_subsystem('mass',MassBreakdown(payload_from_npax=False,propulsion_id='fastga.wrapper.propulsion.basicIC_engine'),promotes=['*'])
            def configure(self):
                outs={m['prom_name'] for m in self.mass.get_io_metadata(iotypes='output').values()}
                for m in self.mass.get_io_metadata(iotypes='input',metadata_keys=['val','units']).values():
                    name=m['prom_name']
                    if name in outs or name in bindings:continue
                    if name not in supplied:raise ValueError('未显式定义质量模型输入：'+name)
                    val,unit=supplied[name]
                    self.set_input_defaults(name,val=val,units=unit)
                    bindings[name]={'units':unit or 'unitless','origin':'engine_constructor_only_public_map' if name in maps else 'design_configuration'}
        self.problem=om.Problem(model=Root(),reports=False);self.problem.setup();self.problem.final_setup()
        self.audit={'provider':'FAST-GA 1.4.0 MassBreakdown(payload_from_npax=False)',
                    'propeller_constructor_source_sha256':sha256(source),'bindings':bindings,
                    'upstream_mass_source_hashes':{f.relative_to(source.parents[1]).as_posix():sha256(f)
                        for f in (source.parents[1]/'models/weight/mass_breakdown').rglob('*.py')},
                    'note':'公开桨图仅供原生发动机对象初始化，未用于当前任务效率或耗油率；新机几何和重量输入全部自行生成'}

    def evaluate(self,mass,power,geo,project):
        values=mass_inputs(mass,power,geo,project)
        if self.problem is None:self._setup(values)
        for name,(val,unit) in values.items():self.problem.set_val(name,val,units=unit)
        self.problem.run_model()
        categories={name:float(self.problem.get_val('data:weight:'+name+':mass',units='kg').item()) for name in ('airframe','propulsion','systems','furniture')}
        owe=float(self.problem.get_val('data:weight:aircraft:OWE',units='kg').item())
        if not np.isfinite(list(categories.values())+[owe]).all() or min(categories.values())<0 or abs(sum(categories.values())-owe)>1e-6:
            raise ValueError('FAST-GA 重量输出或部件求和无效')
        self.last_inputs={n:{'value':v,'units':u or 'unitless'} for n,(v,u) in values.items()}
        self.audit['domain_ledger']=domain_ledger(geo)
        details={}
        for name,m in self.problem.model.get_io_metadata(iotypes='output').items():
            public=m['prom_name']
            if public.startswith('data:weight:') and public.endswith(':mass') and not name.startswith('_auto_ivc.'):
                details[public]=float(self.problem.get_val(public,units='kg').item())
        unusable=details['data:weight:propulsion:unusable_fuel:mass']
        categories['unusable_fuel']=unusable
        return {'owe_kg':owe+unusable,'native_owe_kg':owe,'unusable_fuel_added_once_kg':unusable,
                'categories_kg':categories,'components_kg':details}
