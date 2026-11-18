"""Unfitted clean NACA0012 check against Ladson TM4074 Table IX (not CFD)."""
from pathlib import Path
from dataclasses import replace
import json
from wingdesignhub.xfoil_polars import PolarSpec,run_polar
from wingdesignhub.adapters import tool_paths,sha256
from wingdesignhub.service import write_json
from wingdesignhub.jobs import code_identity

root=Path(__file__).resolve().parents[1];w=root/'local/v033/formal3'
assert json.loads((w/'freeze.json').read_text('utf8'))==code_identity()
# Registered before solving. The original report says 5.95e6; TMR rounds to 6e6.
reference={'id':'ladson_tm4074_table_ix_clean_0012','role':'independent_unfitted_airfoil_reference',
    'url':'https://ntrs.nasa.gov/api/citations/19880019495/downloads/19880019495.pdf',
    'document_sha256':'8e466706cbdf54b3c778ea2b089c4f52d87686bf7f6b1bd10d224b42c2d06902',
    'pages':'p.3 tests/procedures, p.19 Table IX (PDF 5,21)','reynolds':5950000.,'mach':.15,
    'transition_xc_both_sides':.05,'trip':'No.80 grit, approximately .01c wide strips',
    'rows':[{'alpha_deg':-.05,'cl':-.0126,'cd':.00809},{'alpha_deg':2.05,'cl':.2125,'cd':.00816},
            {'alpha_deg':4.04,'cl':.4316,'cd':.00823}],
    'acceptance':{'cd_relative':.15,'alpha_absolute_deg':.4,'panel_cd_relative':.02},
    'new_fit_parameters':[],'limits':['测试修正约占测量系数的2%；不是完整不确定度预算。',
        '匹配标称翼型、Re/Mach、CL和转捩位置；XFOIL不模拟砂粒附加阻力，实际模型制造/尾缘细节未一一重建。',
        '采用本机几何导出的未偏舵NACA0012；不使用TMR为CFD专门缩短/封口的11.894%厚度截面。',
        '不覆盖NACA2412、偏舵/缝隙、当前飞机完整Re/Mach域或整机独立精度。']}
work=w/'airfoil-check';work.mkdir(exist_ok=False)
foil=w/'legacy/point_000/airfoils/HorizontalTail.dat'
reference['foil_sha256']=sha256(foil);write_json(work/'registered.json',reference)
spec=PolarSpec(reference['reynolds'],reference['mach'],tuple(r['cl'] for r in reference['rows']),
    trip_top=.05,trip_bottom=.05,panels=160)
exe=tool_paths(root)['xfoil'];results={}
for name,condition in [('tripped160',spec),('tripped320',replace(spec,panels=320)),
                       ('natural160',replace(spec,trip_top=1.,trip_bottom=1.))]:
    results[name]=run_polar(foil,condition,exe,work/name)
write_json(work/'polars.json',results)
print({k:list(v) for k,v in results.items()})
rows=[]
for observed,a,b,natural in zip(reference['rows'],results['tripped160']['rows'],results['tripped320']['rows'],results['natural160']['rows']):
    error=a['cd']/observed['cd']-1;alpha=a['alpha_deg']-observed['alpha_deg'];panel=a['cd']/b['cd']-1
    rows.append({'observed':observed,'predicted':a,'cd_relative_error':error,'alpha_error_deg':alpha,
        'panel_cd_relative_change':panel,'natural_cd':natural['cd'],
        'inside_diagnostic_bands':abs(error)<=.15 and abs(alpha)<=.4,'panel_check':abs(panel)<=.02})
out={'reference':reference,'polars':results,'comparison':rows,
    'all_diagnostic_bands_met':all(r['inside_diagnostic_bands'] for r in rows),
    'panel_check_passed':all(r['panel_check'] for r in rows),'whole_aircraft_validation_passed':False,
    'physical_validation_scope':'clean 0012 three-point diagnostic only'}
write_json(w/'airfoil.json',out)
assert json.loads((w/'freeze.json').read_text('utf8'))==code_identity()
print(rows)
