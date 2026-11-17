"""Isolated allowlisted engineering entry points for the local queue."""
from pathlib import Path
import sys
import traceback
from .jobs import read,atomic


def dispatch(root,request):
    from .sizing_service import run_sizing
    from .feedback_service import run_aero_feedback
    from .coupled_service import run_coupled
    from .comparison_service import run_comparison
    from .geometry_service import run_aircraft_geometry
    from .aero_service import run_aircraft_aero
    from .trim_service import run_aircraft_trim
    from .drag_service import run_aircraft_drag
    from .propulsion_service import run_propulsion
    from .design_service import run_fastga_reference
    kind=request['kind'];project=request['project']
    if kind=='tools':
        from uuid import uuid4
        from .tool_health import check_ccblade
        work=Path(root)/'runs'/uuid4().hex
        record={'run_id':work.name,'mode':'tool_check','status':'running'}
        atomic(work/'result.json',record)
        try:record.update(summary=check_ccblade(root,work),status='runtime_checked')
        except Exception as exc:record.update(status='failed',error=str(exc))
        atomic(work/'result.json',record);return record
    if kind=='size':return run_sizing(project,root)
    if kind=='compare':return run_comparison(project,root)
    if kind=='fastga_reference':return run_fastga_reference(root)
    methods={'feedback':run_aero_feedback,'coupled':run_coupled,'geometry':run_aircraft_geometry,
             'aero':run_aircraft_aero,'trim':run_aircraft_trim,'drag':run_aircraft_drag,'propulsion':run_propulsion}
    return methods[kind](project,root,request['parent_run_id'],request['options'])


def main(root,directory):
    try:
        r=dispatch(Path(root),read(Path(directory)/'request.json'))
        from .jobs import code_identity
        if read(Path(directory)/'job.json')['source_hashes']!=code_identity():
            raise ValueError('运行期间源码发生变化，结果保留供诊断，请重新提交固定版本的计算。')
        result={'run_id':r['run_id'],'engineering_status':r['status']}
        if r.get('error'):result['error']=r['error']
        if r.get('diagnostic_context'):result['diagnostic_context']=r['diagnostic_context']
        atomic(Path(directory)/'outcome.json',result)
        return 0
    except Exception as exc:
        atomic(Path(directory)/'outcome.json',{'error':str(exc)})
        (Path(directory)/'error.log').write_text(traceback.format_exc(),encoding='utf-8')
        return 1


if __name__=='__main__':raise SystemExit(main(*sys.argv[1:]))
