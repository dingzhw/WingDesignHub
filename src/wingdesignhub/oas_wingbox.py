"""OAS v2.12.1 official wingbox regression; adapted from test_wingbox_analysis.py.

Apache-2.0; see third_party/OpenAeroStruct-LICENSE.txt. Changes: explicit num_x,
real physical coordinates, input/result snapshots, explicit optimizer bound clipping,
and fuel-load checks. Original upstream test is also run unmodified locally.
"""
from pathlib import Path
from importlib.metadata import version
import numpy as np
import openmdao.api as om
from openaerostruct.meshing.mesh_generator import generate_mesh
from openaerostruct.structures.struct_groups import SpatialBeamAlone
from .service import write_json

REFERENCE_URL = "https://github.com/mdolab/OpenAeroStruct/blob/v2.12.1/tests/integration_tests/test_wingbox_analysis.py"
REFERENCE_MASS_KG = 16932.20046986


def official_surface():
    mesh,_=generate_mesh({'num_x':3,'num_y':7,'wing_type':'uCRM_based','symmetry':True,'num_twist_cp':5})
    return {'name':'wing','symmetry':True,'S_ref_type':'wetted','fem_model_type':'wingbox','mesh':mesh,
            'spar_thickness_cp':np.array([.004,.005,.005,.008,.008,.01]),
            'skin_thickness_cp':np.array([.005,.01,.015,.020,.025,.026]),
            'twist_cp':np.array([4.,5.,8.,8.,8.,9.]),
            'data_x_upper':UPPER_X,'data_x_lower':LOWER_X,'data_y_upper':UPPER_Y,'data_y_lower':LOWER_Y,
            'CL0':0.,'CD0':.0078,'k_lam':.05,'c_max_t':.38,'with_viscous':True,'with_wave':True,
            't_over_c_cp':np.array([.08,.08,.08,.10,.10,.08]),'original_wingbox_airfoil_t_over_c':.12,
            'E':73.1e9,'G':73.1e9/2/1.33,'yield':420e6,'safety_factor':1.5,'mrho':2780.,
            'strength_factor_for_upper_skin':1.,'wing_weight_ratio':1.25,
            'struct_weight_relief':False,'distributed_fuel_weight':True,'exact_failure_constraint':True,
            'fuel_density':803.,'Wf_reserve':15000.}


def run_benchmark(work):
    if version('openaerostruct')!='2.12.1':raise RuntimeError('翼盒回归值仅验证 OpenAeroStruct 2.12.1')
    work=Path(work);work.mkdir(parents=True,exist_ok=True)
    surface=official_surface();ny=surface['mesh'].shape[1]
    snapshot={k:v.tolist() if isinstance(v,np.ndarray) else v for k,v in surface.items()}
    write_json(work/'input.json',{'surface':snapshot,'loads_N_Nm':np.full((ny,6),2e5).tolist(),
        'load_factor':1.,'fuel_mass_kg':10000.,'optimizer':'SLSQP','tol':1e-9,'thickness_bounds_m':[.01,.5]})
    p=om.Problem(reports=False);g=SpatialBeamAlone(surface=surface);iv=om.IndepVarComp()
    iv.add_output('loads',val=np.full((ny,6),2e5),units='N');iv.add_output('load_factor',val=1.)
    iv.add_output('fuel_mass',val=10000.,units='kg');g.add_subsystem('indep_vars',iv,promotes=['*'])
    p.model.add_subsystem('wing',g)
    p.model.connect('wing.fuel_mass','wing.struct_states.fuel_mass')
    p.model.connect('wing.struct_setup.fuel_vols','wing.struct_states.fuel_vols')
    p.driver=om.ScipyOptimizeDriver();p.driver.options['tol']=1e-9
    for name in ('spar','skin'):p.model.add_design_var(f'wing.{name}_thickness_cp',lower=.01,upper=.5,ref=.1)
    p.model.add_constraint('wing.failure',upper=0.);p.model.add_objective('wing.structural_mass',scaler=1e-5)
    try:
        p.setup();p.run_model()
        initial=float(p.get_val('wing.structural_mass').item())
        # Upstream starts below the design lower bound; ScipyOptimizeDriver clips it.
        # Make the same clipping explicit, retaining original inputs/initial analysis above.
        clipped={}
        for name in ('spar','skin'):
            key=f'wing.{name}_thickness_cp';raw=p.get_val(key).copy();new=np.clip(raw,.01,.5)
            clipped[name]={'original_m':raw.tolist(),'optimizer_start_m':new.tolist()};p.set_val(key,new)
        driver=p.run_driver();mass=float(p.get_val('wing.structural_mass').item())
        failure=float(np.max(p.get_val('wing.failure')))
        fuel=p.get_val('wing.struct_states.fuel_weight_loads').copy()
        expected_fuel=-(10000.+15000.)*9.80665/2
        fuel_force=float(fuel[:,2].sum())
        out={'reference':REFERENCE_URL,'reference_mass_kg':REFERENCE_MASS_KG,'mass_kg':mass,'initial_mass_kg':initial,
             'mass_relative_error':abs(mass-REFERENCE_MASS_KG)/REFERENCE_MASS_KG,'reference_rtol':1e-6,
             'driver_success':bool(driver.success),'failure_max':failure,'initial_bound_handling':clipped,
             'spar_thickness_cp_m':p.get_val('wing.spar_thickness_cp').tolist(),
             'skin_thickness_cp_m':p.get_val('wing.skin_thickness_cp').tolist(),
             'tip_displacement_m_rad':p.get_val('wing.disp')[0].tolist(),
             'half_wing_fuel_force_n':fuel_force,'expected_half_wing_fuel_force_n':expected_fuel,
             'full_wing_mass':True,'wing_weight_ratio':1.25,'half_mesh_nodes':ny}
        p.set_val('wing.fuel_mass',11000.);p.run_model()
        delta=float(p.get_val('wing.struct_states.fuel_weight_loads')[:,2].sum()-fuel_force)
        out['fuel_increment_force_n']=delta;out['expected_fuel_increment_force_n']=-1000.*9.80665/2
        finite=np.isfinite([mass,failure,fuel_force,delta]).all()
        passed=bool(finite and driver.success and out['mass_relative_error']<=1e-6 and failure<=1e-6
                    and np.isclose(fuel_force,expected_fuel,rtol=1e-10) and np.isclose(delta,-4903.325,rtol=1e-10))
        result={'status':'passed' if passed else 'failed','passed':passed,'official_wingbox':out,
                'versions':{k:version(k) for k in ('openaerostruct','openmdao','numpy','scipy')},
                'evidence_level':'upstream wingbox regression and independent fuel force balance',
                'physical_validation_passed':False,'buckling_checked':False,
                'limits':['官方 uCRM 翼盒与合成六分量外载；未与本项目 OpenVSP 壳模型同构型对比',
                          '半翼计算、质量已含对称和 1.25 修正；燃油含 10000 kg 与 15000 kg 储备的半翼卸载',
                          '自重卸载关闭；优化只按官方应力失效约束，未包含局部/整体屈曲、疲劳或连接件校核',
                          '材料与 1.5 安全系数均为官方案例输入；不能视为目标飞机许用值',
                          '原始初值部分低于 0.01 m 优化下界，显式执行与上游优化器相同的裁剪并记录']}
        write_json(work/'summary.json',result);return result
    finally:
        p.cleanup()
