"""Isolated native aerodynamics and FAST-GA overall iteration."""
from pathlib import Path
from importlib.metadata import version
import json,sys,traceback,shutil,hashlib
from .requirements import DesignProject
from .fastga_mass import FastGAMassModel
from .sizing import solve_design
from .aero_feedback import AeroFeedback,FeedbackOptions
from .service import write_json
from .adapters import sha256


def main(work):
    work=Path(work).resolve();root=work.parents[1]
    p=DesignProject.from_dict(json.loads((work/'input.json').read_text('utf-8')))
    options=FeedbackOptions.from_dict(json.loads((work/'options.json').read_text('utf-8')))
    parent=json.loads((work/'parent_result.json').read_text('utf-8'));baseline=parent['summary']
    try:
        feedback=AeroFeedback(root,work,p,options)
        with FastGAMassModel() as model:
            summary=solve_design(p,model,options.max_iterations,options.integration_step_s,feedback=feedback,initial_summary=baseline)
            write_json(work/'fastga_mass_inputs.json',model.last_inputs);write_json(work/'fastga_mass_interface.json',model.audit)
            evidence={'mass_sources':model.audit.get('upstream_mass_source_hashes',{}),'engine_sources':model.audit.get('propeller_constructor_source_sha256')}
            summary['model_signature']=hashlib.sha256(json.dumps(evidence,sort_keys=True).encode()).hexdigest()
            write_json(work/'model_evidence.json',evidence)
        summary['versions']={n:version(n) for n in ('fast-oad-cs23','fast-oad-core','openmdao','numpy','wingdesignhub')}
        if 'geometry' in summary:
            comparison=[]
            for label,path,unit in [('设计起飞重量',('design_mtow_kg',),'kg'),('总可用燃油',('mission','block_fuel_kg'),'kg'),
                                    ('安装轴功率',('power','installed_power_w'),'W'),('翼面积',('geometry','wing_area_m2'),'m²'),
                                    ('空重',('weights','owe_kg'),'kg')]:
                old=baseline;new=summary
                for key in path:old=old[key];new=new[key]
                comparison.append({'quantity':label,'unit':unit,'legacy':old,'feedback':new,'relative_change':new/old-1})
            summary['redesign_comparison']={'basis':'same requirements, different aerodynamic model and explicit speed schedule; both resized', 'rows':comparison}
            write_json(work/'comparison.json',{'redesign':summary['redesign_comparison'],'same_condition':summary.get('aerodynamic_feedback',{}).get('same_condition_comparison')})
            write_json(work/'aircraft_parameters.json',{k:summary[k] for k in ('geometry','weights','power','cg')})
            from .sizing_worker import geometry_svg
            (work/'geometry.svg').write_text(geometry_svg(summary['geometry']),encoding='utf-8')
            final=feedback.last['native'].geometry_work
            dest=work/'final_geometry';dest.mkdir()
            for name in ('aircraft.vsp3','geometry_contract.json','aerodynamic_geometry.json','summary.json'):
                shutil.copy2(final/name,dest/name)
        write_json(work/'summary.json',summary)
    except Exception as exc:
        write_json(work/'failure.json',{'status':getattr(exc,'status','failed'),'error':str(exc),'diagnostic_context':getattr(exc,'context',{})})
        (work/'error.log').write_text(traceback.format_exc(),encoding='utf-8')
        raise
    print(summary['status'],flush=True)


if __name__=='__main__':main(sys.argv[1])
