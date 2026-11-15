"""Bounded structural risk study, supplying diagnostics to future sizing constraints.

One geometry, one actual AVL load set and one mass inventory. Only mapping
support width and shell-root local rotations change between static solves.
"""
from dataclasses import replace
from pathlib import Path
import numpy as np
from .adapters import tool_paths,sha256
from .flight_loads import FlightLoadCase,aerodynamic_loads,combine_loads
from .structure_service import generate_mesh
from .fea_mesh import read_inp,audit_mesh
from .shell_static import promote_s6,solve_shell,read_dat
from .buckling import panel_screen
from .plate_buckling import PlateCase,run_plate
from .service import write_json


def plate_validation(executable,work):
    work=Path(work);work.mkdir(parents=True,exist_ok=True);case=PlateCase()
    runs={}
    for n in (8,16,24):runs[f'mesh_{n}']=run_plate(replace(case,divisions=n),executable,work/f'mesh_{n}')
    fine=runs['mesh_24'];runs['half_reference']=run_plate(replace(case,divisions=24),executable,work/'half_reference',reference_scale=fine['native_reference_scale']/2)
    runs['double_stress']=run_plate(replace(case,divisions=24,compression_pa=2e6),executable,work/'double_stress')
    runs['clamped']=run_plate(replace(case,divisions=24,support='clamped'),executable,work/'clamped')
    runs['square']=run_plate(replace(case,divisions=24,length_m=.6),executable,work/'square')
    for name,shear in (('shear_positive',1e6),('shear_negative',-1e6)):
        runs[name]=run_plate(replace(case,divisions=24,length_m=.6,compression_pa=0.,shear_pa=shear),executable,work/name)
    checks={'maximum_compression_error':max(runs[f'mesh_{n}']['analytical_compression_relative_error'] for n in (8,16,24)),
            'mesh_16_24_difference':abs(runs['mesh_16']['first_factor']/fine['first_factor']-1),
            'reference_scaling_error':abs(runs['half_reference']['first_factor']/fine['first_factor']-1),
            'double_stress_critical_error':abs(runs['double_stress']['critical_compression_pa']/fine['critical_compression_pa']-1),
            'clamped_increases_critical_load':runs['clamped']['first_factor']>fine['first_factor'],
            'square_compression_error':runs['square']['analytical_compression_relative_error'],
            'shear_sign_symmetry_error':abs(runs['shear_positive']['first_factor']/runs['shear_negative']['first_factor']-1)}
    out={'runs':runs,'checks':checks,'thresholds':{'compression_error':.05,'mesh_difference':.02,'load_scaling':.001},
         'passed':bool(checks['maximum_compression_error']<.05 and checks['mesh_16_24_difference']<.02 and
                       checks['reference_scaling_error']<.001 and checks['double_stress_critical_error']<.001 and
                       checks['clamped_increases_critical_load'] and checks['square_compression_error']<.05 and checks['shear_sign_symmetry_error']<.001),
         'physical_validation_passed':False,'limits':['理想简支/固支均匀膜应力平板的数值基准；与全翼屈曲验收区分',
         '用低参考载荷避开特征值搜索偏移，保留原生与实际工况两套系数；第二档参考载荷核验临界值']}
    out['status']='passed' if out['passed'] else 'failed';write_json(work/'summary.json',out);return out


