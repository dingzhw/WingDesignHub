"""A held-out handbook operating point, not a whole-aircraft accuracy claim.

Piper VB-760 manufacturer handbook, section 5 pp. 5-4/5-5/5-19 and 1-2/1-3.
The cruise figure is at 2550 lb; the separate flight-plan loading is 2400 lb.
Use the figure's gross mass, not the flight-plan takeoff mass. No coefficient fit.
"""
from dataclasses import replace,asdict
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
import math
from . import __version__
from .sizing_config import SizingAssumptions
from .sizing_physics import flight_power,density,G
from .adapters import sha256
from .service import write_json

REFERENCE={
    'aircraft':'Piper PA-28-181 Cherokee Archer II', 'document':'Piper VB-760, issued 1975-08-15',
    'url':'https://www.summitaviationspokane.com/wp-content/uploads/2025/08/pa-28-181-archer-ii-poh.pdf',
    'document_sha256':'0a51a23b0db5d4d1bbb063484a56d7ed12a0a1935da96e5c90e88dd13e1bd43c',
    'pages':{'geometry':'1-2, PDF 9','engine':'1-3, PDF 10','atmosphere':'5-4, PDF 65',
             'cruise_example':'5-5, PDF 66 (revised 1979-03-16)','speed_figure':'5-19 Fig.5-17, PDF 82'},
    'pressure_altitude_ft':6000.,'temperature_f':55.,'gross_weight_lb':2550.,
    'wing_area_ft2':170.,'span_ft':35.,'rated_power_hp':180.,'power_fraction':.65,
    'true_airspeed_mph':127.,'fuel_us_gal_h':7.6,'fuel_lb_us_gal':6.,
    'configuration':'wheel fairings installed, economy mixture leaned to peak EGT, still air',
    'interpretation':'speed uses chart gross weight 2550 lb; fuel is the same 65% rated-power example; whole flight-plan 2400 lb not compared',
    'data_role':'V0.1.8 independent spot check; V0.2.0 reclassified as calibration datum, legacy baseline only',
}
# Diagnostic bands chosen before the first evaluation; not certification limits.
BANDS={'speed_relative':.10,'fuel_relative':.20}


def evaluate_public_cruise():
    ref=dict(REFERENCE);a=replace(SizingAssumptions(),aspect_ratio=ref['span_ft']**2/ref['wing_area_ft2'])
    mass=ref['gross_weight_lb']*.45359237;area=ref['wing_area_ft2']*.3048**2
    altitude=ref['pressure_altitude_ft']*.3048
    temperature=(ref['temperature_f']-32)*5/9+273.15
    # At pressure altitude the pressure is standard; use actual OAT in the gas law.
    rho=density(altitude)*(288.15-.0065*altitude)/temperature
    shaft_power=ref['rated_power_hp']*745.6998715822702*ref['power_fraction']
    def power(v):return flight_power(mass,area,v,altitude,0,a,air_density_kg_m3=rho)[0]
    # Start at minimum-power speed and solve the physically relevant high-speed branch.
    k=1/(math.pi*a.oswald_efficiency*a.aspect_ratio)
    cl_minpower=math.sqrt(3*a.cd0/k)
    lo=math.sqrt(2*mass*G/(rho*area*cl_minpower));hi=100.
    if not power(lo)<shaft_power<power(hi):raise ValueError('公开对照工况未包围高速平飞根')
    for _ in range(70):
        mid=(lo+hi)/2
        if power(mid)>shaft_power:hi=mid
        else:lo=mid
    speed=(lo+hi)/2
    fuel=shaft_power/1000*a.bsfc_kg_kwh/(ref['fuel_lb_us_gal']*.45359237)
    speed_error=speed/(ref['true_airspeed_mph']*.44704)-1;fuel_error=fuel/ref['fuel_us_gal_h']-1
    checks={'speed':abs(speed_error)<=BANDS['speed_relative'],'fuel':abs(fuel_error)<=BANDS['fuel_relative']}
    return {'status':'model_discrepancy' if not all(checks.values()) else 'spot_check_with_limits',
            'reference':ref,'conditions_si':{'gross_mass_kg':mass,'area_m2':area,'pressure_altitude_m':altitude,
                'temperature_k':temperature,'density_kg_m3':rho,'shaft_power_w':shaft_power},
            'predicted':{'speed_mph':speed/.44704,'fuel_us_gal_h':fuel,
                'power_at_reference_speed_w':power(ref['true_airspeed_mph']*.44704)},
            'relative_errors':{'speed':speed_error,'fuel':fuel_error},'checks':checks,'diagnostic_bands':BANDS,
            'numerical_power_residual_w':power(speed)-shaft_power,'assumptions':asdict(a),
            'coefficients_fitted':False,'physical_validation_passed':False,
            'limits':['匹配压力高度、实际温度、巡航图重量、功率与参考面积；极曲线和桨效率仍为平台默认假设。',
                '单个手册工况仅测量模型偏差，不构成整机、全包线或完整任务精度验收。',
                '同一额定功率下的经济混合比耗油可暴露常数 BSFC 的局限；保持偏差，不据此自动改默认值。',
                '主总体任务仍采用标准大气；此处显式密度仅用于同条件对照，不代表高温高原整机能力已接通。']}


def run_public_cruise(root):
    root=Path(root).resolve();work=root/'runs'/uuid4().hex;work.mkdir(parents=True)
    summary=evaluate_public_cruise();write_json(work/'input.json',REFERENCE);write_json(work/'summary.json',summary)
    text=['# Piper VB-760 同条件巡航点对照','',summary['status'],
          f"- 真空速：手册 127 mph；模型 {summary['predicted']['speed_mph']:.3f} mph，偏差 {summary['relative_errors']['speed']:.2%}",
          f"- 耗油：手册 7.6 US gal/h；模型 {summary['predicted']['fuel_us_gal_h']:.3f} US gal/h，偏差 {summary['relative_errors']['fuel']:.2%}",
          '',*summary['limits'],'',f"来源：{REFERENCE['url']}"]
    (work/'report.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    result={'run_id':work.name,'version':__version__,'mode':'public_cruise_check','status':summary['status'],'summary':summary,
            'finished_utc':datetime.now(timezone.utc).isoformat(),'input_hash':sha256(work/'input.json'),
            'source_hashes':{p.relative_to(Path(__file__).parent).as_posix():sha256(p) for p in Path(__file__).parent.rglob('*.py')},
            'artifact_hashes':{p.name:sha256(p) for p in work.iterdir() if p.is_file()},'physical_validation_passed':False}
    write_json(work/'result.json',result);return result
