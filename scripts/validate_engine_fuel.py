"""Pinned upstream engine regression and independent shaft fuel/mass units."""
from pathlib import Path
import importlib.util,json,math,sys,urllib.request
import numpy as np
from wingdesignhub.engine_fuel import EngineFuelModel
from wingdesignhub.fastga_mass import FastGAMassModel
from wingdesignhub.requirements import DesignProject
from wingdesignhub.sizing_physics import geometry
from wingdesignhub.service import write_json
from wingdesignhub.adapters import sha256

URL='https://raw.githubusercontent.com/supaero-aircraft-design/FAST-GA/v1.4.0/src/fastga/models/propulsion/fuel_propulsion/basicIC_engine/unitary_tests/test_basicIC_engine.py'
SHA='f1658cecf67d66eb16e838b741b27220ca48feade048ad1f3c944ba4d2c61af5'


def main(target,source=None):
    work=Path(target).resolve();work.mkdir(parents=True,exist_ok=False)
    path=work/'test_basicIC_engine.py'
    path.write_bytes(Path(source).read_bytes() if source else urllib.request.urlopen(URL,timeout=30).read())
    if sha256(path)!=SHA:raise ValueError('官方测试文件与固定v1.4.0内容不符')
    name='fastga.models.propulsion.fuel_propulsion.basicIC_engine.unitary_tests.pinned_public_test'
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    upstream=[]
    for name in ('test_compute_flight_points','test_engine_weight','test_engine_dim'):
        try:getattr(module,name)();upstream.append({'test':name,'passed':True})
        except Exception as exc:upstream.append({'test':name,'passed':False,'error':str(exc)})
    engine=EngineFuelModel(160000.);node_errors=[]
    for j,rpm in enumerate(engine.rpm):
        for i,q in enumerate(engine.torque_nodes):
            power=q*rpm*math.pi/30;point=engine.operating_point(power,float(rpm),2000,'cruise',.3)
            expected=engine.sfc_grid[j,i]/1000
            node_errors.append(float(abs(point['fuel_flow_kg_s']*3600/(power/1000*expected)-1)))
    # Independent installation factor and lb-to-kg conversion, not the FAST-GA output reused as expected.
    p=DesignProject().confirmed();g=geometry(1240.,100.,p);weights=[]
    with FastGAMassModel() as model:
        for power in (140000.,150000.,160000.):
            result=model.evaluate(1240.,power,g,p)
            expected=1.4*(power/745.7-21.55)/.5515*.45359237
            actual=result['components_kg']['data:weight:propulsion:engine:mass']
            weights.append({'rated_power_w':power,'expected_installed_engine_mass_kg':expected,'actual_installed_engine_mass_kg':actual,
                            'relative_error':actual/expected-1,'passed':abs(actual/expected-1)<1e-12})
    output={'source_url':URL,'source_sha256':sha256(path),'role':'upstream numerical regression and same-map implementation identity; not independent target-engine experiment',
        'official_tests':upstream,'sfc_node_count':len(node_errors),'sfc_node_max_relative_error':max(node_errors),'installed_mass_checks':weights,
        'engine':engine.evidence,'calibration_ids':[],'independent_target_engine_validation':False,
        'passed':all(r['passed'] for r in upstream+weights) and max(node_errors)<1e-12}
    write_json(work/'validation.json',output);print(json.dumps(output,ensure_ascii=False,indent=2),flush=True)
    if not output['passed']:raise RuntimeError('公开发动机模块检查失败，保留原始文件与诊断')
    return output


if __name__=='__main__':main(sys.argv[1],sys.argv[2] if len(sys.argv)>2 else None)
