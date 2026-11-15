"""Persist design intent through one API used by the local UI and CLI."""
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from . import __version__
from .adapters import sha256
from .requirements import DesignProject, build_design_intent, WEIGHT_LABELS, MISSION_LABELS
from .service import write_json, run_reference


def prepare_design_project(project, root):
    p = DesignProject.from_dict(project) if isinstance(project, dict) else project
    p.check_schema()
    started = datetime.now(timezone.utc).isoformat()
    work = Path(root).resolve()/'runs'/uuid4().hex
    work.mkdir(parents=True)
    write_json(work/'input.json', p.to_dict())
    intent = build_design_intent(p)
    write_json(work/'design_intent.json', intent)
    lines = [f'# {p.name}', '', '本记录为需求定义与接口准备；飞机性能及可行性尚未求解。', '',
             f'状态：{intent["status"]}', f'需求版本：{p.definition_hash()}',
             f'载荷合计：{p.payload_kg:g} kg（含机组、乘员、行李、任务设备）',
             f'重量模式：{WEIGHT_LABELS[p.weight.mode]}；规定值/上限（kg）：{p.weight.value_kg}',
             f'任务类型：{MISSION_LABELS[p.mission.kind]}',
             f'主任务或往返总航程（m）：{p.mission.range_m}',
             f'主任务最低航时或额外留空（s）：{p.mission.endurance_s}',
             f'额外储备（s）：{p.assumptions.reserve_duration_s}', '',
             '储备不计入主任务航程/航时；转场与留空仅在显式选择往返加留空时分列。',
             f'巡航真空速（m/s）：{p.assumptions.cruise_speed_m_s}；高度（m）：{p.assumptions.cruise_altitude_m}',
             '环境：标准大气、无风；构型：常规金属单发活塞螺旋桨。', '', '假设来源：']
    lines += [f'- {name}：{value}' for name, value in p.assumptions.sources.items()]
    lines += ['', '定尺寸假设：']+[f'- {name}：{value}' for name,value in p.sizing.to_dict().items()]
    lines += ['', '下一步：点击“运行初步总体设计”或调用 run_sizing。完整任务定义见 design_intent.json。']
    lines += [f'- {d["message"]}' for d in intent['diagnostics']]
    (work/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    source = Path(__file__).parent
    r = {'run_id': work.name, 'version': __version__, 'mode': 'design_intent', 'status': intent['status'],
         'input_hash': sha256(work/'input.json'), 'definition_sha256': p.definition_hash(),
         'started_utc': started,
         'finished_utc': datetime.now(timezone.utc).isoformat(), 'summary': intent,
         'source_hashes': {f.relative_to(source).as_posix(): sha256(f) for f in source.rglob('*.py')},
         'physical_validation_passed': False,
         'artifact_hashes': {f.name: sha256(f) for f in work.iterdir() if f.is_file()}}
    write_json(work/'result.json', r)
    return r


def run_fastga_reference(root):
    """Fixed upstream task only; no custom project is silently substituted."""
    return run_reference(root, 'fastga')
