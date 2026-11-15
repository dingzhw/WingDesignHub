"""Independent S6 cantilever and representative-wing perturbation checks."""
from dataclasses import replace
from pathlib import Path
import numpy as np
from .shell_static import promote_s6,solve_shell,StaticWingCase,run_static_case
from .structure_service import generate_mesh
from .adapters import tool_paths
from .service import write_json
from .fea_mesh import StructureMeshCase


def plate_beam(executable,work,elements):
    """Narrow flat strip, nu=0, tip line load; Euler-Bernoulli analytic reference."""
    length,width,thickness,modulus,force=1.,.1,.02,70e9,1.
    nodes={};elements_map={}
    for j in range(elements+1):
        for i in range(3):nodes[3*j+i+1]=[-width/2+i*width/2,j*length/elements,0.]
    for j in range(elements):
        for i in range(2):
            a=3*j+i+1;b=a+1;c=a+4;d=a+3
            for conn in ([a,b,c],[a,c,d]):elements_map[len(elements_map)+1]=conn
    mesh={'nodes':nodes,'elements':elements_map,'types':{n:'S3' for n in elements_map},
          'sets':{'ESkin_plate':list(elements_map)},'sections':{'ESkin_plate':{'thickness_m':thickness,'material':'M'}},
          'materials':{'M':{'elastic_modulus_pa':modulus,'poisson_ratio':0.,'density_kg_m3':2700.}}}
    mesh=promote_s6(mesh)
    ids=sorted((n for n,p in mesh['nodes'].items() if p[1]==length),key=lambda n:mesh['nodes'][n][0])
    assert len(ids)==5
    forces=np.zeros((5,3));forces[:,2]=force*np.array([1,4,2,4,1])/12
    audit={'force_scale_n':force,'moment_scale_nm':force*length,'input_force_n':[0.,0.,force],
           'input_moment_nm':[force*length,0.,0.]}
    result=solve_shell(executable,work,mesh,ids,forces,length,audit)
    exact=force*length**3/(3*modulus*(width*thickness**3/12))
    error=abs(result['tip_mean_z_m']/exact-1)
    result.update(span_elements=elements,analytical_tip_m=exact,tip_relative_error=error,threshold=.02,
                  parameters_si={'length':length,'width':width,'thickness':thickness,'E':modulus,'nu':0.,'tip_force':force},
                  passed=error<.02)
    write_json(Path(work)/'summary.json',result);return result


def run_benchmark(root,work):
    root=Path(root);work=Path(work);work.mkdir(parents=True,exist_ok=True)
    executable=tool_paths(root)['calculix']
    if not executable or not Path(executable).is_file():raise FileNotFoundError('请配置 CalculiX 2.23')
    beams=[plate_beam(executable,work/f'plate_{n}',n) for n in (10,20,40)]
    case=StaticWingCase(mesh=StructureMeshCase());generate_mesh(case.mesh,work/'coarse_mesh')
    fine_case=replace(case,mesh=replace(case.mesh,max_edge_m=.2,min_edge_m=.02))
    generate_mesh(fine_case.mesh,work/'fine_mesh')
    refined_case=replace(case,mesh=replace(case.mesh,max_edge_m=.15,min_edge_m=.015))
    generate_mesh(refined_case.mesh,work/'refined_mesh')
    coarse=run_static_case(case,work/'coarse_mesh/wing.inp',executable,work/'coarse')
    fine=run_static_case(fine_case,work/'fine_mesh/wing.inp',executable,work/'fine')
    refined=run_static_case(refined_case,work/'refined_mesh/wing.inp',executable,work/'refined')
    doubled=run_static_case(replace(case,limit_lift_n=case.limit_lift_n*2),work/'coarse_mesh/wing.inp',executable,work/'double_load')
    negative=run_static_case(replace(case,limit_lift_n=-case.limit_lift_n),work/'coarse_mesh/wing.inp',executable,work/'negative_load')
    keys=('tip_mean_z_m','bulk_von_mises_p95_pa','peak_von_mises_pa')
    coarse_diffs={k:abs(coarse[k]-fine[k])/abs(fine[k]) for k in keys}
    diffs={k:abs(fine[k]-refined[k])/abs(refined[k]) for k in keys}
    ratios={'double_displacement':doubled['tip_mean_z_m']/coarse['tip_mean_z_m'],
            'double_stress':doubled['peak_von_mises_pa']/coarse['peak_von_mises_pa'],
            'negative_displacement':negative['tip_mean_z_m']/coarse['tip_mean_z_m'],
            'negative_stress':negative['peak_von_mises_pa']/coarse['peak_von_mises_pa']}
    passed=all(r['passed'] for r in beams) and diffs['tip_mean_z_m']<.05 and diffs['bulk_von_mises_p95_pa']<.1
    passed=passed and np.allclose(list(ratios.values()),[2.,2.,-1.,1.],rtol=2e-5,atol=1e-8)
    result={'status':'passed' if passed else 'failed','passed':bool(passed),'plate_beams':beams,
            'coarse':coarse,'fine':fine,'refined':refined,'double_load':doubled,'negative_load':negative,
            'coarse_to_fine_differences':coarse_diffs,'relative_mesh_differences':diffs,
            'mesh_comparison':'0.2/0.02 m versus 0.15/0.015 m; coarse 0.4 m stress statistic did not meet threshold',
            'mesh_thresholds':{'tip_mean_z_m':.05,'bulk_von_mises_p95_pa':.1},
            'load_ratios':ratios,'physical_validation_passed':False,'buckling_checked':False,
            'limits':coarse['limits']+['三档网格仅提供指定输出的敏感性证据；根部与交线峰值不作收敛验收']}
    write_json(work/'summary.json',result);return result
