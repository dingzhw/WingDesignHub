"""Native OpenVSP wetted areas, exposed planform quadrature and exact foil export."""
from pathlib import Path
import json
import sys
import numpy as np
import openvsp as vsp
from .adapters import sha256
from .aircraft_vsp_worker import errors, setp, surface_mesh
from .service import write_json


def outside_other(points, ids, own):
    hidden=np.zeros(len(points),dtype=bool)
    vectors=[vsp.vec3d(*p) for p in points]
    for name,gid in ids.items():
        if name in (own,'PropellerDisk'):continue
        for surf in range(vsp.GetTotalNumSurfs(gid)):
            hidden |= np.asarray(vsp.VecInsideSurf(gid,surf,vectors),dtype=bool)
    return ~hidden


def exposed_strips(strips, surfaces, ids, samples):
    result=[];by_name={s['name']:s for s in surfaces}
    for name in dict.fromkeys(s['surface'] for s in strips):
        own=name.replace(' (YDUP)','');surface=by_name[own];vertical=surface['vertical']
        rows=sorted((s for s in strips if s['surface']==name),key=lambda s:s['z_le_m'] if vertical else abs(s['y_le_m']))
        full=surface['span_m']/(2 if surface['symmetric'] else 1)
        if not np.isclose(sum(s['width_m'] for s in rows),full,rtol=1e-6):raise ValueError('条带展向宽度与几何不一致：'+name)
        start=0.
        for row in rows:
            ds=row['width_m'];points=[];weights=[]
            for eta in (np.arange(samples)+.5)/samples:
                span=start+eta*ds;fraction=span/full
                chord=surface['root_chord_m']+(surface['tip_chord_m']-surface['root_chord_m'])*fraction
                xle=surface['quarter_x_m']-.25*chord
                for xc in (np.arange(samples)+.5)/samples:
                    # Geometry is zero incidence/sweep/dihedral; use its camber line.
                    m,p=surface['camber'],surface['camber_location']
                    camber=(m/p**2*(2*p*xc-xc*xc) if xc<p else m/(1-p)**2*(1-2*p+2*p*xc-xc*xc)) if m else 0.
                    if vertical:point=[xle+xc*chord,-camber*chord,surface['z_m']+span]
                    else:point=[xle+xc*chord,span*(-1 if '(YDUP)' in name else 1),surface['z_m']+camber*chord]
                    points.append(point);weights.append(chord)
            exposed=outside_other(points,ids,own);fraction=float(np.dot(exposed,weights)/sum(weights))
            result.append({'surface':name,'strip_id':row['strip_id'],'gross_area_m2':row['area_m2'],
                           'exposed_fraction':fraction,'exposed_area_m2':row['area_m2']*fraction})
            start+=ds
    errors();return result


