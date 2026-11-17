"""One bounded historical XFOIL failure replay and actual CCBlade import check.

Run after the representative native job, never alongside another native batch.
The archived failure inputs are read-only; neither polar bounds nor algorithms change.
"""
from pathlib import Path
import json
import time
from wingdesignhub.jobs import read,atomic
from wingdesignhub.adapters import sha256,tool_paths
from wingdesignhub.geometry_service import source_hashes
from wingdesignhub.xfoil_polars import PolarSpec,PolarError,run_polar,commands
from wingdesignhub.requirements import DesignProject
from wingdesignhub.service import get_results
from wingdesignhub.project_archive import build_bundle,read_bundle

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'local/v031/diagnostics'


def main():
    state=read(ROOT/'local/v031/native/checkpoint.json')
    assert state['source_hashes']==source_hashes()
    assert read(ROOT/'local/jobs'/state['native_job_id']/'job.json')['status']=='completed'
    WORK.mkdir(parents=True,exist_ok=False)
    tools=read(ROOT/'local/jobs'/state['tools_job_id']/'job.json')
    assert tools['status']=='completed' and tools['engineering_status']=='runtime_checked'
    runtime=read(ROOT/'runs'/tools['run_id']/'result.json')['summary']
    checks={}
    checks['actual_ccblade_import']=runtime['status']=='runtime_checked'
    old_root=ROOT/'local/v030-infeasible02/workspace'
    old_id='39d34c3a5cb6493eba089a98cee9c3ea';old_work=old_root/'runs'/old_id
    old=get_results(old_root,old_id);before=sha256(old_work/'result.json')
    old_polar=old_work/'native/trial_002/point_005/polars/HorizontalTail/0'
    spec=PolarSpec(**old['diagnostic_context']['conditions'])
    checks['identical_commands']=commands(spec)==(old_polar/'stdin.txt').read_text('utf-8')
    assert checks['identical_commands']
    start=time.perf_counter();status='completed';detail=None
    try:run_polar(old_polar/'foil.dat',spec,tool_paths(ROOT)['xfoil'],WORK/'polar',cache=None)
    except PolarError as exc:status=exc.status;detail={'message':str(exc),'context':exc.context}
    elapsed=time.perf_counter()-start
    log=(WORK/'polar/stdout.log').read_text('utf-8',errors='replace')
    checks['polar_failure_reproduced']=status=='polar_failed' and ('NaN' in log or 'TRCHEK2' in log)
    checks['foil_unchanged']=sha256(old_polar/'foil.dat')==sha256(WORK/'polar/foil.dat')
    checks['original_failure_preserved']=before==sha256(old_work/'result.json')
    project=DesignProject.from_dict(read(old_work/'input.json'))
    seed=get_results(old_root,old['parent_run_id'])
    data=build_bundle(project,old_root,seed,coupled_record=old,current_run_id=old_id)
    parsed=read_bundle(data)
    checks['failed_record_reopened']=parsed['coupled_records']==[old] and parsed['manifest']['current_run_id']==old_id
    checks['failed_report_selected']=parsed['files']['reports/report.html']==(old_work/'report.html').read_bytes()
    result={'checks':checks,'ccblade':runtime,'polar_status':status,'polar_elapsed_s':elapsed,'diagnostic':detail,
        'source_hashes':source_hashes(),'old_run_id':old_id,'original_result_sha256':before,
        'foil_sha256':sha256(old_polar/'foil.dat'),'conditions':old['diagnostic_context'],
        'role':'failure diagnosis replay; fixed-weight budget validation remains incomplete'}
    atomic(WORK/'validation.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='source_hashes'},ensure_ascii=False))
    assert all(checks.values()),checks


if __name__=='__main__':main()