UPPER_X = np.array([0.1,0.11,0.12,0.13,0.14,0.15,0.16,0.17,0.18,0.19,0.2,0.21,0.22,0.23,0.24,0.25,0.26,0.27,0.28,0.29,0.3,0.31,0.32,0.33,0.34,0.35,0.36,0.37,0.38,0.39,0.4,0.41,0.42,0.43,0.44,0.45,0.46,0.47,0.48,0.49,0.5,0.51,0.52,0.53,0.54,0.55,0.56,0.57,0.58,0.59,0.6], dtype=float)
LOWER_X = np.array([0.1,0.11,0.12,0.13,0.14,0.15,0.16,0.17,0.18,0.19,0.2,0.21,0.22,0.23,0.24,0.25,0.26,0.27,0.28,0.29,0.3,0.31,0.32,0.33,0.34,0.35,0.36,0.37,0.38,0.39,0.4,0.41,0.42,0.43,0.44,0.45,0.46,0.47,0.48,0.49,0.5,0.51,0.52,0.53,0.54,0.55,0.56,0.57,0.58,0.59,0.6], dtype=float)
UPPER_Y = np.array([0.0447,0.046,0.0472,0.0484,0.0495,0.0505,0.0514,0.0523,0.0531,0.0538,0.0545,0.0551,0.0557,0.0563,0.0568,0.0573,0.0577,0.0581,0.0585,0.0588,0.0591,0.0593,0.0595,0.0597,0.0599,0.06,0.0601,0.0602,0.0602,0.0602,0.0602,0.0602,0.0601,0.06,0.0599,0.0598,0.0596,0.0594,0.0592,0.0589,0.0586,0.0583,0.058,0.0576,0.0572,0.0568,0.0563,0.0558,0.0553,0.0547,0.0541], dtype=float)
LOWER_Y = np.array([-0.0447,-0.046,-0.0473,-0.0485,-0.0496,-0.0506,-0.0515,-0.0524,-0.0532,-0.054,-0.0547,-0.0554,-0.056,-0.0565,-0.057,-0.0575,-0.0579,-0.0583,-0.0586,-0.0589,-0.0592,-0.0594,-0.0595,-0.0596,-0.0597,-0.0598,-0.0598,-0.0598,-0.0598,-0.0597,-0.0596,-0.0594,-0.0592,-0.0589,-0.0586,-0.0582,-0.0578,-0.0573,-0.0567,-0.0561,-0.0554,-0.0546,-0.0538,-0.0529,-0.0519,-0.0509,-0.0497,-0.0485,-0.0472,-0.0458,-0.0444], dtype=float)
