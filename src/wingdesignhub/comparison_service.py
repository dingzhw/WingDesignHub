"""Recorded three-design orchestration, shared by UI/CLI/Python."""
from pathlib import Path
from datetime import datetime,timezone
from uuid import uuid4
import json
import traceback
from zipfile import ZipFile,ZIP_DEFLATED
from . import __version__
from .adapters import sha256
from .requirements import DesignProject
from .design_comparison import ComparisonRequest,summarize_comparison,check_record
from .design_cards import card_html,comparison_markdown
from .service import get_results,write_json
from .sizing_service import run_sizing
from .coupled_service import run_coupled


def _save(request,root,records=None,on_progress=None,complete=False):
    request.validate();root=Path(root).resolve();work=root/'runs'/uuid4().hex;work.mkdir(parents=True)
    write_json(work/'input.json',request.to_dict())
    result={'run_id':work.name,'version':__version__,'mode':'overall_comparison','status':'running',
            'definition_sha256':request.definition_hash(),'input_hash':sha256(work/'input.json'),
            'started_utc':datetime.now(timezone.utc).isoformat(),'physical_validation_passed':False,
            'source_hashes':{p.relative_to(Path(__file__).parent).as_posix():sha256(p) for p in Path(__file__).parent.rglob('*.py')}}
    write_json(work/'result.json',result)
    try:
        if any(p.confirmation_sha256!=p.definition_hash() for p in request.projects):
            result.update(status='needs_confirmation',error='三个方案均需核对确认后计算')
        else:
            if records is None or complete:
                records=list(records or [])
                if len(records)>3:raise ValueError('最多复用三个已完成方案')
                for p,r in zip(request.projects,records):
                    check_record(request,p,r)
                    from .computation_identity import compatible
                    if r['version']!=__version__ or not compatible(r,root):
                        raise ValueError('复用记录源码或版本已改变，请重新计算')
                result['child_runs']=[r['run_id'] for r in records]
                for index,project in enumerate(request.projects[len(records):],len(records)):
                    result['progress']={'scheme':index,'stage':'initial'};write_json(work/'result.json',result)
                    if on_progress:on_progress(index,'initial',result['run_id'])
                    seed=run_sizing(project,root);r=seed
                    if request.analysis_model=='coupled' and seed.get('summary',{}).get('converged'):
                        result['progress']={'scheme':index,'stage':'coupled','seed_run_id':seed['run_id']}
                        write_json(work/'result.json',result)
                        if on_progress:on_progress(index,'coupled',result['run_id'])
                        r=run_coupled(project,root,seed['run_id'],request.options_dict())
                    records.append(get_results(root,r['run_id']))
                    # Checkpoint after each completed child; one failed solver does not hide the others.
                    result['child_runs']=[x['run_id'] for x in records];write_json(work/'result.json',result)
                    if on_progress:on_progress(index,'completed',result['run_id'])
            summary=summarize_comparison(request,records)
            result.update(status=summary['status'],summary=summary,child_runs=[r['run_id'] for r in records])
            write_json(work/'comparison.json',summary)
            for i,(p,r,card) in enumerate(zip(request.projects,records,summary['cards']),1):
                write_json(work/f'plan-{i}-input.json',p.to_dict());write_json(work/f'plan-{i}-result.json',r)
                write_json(work/f'plan-{i}-card.json',card)
                (work/f'plan-{i}-card.html').write_text(card_html(card),encoding='utf-8')
            (work/'report.md').write_text(comparison_markdown(summary),encoding='utf-8')
            from .design_report import comparison_report_html
            (work/'report.html').write_text(comparison_report_html(summary,result),encoding='utf-8')
            with ZipFile(work/'scheme-cards.zip','w',compression=ZIP_DEFLATED) as archive:
                for f in sorted(work.iterdir()):
                    if f.suffix in ('.html','.md') or f.name.endswith('-input.json') or f.name=='comparison.json':
                        archive.write(f,f.name)
    except Exception as exc:
        result.update(status='failed',error=str(exc));(work/'error.log').write_text(traceback.format_exc(),encoding='utf-8')
    if not (work/'report.html').exists():
        from .design_report import comparison_report_html
        (work/'report.html').write_text(comparison_report_html(result.get('summary',{}),result),encoding='utf-8')
    result['finished_utc']=datetime.now(timezone.utc).isoformat()
    result['artifact_hashes']={p.name:sha256(p) for p in work.iterdir() if p.is_file() and p.name!='result.json'}
    write_json(work/'result.json',result);return result


def run_comparison(request,root,*,reuse_run_ids=(),on_progress=None):
    req=ComparisonRequest.from_dict(request) if isinstance(request,dict) else request
    if req.analysis_model=='coupled':
        from dataclasses import replace,asdict
        from .propulsion_feedback import CoupledOptions
        req=replace(req,analysis_options=asdict(CoupledOptions.from_dict(req.analysis_options)))
    records=[get_results(root,rid) for rid in reuse_run_ids]
    return _save(req,root,records,on_progress,complete=True)


def compare_sizing_runs(root,run_ids,purpose='design_trade'):
    if len(run_ids)!=3:raise ValueError('请选择三个总体运行编号')
    root=Path(root).resolve();records=[get_results(root,rid) for rid in run_ids]
    projects=[DesignProject.from_dict(json.loads((root/'runs'/rid/'input.json').read_text(encoding='utf-8'))) for rid in run_ids]
    coupled=any(r.get('mode')=='overall_propulsion' for r in records)
    options=next((r['options'] for r in records if r.get('mode')=='overall_propulsion'),{})
    request=ComparisonRequest(tuple(projects),purpose,2,'coupled',options) if coupled else ComparisonRequest(tuple(projects),purpose)
    return _save(request,root,records)