def main(work):
    work=Path(work).resolve();c=json.loads((work/'drag_contract.json').read_text('utf-8'))
    gc=json.loads((work/'geometry_contract.json').read_text('utf-8'));o=c['options']
    if vsp.GetVSPVersion()!='OpenVSP 3.56.0':raise ValueError('阻力几何接口锁定 OpenVSP 3.56.0')
    vsp.ClearVSPModel();vsp.ReadVSPFile(str(work/'aircraft.vsp3'));vsp.Update();errors()
    ids={vsp.GetGeomName(g):g for g in vsp.FindGeoms()}
    if len(ids)!=12:raise ValueError('部件数量与常规单发模板不一致')
    for name,gid in ids.items():
        setp(gid,'Tess_U','Shape',16*o['geometry_tessellation']);setp(gid,'Tess_W','Shape',32*o['geometry_tessellation']+1)
        if name in ('MainWing','HorizontalTail','VerticalTail'):
            setp(vsp.GetXSec(vsp.GetXSecSurf(gid,0),1),'SectTess_U','XSec',12*o['geometry_tessellation'])
        vsp.SetSetFlag(gid,7,name!='PropellerDisk')
    vsp.Update();errors()
    mesh=vsp.ComputeCompGeom(7,False,0);rid=vsp.FindLatestResultsID('Comp_Geom');raw={}
    for name in vsp.GetAllDataNames(rid):
        kind=vsp.GetResultsType(rid,name)
        if kind==vsp.DOUBLE_DATA:raw[name]=list(vsp.GetDoubleResults(rid,name))
        elif kind==vsp.INT_DATA:raw[name]=list(vsp.GetIntResults(rid,name))
        elif kind==vsp.STRING_DATA:raw[name]=list(vsp.GetStringResults(rid,name))
    errors();write_json(work/'compgeom.json',raw)
    # OpenVSP joins the two root-open symmetric halves into each closed wing.
    if (raw.get('Num_Open_Meshes_Removed',[0])[0] or
            set(raw.get('Meshes_Merged_Names',[]))!={'MainWing','HorizontalTail'} or
            raw.get('Num_Open_Meshes_Merged')!=[2]):
        raise ValueError('CompGeom 开放网格处理与常规对称翼模板不符')
    areas=dict(zip(raw['Comp_Name'],raw['Wet_Area']))
    if set(areas)!=set(ids)-{'PropellerDisk'} or not np.isfinite(list(areas.values())).all() or min(areas.values())<=0:
        raise ValueError('CompGeom 部件湿面积缺失或无效')
    vsp.DeleteGeom(mesh);errors()
    foils={};(work/'airfoils').mkdir()
    for name in ('MainWing','HorizontalTail','VerticalTail'):
        # CAD display tessellation is too coarse for viscous nose curvature.
        # Sample the unchanged native section densely, independently of body mesh.
        setp(ids[name],'Tess_W','Shape',401);vsp.Update()
        path=work/'airfoils'/f'{name}.dat';vsp.WriteSeligAirfoil(str(path),ids[name],.5);errors()
        # The native header contains a local path; only replace this title, not coordinates.
        lines=path.read_text('utf-8').splitlines();lines[0]=name+' OpenVSP 3.56.0 unit chord'
        path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
        pts=np.loadtxt(path,skiprows=1)
        if not np.isfinite(pts).all() or abs(np.ptp(pts[:,0])-1)>.001:raise ValueError('翼型坐标未归一化')
        foils[name]={'file':path.relative_to(work).as_posix(),'sha256':sha256(path),'points':len(pts),'export_u':.5,'native_tess_w':401}
    strips=json.loads((work/'trim_strip_loads.json').read_text('utf-8'))['strips']
    exposed=exposed_strips(strips,gc['lifting_surfaces'],ids,o['area_samples'])
    projected={}
    for mesh in surface_mesh({name:gid for name,gid in ids.items() if name.endswith('Strut')}):
        triangles=np.asarray(mesh['vertices_m'])[np.asarray(mesh['triangles'])]
        centers=triangles.mean(axis=1);outside=outside_other(centers,ids,mesh['name'])
        cross=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
        # Each convex POD has a front and a back: half of summed absolute projection.
        projected[mesh['name']]=float(np.sum(np.abs(cross[:,0])*outside)/4)
    result={'openvsp_version':vsp.GetVSPVersion(),'geometry_sha256':sha256(work/'aircraft.vsp3'),
            'native_binary_hashes':{p.name:sha256(p) for p in Path(vsp.__file__).parent.iterdir() if p.suffix.lower() in ('.pyd','.dll')},
            'wetted_area_m2':areas,'airfoils':foils,'strips':exposed,'strut_projected_area_m2':projected,
            'method':'native CompGeom wet areas; midpoint camber-planform quadrature inside other solids; convex strut frontal projection',
            'area_samples_per_axis':o['area_samples'],'geometry_tessellation':o['geometry_tessellation']}
    write_json(work/'drag_geometry.json',result);print('drag geometry checked',flush=True)


if __name__=='__main__':main(sys.argv[1])
