"""Isolated model registry and numerical execution."""
from pathlib import Path
import json,sys
import hashlib
from importlib.metadata import version
from .requirements import DesignProject
from .fastga_mass import FastGAMassModel
from .sizing import solve_design
from .service import write_json


def geometry_svg(g):
    scale=420/max(g['wing_span_m'],g['fuselage_length_m']);origin=40;mid=270
    def polygon(points,color):
        pairs=' '.join(f'{origin+x*scale:.3f},{mid+y*scale:.3f}' for x,y in points)
        return f'<polygon points="{pairs}" fill="{color}" stroke="#273e50" stroke-width="1"/>'
    lf=g['fuselage_length_m'];w=g['fuselage_width_m']/2
    svg='<svg xmlns="http://www.w3.org/2000/svg" width="600" height="560" viewBox="0 0 600 560"><rect width="600" height="560" fill="white"/>'
    svg+=polygon([(0,0),(.15*lf,-w),(.6*lf,-w),(lf,0),(.6*lf,w),(.15*lf,w)],'#dce3e9')
    root=g['root_chord_m'];tip=g['tip_chord_m'];x=g['wing_quarter_x_m'];b=g['wing_span_m']/2
    svg+=polygon([(x-.25*root,0),(x-.25*tip,-b),(x+.75*tip,-b),(x+.75*root,0),(x+.75*tip,b),(x-.25*tip,b)],'#90bdd8')
    ht=(4*g['horizontal_tail_area_m2'])**.5;hc=2*g['horizontal_tail_area_m2']/(ht*1.6);xt=x+g['tail_arm_m']
    tip=.6*hc
    svg+=polygon([(xt-.25*hc,0),(xt-.25*tip,-ht/2),(xt+.75*tip,-ht/2),(xt+.75*hc,0),
                  (xt+.75*tip,ht/2),(xt-.25*tip,ht/2)],'#a6c6ae')
    svg+=f'<text x="30" y="25" font-size="16">Concept planform: span {g["wing_span_m"]:.2f} m; area {g["wing_area_m2"]:.2f} m2</text>'
    return svg+'<text x="30" y="535" font-size="13">Top view, nose left; parameter layout, not a CAD or trim model.</text></svg>'


def main(work):
    work=Path(work);p=DesignProject.from_dict(json.loads((work/'input.json').read_text(encoding='utf-8')))
    with FastGAMassModel() as model:
        r=solve_design(p,model)
        write_json(work/'fastga_mass_inputs.json',model.last_inputs)
        write_json(work/'fastga_mass_interface.json',model.audit)
        import fastga
        from .adapters import sha256
        engine=Path(fastga.__file__).parent/'models/propulsion/fuel_propulsion/basicIC_engine/basicIC_engine.py'
        evidence={'mass_sources':model.audit.get('upstream_mass_source_hashes',{}),'engine_source':sha256(engine),
                  'constructor_data':model.audit.get('propeller_constructor_source_sha256')}
        r['model_signature']=hashlib.sha256(json.dumps(evidence,sort_keys=True).encode()).hexdigest()
        write_json(work/'model_evidence.json',evidence)
    r['versions']={n:version(n) for n in ('fast-oad-cs23','fast-oad-core','openmdao','numpy','wingdesignhub')}
    write_json(work/'summary.json',r)
    lines=[f'# {p.name} — 初步总体设计','',f'状态：{r["status"]}',
           '概念模型结果；起降和纵向一级检查按四态记录，实机性能及详细结构强度尚未验收。','']
    if 'geometry' in r:
        lines += [f'- 设计起飞重量：{r["design_mtow_kg"]:.3f} kg',f'- 计算装载质量：{r["required_loaded_mass_kg"]:.3f} kg',
                  f'- 质量预算余量：{r["mass_budget_margin_kg"]:.3f} kg',f'- 空重（含不可用燃油）：{r["weights"]["owe_kg"]:.3f} kg',
                  f'- 翼面积：{r["geometry"]["wing_area_m2"]:.3f} m²；翼展：{r["geometry"]["wing_span_m"]:.3f} m',
                  f'- 安装功率：{r["power"]["installed_power_w"]/1000:.3f} kW',
                  f'- 起飞携带可用燃油：{r["mission"]["takeoff_fuel_kg"]:.3f} kg；含出场滑行的总可用燃油：{r["mission"]["block_fuel_kg"]:.3f} kg',
                  f'- 额外储备油：{r["mission"]["reserve_fuel_kg"]:.3f} kg（已包含）',
                  f'- 主任务航程：{r["mission"]["route_distance_m"]/1000:.3f} km；空中时长：{r["mission"]["main_duration_s"]/3600:.3f} h','']
        from .constraint_states import markdown
        lines += [markdown(r,p)]
        (work/'geometry.svg').write_text(geometry_svg(r['geometry']),encoding='utf-8')
        write_json(work/'aircraft_parameters.json',{'geometry':r['geometry'],'weights':r['weights'],'power':r['power'],'cg':r['cg']})
    lines += ['']+r.get('diagnostics',[])+r.get('limits',[])
    lines += ['', '需求与假设快照（SI）：', '```json',json.dumps(p.to_dict(),ensure_ascii=False,indent=2),'```',
              '', '软件版本：'+json.dumps(r['versions'],ensure_ascii=False),
              '部件质量输入、上游源文件哈希、命令与日志随本次运行保存。']
    (work/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(r['status'],r.get('design_mtow_kg'),flush=True)


if __name__=='__main__':main(sys.argv[1])