def run_sensitivity(root,work):
    root=Path(root);work=Path(work);work.mkdir(parents=True,exist_ok=True);case=FlightLoadCase();paths=tool_paths(root)
    write_json(work/'input.json',{'flight':case.to_dict(),'patch_width_fractions':[.05,.1,.2],
                                'root_supports':['clamped','translations_fixed']})
    p,f,aero=aerodynamic_loads(case,paths['avl'],work/'aero');generate_mesh(case.mesh,work/'mesh')
    linear=read_inp(work/'mesh/wing.inp');audit_mesh(linear,case.mesh);mesh=promote_s6(linear);rows=[]
    for width in (.05,.1,.2):
        ids,forces,loads=combine_loads(case,mesh,p,f,patch_width_fraction=width)
        for support in ('clamped','translations_fixed'):
            name=f'width_{width:g}_{support}';folder=work/name
            s=solve_shell(paths['calculix'],folder,mesh,ids,forces,case.mesh.half_span_m,loads['mapping'],allow_root_loads=True,root_support=support)
            _,stress=read_dat(folder/'wing.dat',mesh);screen=panel_screen(mesh,case.mesh,stress)
            row={'name':name,'patch_width_fraction':width,'patch_support_radius_m':loads['patch_support_radius_m'],
                 'root_support':support,'mapping':loads['mapping'],'structure_mass_kg':loads['structure_mass']['mass_kg'],
                 'static':s,'buckling':screen,'source_mesh_sha256':sha256(work/'mesh/wing.inp')}
            write_json(folder/'load_definition.json',loads);write_json(folder/'diagnosis.json',row);rows.append(row)
            print(name,s['tip_mean_z_m'],screen['max_interaction_utilization'],flush=True)
    baseline=next(v for v in rows if v['patch_width_fraction']==.1 and v['root_support']=='clamped')
    controls={}
    for row in rows:
        control=max(row['buckling']['panels'],key=lambda x:x['interaction_utilization'])
        row['controlling_panel']=control
        row['changes_from_baseline']={'tip_relative':row['static']['tip_mean_z_m']/baseline['static']['tip_mean_z_m']-1,
            'peak_stress_relative':row['static']['peak_von_mises_pa']/baseline['static']['peak_von_mises_pa']-1,
            'screen_utilization_relative':row['buckling']['max_interaction_utilization']/baseline['buckling']['max_interaction_utilization']-1}
    panel=baseline['controlling_panel'];diag=panel['diagnostics']
    representative=PlateCase(length_m=panel['y_end_m']-panel['y_start_m'],width_m=panel['width_m'],thickness_m=panel['thickness_m'],
          compression_pa=max(0.,-panel['sigma_longitudinal_pa']),shear_pa=abs(panel['tau_pa']),divisions=24)
    for name,c in (('envelope_simple',representative),('envelope_clamped',replace(representative,support='clamped')),
                   ('area_mean_simple',replace(representative,compression_pa=max(0.,-diag['area_mean_sigma_pa']),shear_pa=abs(diag['area_mean_tau_pa'])))):
        controls[name]=run_plate(c,paths['calculix'],work/'representative_plates'/name)
    ref=controls['envelope_simple']
    controls['envelope_half_reference']=run_plate(representative,paths['calculix'],work/'representative_plates/half_reference',reference_scale=ref['native_reference_scale']/2)
    controls['envelope_mesh32']=run_plate(replace(representative,divisions=32),paths['calculix'],work/'representative_plates/mesh32')
    checks={'same_resultants':all(np.allclose(v['mapping']['input_force_n'],baseline['mapping']['input_force_n'],atol=1e-8,rtol=1e-12) and
              np.allclose(v['mapping']['input_moment_nm'],baseline['mapping']['input_moment_nm'],atol=1e-8,rtol=1e-12) for v in rows),
            'same_mass':all(v['structure_mass_kg']==baseline['structure_mass_kg'] for v in rows),
            'same_geometry':len({v['source_mesh_sha256'] for v in rows})==1,
            'representative_reference_scaling_error':abs(controls['envelope_half_reference']['first_factor']/ref['first_factor']-1),
            'representative_mesh_24_32_error':abs(controls['envelope_mesh32']['first_factor']/ref['first_factor']-1)}
    out={'rows':rows,'aero':aero,'representative_plates':controls,'checks':checks,
         'passed':bool(checks['same_resultants'] and checks['same_mass'] and checks['same_geometry'] and checks['representative_reference_scaling_error']<.001 and checks['representative_mesh_24_32_error']<.02),
         'risk_status':'local_buckling_not_cleared','physical_validation_passed':False,'whole_wing_buckling_checked':False,
         'limits':['相同几何、条带和质量的受控敏感性；映射带宽为高斯参数，实际截断半径为其 1.5 倍',
         'translations_fixed 固定根部全部节点三向位移、释放壳局部转角；并非根部自由铰或真实连接刚度模型',
         '代表板由膜应力包络/面积均值驱动，四边简支/固支分别是假设；单板特征值不作为全翼失稳或实际极限载荷',
         '均值与同点指标仅解释包络保守性，不替代最大包络判据；本轮不自动增厚或回写结构质量']}
    out['status']='executed_with_limits' if out['passed'] else 'failed';write_json(work/'summary.json',out);return out
