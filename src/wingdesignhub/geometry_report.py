"""Preview and self-contained report from actual native surface tessellation."""
from html import escape
import json
from pathlib import Path
import numpy as np

COLORS={'MainWing':'#649fc5','HorizontalTail':'#80b69f','VerticalTail':'#80b69f',
        'Fuselage':'#d1d9e0','PropellerDisk':'#bedfe7','Spinner':'#a6b5c1'}


def mesh_figure(meshes):
    import plotly.graph_objects as go
    fig=go.Figure()
    for mesh in meshes:
        p=np.asarray(mesh['vertices_m']);t=np.asarray(mesh['triangles'])
        fig.add_trace(go.Mesh3d(x=p[:,0],y=p[:,1],z=p[:,2],i=t[:,0],j=t[:,1],k=t[:,2],
                               name=mesh['name'],color=COLORS.get(mesh['name'],'#657a89'),
                               opacity=.45 if mesh['name']=='PropellerDisk' else 1.,
                               hovertemplate=mesh['name']+'<br>x %{x:.3f} m<br>y %{y:.3f} m<br>z %{z:.3f} m<extra></extra>',
                               showlegend=mesh['surface']==0))
    fig.update_layout(height=540,margin=dict(l=0,r=0,t=25,b=0),
                      scene=dict(aspectmode='data',xaxis_title='x 向后 / m',yaxis_title='y 向右 / m',zaxis_title='z 向上 / m',
                                 camera=dict(eye=dict(x=-1.45,y=-1.8,z=.9))),
                      legend=dict(orientation='h',y=-.05),paper_bgcolor='#ffffff')
    return fig


def preview_svg(meshes):
    """Orthographic panels using actual surface triangles, with equal metre scales."""
    svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1050" height="680" viewBox="0 0 1050 680">',
         '<rect width="1050" height="680" fill="#f8fafc"/>']
    allp=np.concatenate([m['vertices_m'] for m in meshes]);panels=[(0,1,0,0,650,650,'Top view / nose left'),(0,2,650,0,400,330,'Side view / z up')]
    for a,b,ox,oy,width,height,label in panels:
        mn=allp.min(axis=0);mx=allp.max(axis=0);scale=min((width-60)/(mx[a]-mn[a]),(height-90)/(mx[b]-mn[b]))
        def project(p):
            q=np.asarray(p);x=ox+30+(q[:,a]-mn[a])*scale;y=oy+height-45-(q[:,b]-mn[b])*scale
            return np.stack((x,y),axis=1)
        for mesh in sorted(meshes,key=lambda m:m['name']=='Fuselage'):
            p=project(mesh['vertices_m']);color=COLORS.get(mesh['name'],'#657a89')
            paths=['M'+' L'.join(f'{p[i,0]:.2f},{p[i,1]:.2f}' for i in face)+'Z' for face in mesh['triangles']]
            svg.append(f'<path d="{" ".join(paths)}" fill="{color}" stroke="{color}" stroke-width="0.15"/>')
        svg.append(f'<text x="{ox+25}" y="{oy+25}" font-family="sans-serif" font-size="17">{label}</text>')
        svg.append(f'<path d="M{ox+30},{oy+height-25} h{scale:.3f}" stroke="#24384b" stroke-width="3"/>')
        svg.append(f'<text x="{ox+30}" y="{oy+height-6}" font-family="sans-serif" font-size="12">1 m</text>')
    svg.append('<text x="675" y="390" font-family="sans-serif" font-size="16">OpenVSP native geometry</text>')
    svg.append('<text x="675" y="420" font-family="sans-serif" font-size="14">Concept template / no aerodynamic solution</text></svg>')
    return ''.join(svg)


def write_geometry_report(work,contract,summary):
    work=Path(work);meshes=json.loads((work/'surface_mesh.json').read_text('utf-8'));svg=preview_svg(meshes)
    (work/'geometry_preview.svg').write_text(svg,encoding='utf-8')
    ref=contract['references']
    rows=[('原总体运行',contract['parent_run_id']),('几何运行',work.name),('状态',summary['status']),
          ('OpenVSP',summary['openvsp_version']),('外形模板',summary['template_version']),
          ('参考面积 / m²',ref['area_m2']),('参考翼展 / m',ref['span_m']),('参考 MAC / m',ref['chord_m']),
          ('力矩参考点（几何坐标，m）',ref['moment_reference_geometry_m'])]
    md=f'# {contract["name"]} — 全机参数化几何\n\n'+ '\n'.join(f'- {k}：{v}' for k,v in rows)
    md+='\n\n## 验收与适用边界\n\n'+f'{sum(c["passed"] for c in summary["checks"])} / {len(summary["checks"])} 项几何检查通过。\n\n'
    md+='\n'.join('- '+s for s in contract['limits'])+'\n\n## 模板输入与来源\n\n```json\n'+json.dumps(contract,ensure_ascii=False,indent=2)+'\n```\n'
    (work/'report.md').write_text(md,encoding='utf-8')
    html='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>全机几何报告</title><style>body{font:16px/1.7 sans-serif;max-width:1100px;margin:30px auto;padding:20px;color:#203448}table{border-collapse:collapse}td{padding:6px 18px;border:1px solid #ccd4dc}svg{width:100%;height:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px}@media print{body{margin:0;padding:0}}</style>'
    html+=f'<h1>{escape(contract["name"])}：全机几何</h1><table>'+''.join(f'<tr><td>{escape(k)}</td><td>{escape(str(v))}</td></tr>' for k,v in rows)+'</table>'+svg
    html+='<h2>验收与适用边界</h2><p>'+str(sum(c['passed'] for c in summary['checks']))+'/'+str(len(summary['checks']))+' 项几何检查通过；实际气动与配平尚未运行。</p><ul>'+''.join('<li>'+escape(s)+'</li>' for s in contract['limits'])+'</ul>'
    html+='<h2>完整输入与几何检查</h2><pre>'+escape(json.dumps({'contract':contract,'summary':summary},ensure_ascii=False,indent=2))+'</pre></html>'
    (work/'report.html').write_text(html,encoding='utf-8')
