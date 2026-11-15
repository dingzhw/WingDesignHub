"""Isolated fixed-reference FAST-GA evaluation with runtime interface audit."""
import json
import math
import os
from pathlib import Path
import shutil
from importlib.metadata import version
from .adapters import sha256
from .fastga_interface import VARIABLES, BASELINE_KG, REFERENCE_HASH, get_fastga_contract
from .service import write_json


def audit_problem(problem):
    metadata = problem.model.get_io_metadata(iotypes='output', metadata_keys=['units'])
    values, bindings = {}, {}
    for key, (name, unit, expected) in VARIABLES.items():
        matches = [(n, m) for n, m in metadata.items() if m.get('prom_name') == name]
        if len(matches) != 1:
            raise ValueError(f'FAST-GA 变量来源不唯一：{name}')
        absolute, meta = matches[0]
        role = 'input' if absolute.startswith('_auto_ivc.') else 'output'
        if role != expected:
            raise ValueError(f'FAST-GA 输入/输出角色变化：{name}')
        value = float(problem.get_val(name, units=unit).item())
        if not math.isfinite(value):
            raise ValueError(f'FAST-GA 标量非有限：{name}')
        values[key] = value
        bindings[key] = {'name': name, 'absolute_source': absolute, 'role': role,
                         'native_units': meta['units'], 'reporting_units': unit or 'unitless', 'value': value}
    return values, bindings


def mission_ledger(problem, values):
    def scalar(name, unit):
        x = float(problem.get_val(name, units=unit).item())
        if not math.isfinite(x) or x < 0:
            raise ValueError(f'任务账目无效：{name}')
        return x
    prefix = 'data:mission:sizing:'
    fuel = {phase: scalar(prefix+phase+':fuel', 'kg') for phase in
            ('taxi_out', 'takeoff', 'initial_climb', 'main_route:climb', 'main_route:cruise',
             'main_route:reserve', 'main_route:descent', 'taxi_in')}
    distance = {phase: scalar(prefix+'main_route:'+phase+':distance', 'm') for phase in ('climb', 'cruise', 'descent')}
    duration = {phase: scalar(prefix+'main_route:'+phase+':duration', 's') for phase in ('climb', 'cruise', 'descent')}
    k = scalar('settings:mission:sizing:main_route:reserve:k_factor', None)
    if duration['cruise'] <= 0:
        raise ValueError('公开参考任务巡航时长应大于零')
    expected_reserve = fuel['main_route:cruise']/duration['cruise']*values['reserve_duration']*k
    errors = {'mass_balance_kg': values['mtow']-values['owe']-values['payload']-values['fuel'],
              'fuel_sum_kg': sum(fuel.values())-values['fuel'],
              'reserve_formula_kg': fuel['main_route:reserve']-expected_reserve,
              'payload_formula_kg': values['payload']-((values['passengers_excluding_two_pilots']+2)*values['person_mass']+values['luggage']),
              'range_m': sum(distance.values())-values['range']}
    checks = {k: abs(v) <= (max(1., .001*values['range']) if k == 'range_m' else .01) for k, v in errors.items()}
    return {'fuel_by_phase_kg': fuel, 'main_route_distance_m': distance, 'main_route_duration_s': duration,
            'main_route_time_total_s': sum(duration.values()), 'reserve_duration_s': values['reserve_duration'],
            'reserve_k_factor': k, 'reserve_fuel_kg': fuel['main_route:reserve'],
            'non_reserve_fuel_kg': values['fuel']-fuel['main_route:reserve'],
            'fuel_includes_reserve': True, 'errors': errors, 'checks': checks,
            'note': '主航线时长只合计爬升/巡航/下降；地面滑行、起飞/初始爬升及储备另列，非整段总空中时间'}


def evaluate_reference(work):
    import fastga
    import fastoad.api as oad
    from .fastga_compat import compatibility, PROVIDER, SERVICE_FURNITURE_MASS, FurnitureMass
    from .fastga_diagnostics import collect_diagnostics, final_domain_checks
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    source = Path(fastga.__file__).parent/'notebooks/tutorial/data/beechcraft_76.xml'
    if sha256(source) != REFERENCE_HASH:
        raise ValueError('FAST-GA 公开参考输入哈希变化，须先复核基线')
    shutil.copy2(source, work/'reference_source.xml')
    previous = Path.cwd()
    try:
        os.chdir(work)
        config = work/'oad_process.yml'
        with compatibility(), collect_diagnostics() as (diagnostics, python_warnings):
            oad.generate_configuration_file(config, distribution_name='fast-oad-cs23', sample_file_name='fastga.yml')
            with config.open('a', encoding='utf-8') as stream:
                stream.write(f'\nsubmodels:\n  {SERVICE_FURNITURE_MASS}: {PROVIDER}\n')
            oad.generate_inputs(config, source)
            problem = oad.evaluate_problem(config)
            domain = final_domain_checks(problem)
            if not any(isinstance(c, FurnitureMass) for c in problem.model.system_iter()):
                raise RuntimeError('FAST-GA 家具质量替换未生效')
            values, bindings = audit_problem(problem)
            ledger = mission_ledger(problem, values)
            outputs = {name: float(problem.get_val(name, units='kg').item()) for name in BASELINE_KG}
            deviations = {name: abs(value-BASELINE_KG[name]) for name, value in outputs.items()}
            solver = problem.model.aircraft_sizing.nonlinear_solver
            norm, norm0 = float(solver._iter_get_norm()), float(solver._norm0)
            converged = math.isfinite(norm) and (norm <= solver.options['atol'] or (norm0 > 0 and norm/norm0 <= solver.options['rtol']))
            convergence = {'converged': converged, 'iterations': solver._iter_count, 'residual_norm': norm,
                           'initial_norm': norm0, 'rtol': solver.options['rtol'], 'atol': solver.options['atol']}
            problem.cleanup()
        passed = converged and all(v <= 1e-5 for v in deviations.values()) and all(ledger['checks'].values())
        limited = any(not d['within_range'] for d in domain) or bool(diagnostics)
        contract = get_fastga_contract()
        write_json(work/'interface_audit.json', {'contract': contract, 'actual_bindings': bindings})
        write_json(work/'mission_ledger.json', ledger)
        result = {'status': ('executed_with_limits' if limited else 'executed') if passed else 'failed',
                  'passed': passed, 'source_sha256': sha256(source), 'reference_hash_matches': True,
                  'reference': 'FAST-GA 1.4.0 bundled Beechcraft 76 tutorial', 'outputs_kg': outputs,
                  'baseline_difference_kg': deviations, 'baseline_tolerance_kg': 1e-5,
                  'convergence': convergence, 'interface': contract, 'actual_bindings': bindings,
                  'mission_ledger': ledger, 'reference_parameters': values,
                  'versions': {n: version(n) for n in ('fast-oad-cs23', 'fast-oad-core', 'openmdao', 'pandas', 'numpy')},
                  'compatibility': ['furniture_identity_derivative_1', 'mission_csv_dataframe_map'],
                  'final_domain_checks': domain, 'domain_check_scope': 'observed correlations only',
                  'diagnostics': diagnostics, 'python_warnings': python_warnings,
                  'custom_design_solved': False, 'gradient_optimization_supported': False,
                  'physical_validation_passed': False}
        write_json(work/'summary.json', result)
        return result
    finally:
        os.chdir(previous)
