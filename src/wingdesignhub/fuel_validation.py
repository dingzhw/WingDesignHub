"""Reproducible fuel evidence, with calibration and held-out roles kept separate."""
from dataclasses import replace
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
from . import __version__
from .adapters import sha256
from .service import write_json
from .sizing_config import SizingAssumptions
from .fuel_model import (CALIBRATION,HOLDOUT,LYCOMING_REFERENCE,PIPER_SOURCE,HP_W,LB_KG,
                         calibrated_bsfc,fuel_flow)


def evaluate_fuel_model():
    base=SizingAssumptions();economy=replace(base,fuel_model='piper_economy_reference');rows=[]
    for point in (CALIBRATION,*HOLDOUT):
        rated=point['rated_hp']*HP_W;power=rated*point['power_fraction']
        predicted=fuel_flow(power,rated,'cruise',economy)[0]*3600/(6*LB_KG)
        original=fuel_flow(power,rated,'cruise',base)[0]*3600/(6*LB_KG)
        error=predicted/point['fuel_us_gal_h']-1
        rows.append({**point,'original_gal_h':original,'predicted_gal_h':predicted,'relative_error':error,
                     'diagnostic_limit_relative':.05 if point['role']=='same_source_holdout' else None,
                     'holdout_pass':abs(error)<=.05 if point['role']=='same_source_holdout' else None})
    held=[r for r in rows if r['role']=='same_source_holdout']
    return {'status':'fuel_reference_checked_with_limits' if all(r['holdout_pass'] for r in held) else 'model_discrepancy','source':PIPER_SOURCE,'rows':rows,
            'calibrated_bsfc_kg_kwh':calibrated_bsfc(),'holdout_passed':all(r['holdout_pass'] for r in held),
            'calibration_ids':[CALIBRATION['id']],'holdout_ids':[p['id'] for p in HOLDOUT],
            'external_reference':LYCOMING_REFERENCE,'external_same_condition_validation_passed':None,
            'independent_validation_data_available':False,'physical_validation_passed':False,
            'diagnosis':'原 26.5% 为统一 BSFC 与经济混合比点的差异；保留基础模型，增加有范围和数据角色的参考选项。',
            'limits':['校准点误差不计为验证通过；55%/75% 仅为同手册留出检查。',
                      'Lycoming 外部资料的安装/混合比条件未对齐，独立试验资料仍缺。',
                      '新模型不改变极曲线或桨效率；V0.1.8 的速度偏差未通过调参消除。']}


def run_fuel_validation(root):
    work=Path(root)/'runs'/uuid4().hex;work.mkdir(parents=True)
    write_json(work/'input.json',{'calibration':CALIBRATION,'holdout':HOLDOUT,'external_reference':LYCOMING_REFERENCE})
    summary=evaluate_fuel_model();write_json(work/'summary.json',summary)
    result={'run_id':work.name,'version':__version__,'mode':'fuel_model_validation','status':summary['status'],
            'summary':summary,'finished_utc':datetime.now(timezone.utc).isoformat(),
            'input_hash':sha256(work/'input.json'),'physical_validation_passed':False,
            'source_hashes':{p.relative_to(Path(__file__).parent).as_posix():sha256(p) for p in Path(__file__).parent.rglob('*.py')},
            'artifact_hashes':{p.name:sha256(p) for p in work.iterdir() if p.is_file()}}
    write_json(work/'result.json',result);return result
