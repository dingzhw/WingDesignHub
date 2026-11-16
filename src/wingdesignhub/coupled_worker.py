"""Isolated native engine/propeller/airframe overall calculation."""
from pathlib import Path
from importlib.metadata import version
import json,sys,traceback,shutil,hashlib
from .requirements import DesignProject
from .fastga_mass import FastGAMassModel
from .sizing import solve_design
from .propulsion_feedback import PropulsionFeedback,CoupledOptions
from .service import write_json


def comparison(baseline,summary):
    rows=[]
    paths=[('设计起飞重量',('design_mtow_kg',),'kg'),('实际起飞装载',('cg','loaded_mass_kg'),'kg'),
        ('总可用燃油',('mission','block_fuel_kg'),'kg'),('储备油',('mission','reserve_fuel_kg'),'kg'),
        ('安装额定轴功率',('power','installed_power_w'),'W'),('翼面积',('geometry','wing_area_m2'),'m²'),
        ('翼展',('geometry','wing_span_m'),'m'),('可用油箱容量',('geometry','usable_tank_capacity_kg'),'kg'),
        ('空重',('weights','owe_kg'),'kg'),('动力系统质量',('weights','categories_kg','propulsion'),'kg'),
        ('发动机质量',('weights','components_kg','data:weight:propulsion:engine:mass'),'kg'),('起飞重心站位',('cg','cg_x_m'),'m')]
    for label,path,unit in paths:
        a=baseline;b=summary
        for key in path:a=a[key];b=b[key]
        rows.append({'quantity':label,'unit':unit,'before':a,'after':b,'relative_change':b/a-1})
    return {'basis':'same requirements; both designs resized with their recorded models; original design is retained',
            'comparison_type':'redesign','rows':rows}


def main(work):
    work=Path(work).resolve();root=work.parents[1]
    p=DesignProject.from_dict(json.loads((work/'input.json').read_text('utf-8')))
    options=CoupledOptions.from_dict(json.loads((work/'options.json').read_text('utf-8')))
    parent=json.loads((work/'parent_result.json').read_text('utf-8'))
    try:
        feedback=PropulsionFeedback(root,work,p,options)
        with FastGAMassModel() as model:
            summary=solve_design(p,model,options.aero.max_iterations,options.aero.integration_step_s,
                                 feedback=feedback,initial_summary=parent['summary'])
            if summary.get('status')=='out_of_domain':
                from .propulsion_model import PropulsionError
                write_json(work/'incomplete_summary.json',summary)
                raise PropulsionError(summary.get('error_code','out_of_domain'),
                    '; '.join(summary.get('diagnostics') or ['总体试算超出模型范围']),
                    **summary.get('diagnostic_context',{}))
            write_json(work/'fastga_mass_inputs.json',model.last_inputs);write_json(work/'fastga_mass_interface.json',model.audit)
            from .coupled_identity import model_identity
            last=feedback.last
            geometry=json.loads((last['native'].geometry_work/'summary.json').read_text('utf-8'))
            evidence,summary['model_signature']=model_identity(model.audit['upstream_mass_source_hashes'],
                last['flight'].engine.evidence,last['flight'].propeller.data,last['native'].evidence(),
                {k:geometry[k] for k in ('openvsp_version','native_binary_hashes','template_version')})
            write_json(work/'model_evidence.json',evidence)
        summary['versions']={n:version(n) for n in ('fast-oad-cs23','fast-oad-core','openmdao','numpy','wingdesignhub')}
        if 'geometry' in summary:
            summary['redesign_comparison']=comparison(parent['summary'],summary)
            write_json(work/'comparison.json',summary['redesign_comparison'])
            write_json(work/'aircraft_parameters.json',{k:summary[k] for k in ('geometry','weights','power','cg')})
            from .sizing_worker import geometry_svg
            (work/'geometry.svg').write_text(geometry_svg(summary['geometry']),encoding='utf-8')
            dest=work/'final_geometry';dest.mkdir()
            for name in ('aircraft.vsp3','geometry_contract.json','aerodynamic_geometry.json','summary.json'):
                shutil.copy2(feedback.last['native'].geometry_work/name,dest/name)
        write_json(work/'summary.json',summary)
    except Exception as exc:
        write_json(work/'failure.json',{'status':getattr(exc,'status','failed'),'error':str(exc),'diagnostic_context':getattr(exc,'context',{})})
        (work/'error.log').write_text(traceback.format_exc(),encoding='utf-8');raise
    print(summary['status'],flush=True)


if __name__=='__main__':main(sys.argv[1])
