"""Serial native workflow acceptance; local historical runs are explicit inputs."""
from dataclasses import replace
from pathlib import Path
import argparse,json,time
from wingdesignhub.jobs import code_identity
from wingdesignhub.requirements import DesignProject,WeightRequirement
from wingdesignhub.service import get_results,write_json


def main(root,work,baseline,stage):
    root=Path(root).resolve();work=Path(work).resolve();work.mkdir(parents=True,exist_ok=True)
    frozen=code_identity();f=work/'freeze.json'
    if f.exists():assert json.loads(f.read_text('utf8'))==frozen,'source changed'
    else:write_json(f,frozen)
    old=get_results(root,baseline,verify_native=False)
    p=DesignProject.from_dict(json.loads((root/'runs'/baseline/'input.json').read_text('utf8')))
    if stage=='initial':
        from wingdesignhub.sizing_service import run_sizing
        from wingdesignhub.comparison_service import run_comparison
        from wingdesignhub.design_comparison import variants
        seed=run_sizing(p,root);write_json(work/'seed.json',seed)
        assert seed['summary']['converged'],seed.get('error')
        old_seed=get_results(root,old['parent_run_id'],verify_native=False)
        keys=('design_mtow_kg','geometry','weights','power','cg','mission','constraint_states')
        assert all(seed['summary'][k]==old_seed['summary'][k] for k in keys)
        request=variants(p,'sizing.aspect_ratio',[7.5,8.25,9.])
        request=replace(request,projects=tuple(q.confirmed() for q in request.projects))
        r=run_comparison(request,root);write_json(work/'comparison.json',r)
        assert len(r.get('summary',{}).get('cards',[]))==3,r.get('error')
        assert all(c['metrics']['mtow_kg'] is not None for c in r['summary']['cards'])
        q=replace(p,weight=WeightRequirement('fixed',1000.)).confirmed()
        bad=run_sizing(q,root);write_json(work/'infeasible.json',bad)
        assert bad['status']=='constraints_not_met'
        write_json(work/'initial_checks.json',{'old_initial_equal':True,'three_actual_designs':True,'infeasible_preserved':True})
    elif stage=='native':
        from wingdesignhub.coupled_service import run_coupled
        seed=json.loads((work/'seed.json').read_text('utf8'))
        start=time.perf_counter();r=run_coupled(p,root,seed['run_id'],old['options'])
        write_json(work/'native.json',r)
        s=r.get('summary',{});o=old['summary']
        paths=[('design_mtow_kg',),('mission','block_fuel_kg'),('power','installed_power_w'),('geometry','wing_area_m2')]
        differences=[]
        for path in paths:
            a=o;b=s
            for k in path:a=a[k];b=b[k]
            differences.append({'quantity':'.'.join(path),'old':a,'new':b,'relative_difference':b/a-1})
        checks={'converged':bool(s.get('converged')),'status_preserved':r['status']==old['status'],
                'same_physics_results':all(abs(x['relative_difference'])<1e-8 for x in differences),
                'four_state_equal':s['constraint_states']==o['constraint_states']}
        write_json(work/'native_checks.json',{'elapsed_s':time.perf_counter()-start,'checks':checks,'differences':differences,
            'timing_role':'existing caches plus final native audit; not a cold/warm benchmark','baseline_run':baseline,'current_run':r['run_id']})
        assert all(checks.values()),checks
    elif stage=='ui':
        from streamlit.testing.v1 import AppTest
        from wingdesignhub.project_archive import build_bundle,read_bundle,save_bundle,load_saved
        from wingdesignhub.design_comparison import ComparisonRequest
        from wingdesignhub.structure_handoff import build,markdown
        seed=json.loads((work/'seed.json').read_text('utf8'));native=json.loads((work/'native.json').read_text('utf8'))
        cases=[]
        for name,record in [('native',native),('comparison',json.loads((work/'comparison.json').read_text('utf8'))),
                            ('infeasible',json.loads((work/'infeasible.json').read_text('utf8')))]:
            raw=json.loads((root/'runs'/record['run_id']/'input.json').read_text('utf8'))
            project=ComparisonRequest.from_dict(raw) if name=='comparison' else DesignProject.from_dict(raw)
            data=build_bundle(project,root,seed if name=='native' else record,
                              coupled_record=native if name=='native' else None,current_run_id=record['run_id'],profile='portable')
            saved=save_bundle(data,work/'portable');opened=load_saved(work/'portable',saved['archive_id'])
            assert opened['project']==project and opened['manifest']['current_run_id']==record['run_id']
            assert read_bundle(data)['files']['reports/report.html']==(root/'runs'/record['run_id']/'report.html').read_bytes()
            a=AppTest.from_string(f'from wingdesignhub.project_ui import library\nlibrary({str(work/"portable")!r})').run(timeout=60)
            a.selectbox(key='saved_archive_choice').set_value(saved['archive_id']).run()
            a.button(key='open_saved_design').click().run(timeout=60)
            assert not a.exception
            assert a.session_state['opened_archive']['manifest']['current_run_id']==record['run_id']
            tables=[x.value for x in a.dataframe if '状态' in x.value.columns]
            assert any('超限' in set(t['状态']) for t in tables)
            cases.append({'case':name,'run_id':record['run_id'],'bundle_bytes':len(data),'opened_via_button':True,
                          'report_identical':True,'exceedance_visible':True})
        handoff=build(p,native);write_json(work/'structure-inputs.json',handoff)
        (work/'structure-inputs.md').write_text(markdown(handoff),encoding='utf8')
        # Whole application: restore actual chain, select native, save selected record, invalidate input.
        app=AppTest.from_file(str(root/'app.py'))
        app.session_state['workspace_project']=p;app.session_state['sizing_result']=seed;app.session_state['coupled_result']=native
        app.run(timeout=60);key='current_design_run_'+p.definition_hash()
        app.selectbox(key=key).set_value(native['run_id']).run(timeout=60)
        assert not app.exception and app.selectbox(key=key).value==native['run_id']
        assert app.get('plotly_chart')
        app.button(key='design_save_local').click().run(timeout=60)
        assert not app.exception and '已保存' in app.session_state['archive_saved_note']
        next(x for x in app.number_input if x.label.startswith('任务载荷')).set_value(p.payload_kg+10).run(timeout=60)
        assert not app.exception and app.button(key='run_sizing').disabled
        assert any('上次总体结果' in x.value for x in app.info)
        write_json(work/'ui.json',{'cases':cases,'full_app_selected_geometry':True,'save_button':True,
                                 'changed_input_requires_confirmation':True,'handoff_run':handoff['run_id'],
                                 'structural_solution_ready':handoff['ready_for_structural_solution']})
    assert frozen==code_identity(),'source changed during validation'


if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--root',default='.');a.add_argument('--work',required=True)
    a.add_argument('--baseline',required=True);a.add_argument('--stage',choices=['initial','native','ui'],required=True)
    v=a.parse_args();main(v.root,v.work,v.baseline,v.stage)
