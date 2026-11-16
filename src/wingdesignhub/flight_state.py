"""Consistent operating mass/CG from the existing conceptual component ledger."""
from copy import deepcopy
import math


def finite(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(label+' 须为有限数值')
    return float(value)


def make_flight_state(summary, mass_state='takeoff', mass_kg=None, cg_x_m=None, source_note=''):
    if mass_state not in ('takeoff', 'mission_end', 'explicit'):
        raise ValueError('工况质量来源须为 takeoff、mission_end 或 explicit')
    mtow=finite(summary['design_mtow_kg'],'设计起飞质量')
    rows=deepcopy(summary['cg']['rows']);names=set()
    for row in rows:
        if row['component'] in names:raise ValueError('质量台账部件重复')
        names.add(row['component'])
        if finite(row['mass_kg'],'部件质量')<0:raise ValueError('部件质量不得为负')
        finite(row['x_m'],'部件位置')
    total=sum(r['mass_kg'] for r in rows)
    if total<=0 or not math.isclose(total,summary['required_loaded_mass_kg'],abs_tol=1e-6,rel_tol=1e-10):
        raise ValueError('质量台账与配置装载质量不一致')
    cg=sum(r['mass_kg']*r['x_m'] for r in rows)/total
    if not math.isclose(cg,summary['cg']['cg_x_m'],abs_tol=1e-9):raise ValueError('台账质量矩与总体重心不一致')
    fuel=next((r for r in rows if r['component']=='takeoff_fuel'),None)
    if fuel is None or not math.isclose(fuel['mass_kg'],summary['mission']['takeoff_fuel_kg'],abs_tol=1e-6):
        raise ValueError('可用起飞燃油台账不一致')
    burned=0.;mission=summary['mission']
    if mass_state=='explicit':
        mass=finite(mass_kg,'自定义工况质量');cg=finite(cg_x_m,'自定义重心')
        if not isinstance(source_note,str) or not source_note.strip():raise ValueError('自定义质量与重心须填写同一工况的来源/假设')
        if not 0<mass<=mtow:raise ValueError('自定义工况质量须为正且不大于设计起飞重量')
        if not 0<=cg<=summary['geometry']['fuselage_length_m']:raise ValueError('重心 x 须位于本模板机身长度内')
        state_rows=None;fuel_remaining=None
    else:
        if mass_kg is not None or cg_x_m is not None or source_note:
            raise ValueError('台账状态不接受额外质量/重心覆盖；请使用自定义同一工况')
        if mass_state=='mission_end':
            # Before taxi-in: reserve and taxi-in fuel are still carried.
            burned=finite(mission['takeoff_roll_fuel_kg'],'起飞滑跑耗油')+sum(finite(r['fuel_kg'],'任务耗油') for r in mission['segments'])
            if burned<0:raise ValueError('累计耗油不得为负')
            fuel['mass_kg']-=burned
            expected=mission['reserve_fuel_kg']+mission['taxi_in_fuel_kg']
            if not math.isclose(fuel['mass_kg'],expected,rel_tol=1e-9,abs_tol=1e-6):
                raise ValueError('任务结束燃油与储备/入场滑行账目不一致')
        if fuel['mass_kg']<0:raise ValueError('工况可用燃油小于零')
        mass=sum(r['mass_kg'] for r in rows);cg=sum(r['mass_kg']*r['x_m'] for r in rows)/mass
        # A solved MTOW may have the recorded 1e-4 iteration residual; do not clip it.
        if mass>mtow*(1+1e-4)+1e-6:raise ValueError('实际装载超出设计起飞质量，请先处理总体质量约束或明确自定义工况')
        state_rows=rows;fuel_remaining=fuel['mass_kg']
    return {'schema_version':1,'mass_state':mass_state,'operating_mass_kg':mass,
            'cg_geometry_m':[cg,0.,0.],'design_mtow_kg':mtow,'configured_takeoff_mass_kg':total,
            'unallocated_mass_budget_kg':mtow-total,'fuel_burned_from_takeoff_kg':burned if state_rows else None,
            'remaining_usable_fuel_kg':fuel_remaining,'component_ledger':state_rows,
            'source':source_note.strip() if mass_state=='explicit' else 'existing fixed-station component ledger; fuel at wing quarter chord',
            'phase':'end of airborne mission, before taxi-in' if mass_state=='mission_end' else mass_state,
            'scope':'conceptual x-CG; y=z=0 assumption; no payload relocation, tank distribution or CG envelope validation',
            'mass_budget_allocated_as_ballast':False,'unusable_fuel_in_empty_mass_once':True}
