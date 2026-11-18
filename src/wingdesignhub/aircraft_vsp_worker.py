"""Isolated OpenVSP 3.56 builder; no aerodynamic or propulsion solver is run."""
from pathlib import Path
import json
import sys
import numpy as np
import openvsp as vsp
from .service import write_json
from .adapters import sha256


def errors():
    manager = vsp.ErrorMgrSingleton.getInstance(); messages = []
    while manager.GetNumTotalErrors():messages.append(manager.PopLastError().m_ErrorString)
    if messages:raise RuntimeError('; '.join(messages))


def setp(obj, name, group, value):
    pid = vsp.FindParm(obj,name,group)
    if not pid:raise ValueError(f'OpenVSP 参数不存在：{group}/{name}')
    actual = vsp.SetParmVal(pid,value)
    if not np.isclose(actual,value,rtol=1e-10,atol=1e-10):
        raise ValueError(f'OpenVSP 参数被限幅：{group}/{name}={actual}, 请求 {value}')


def xyz(vec):return [vec.x(),vec.y(),vec.z()]


def locate(gid, position, rotation=(0.,0.,0.)):
    for axis, value, angle in zip('XYZ',position,rotation):
        setp(gid,axis+'_Rel_Location','XForm',value)
        setp(gid,axis+'_Rel_Rotation','XForm',angle)


def build(contract):
    if vsp.GetVSPVersion() != 'OpenVSP 3.56.0':raise ValueError('本模块锁定验证版本 OpenVSP 3.56.0')
    vsp.ClearVSPModel(); ids = {}; factor = contract['options']['tessellation']

    def add(kind,name):
        gid = vsp.AddGeom(kind); vsp.SetGeomName(gid,name); ids[name] = gid
        setp(gid,'Tess_U','Shape',16*factor);setp(gid,'Tess_W','Shape',32*factor+1)
        return gid

    for s in contract['lifting_surfaces']:
        gid = add('WING',s['name'])
        setp(gid,'Sym_Planar_Flag','Sym',0 if s['vertical'] else vsp.SYM_XZ)
        vsp.SetDriverGroup(gid,1,vsp.SPAN_WSECT_DRIVER,vsp.ROOTC_WSECT_DRIVER,vsp.TIPC_WSECT_DRIVER)
        xs = vsp.GetXSecSurf(gid,0)
        for key,value in {'Span':s['span_m']/(2 if s['symmetric'] else 1), 'Root_Chord':s['root_chord_m'],
                          'Tip_Chord':s['tip_chord_m'],'Sweep':0.,'Sweep_Location':.25,'Twist':0.,'Dihedral':0.,
                          'SectTess_U':12*factor}.items():
            setp(vsp.GetXSec(xs,1),key,'XSec',value)
        for i in (0,1):
            x = vsp.GetXSec(xs,i)
            for key,value in {'Camber':s['camber'],'CamberLoc':s['camber_location'],
                              'ThickChord':s['thickness_ratio'],'SharpTEFlag':1}.items():
                pid=vsp.GetXSecParm(x,key)
                if not pid or not np.isclose(vsp.SetParmVal(pid,value),value,rtol=1e-10,atol=1e-10):
                    raise ValueError('翼型参数无效：'+key)
        from .incidence import physical_origin
        locate(gid,physical_origin(s),(90. if s['vertical'] else 0.,s['incidence_deg'],0.))
        vsp.Update()
    f = contract['fuselage']; gid = add('FUSELAGE','Fuselage');setp(gid,'Length','Design',f['length_m'])
    xs = vsp.GetXSecSurf(gid,0)
    if vsp.GetNumXSec(xs)!=5:raise ValueError('机身初始截面数与模板不符')
    for i,(x,w,h) in enumerate(f['sections_fraction']):
        vsp.ChangeXSecShape(xs,i,vsp.XS_POINT if i in (0,4) else vsp.XS_ELLIPSE)
        sec = vsp.GetXSec(xs,i);setp(sec,'XLocPercent','XSec',x)
        if i not in (0,4):vsp.SetXSecWidthHeight(sec,w*f['width_m'],h*f['height_m'])
    gid = add('PROP','PropellerDisk');setp(gid,'PropMode','Design',vsp.PROP_DISK)
    setp(gid,'Diameter','Design',contract['propeller']['diameter_m']);locate(gid,contract['propeller']['center_m'])

    def pod(name,length,fineness,position,rotation=(0,0,0)):
        gid = add('POD',name);setp(gid,'Length','Design',length);setp(gid,'FineRatio','Design',fineness)
        locate(gid,position,rotation)
    pod('Spinner',.45,1.5,[-.45,0,0])
    gear = contract['gear']
    for label,x,y in [('Nose',gear['nose_x_m'],0.),('Left',gear['main_x_m'],-gear['half_track_m']),
                      ('Right',gear['main_x_m'],gear['half_track_m'])]:
        pod(label+'Fairing',gear['fairing_length_m'],gear['fairing_fineness'],
            [x-gear['fairing_length_m']/2,y,gear['wheel_center_z_m']])
        zstart = -.24*f['height_m'] if label!='Nose' else -.40*f['height_m']
        length = zstart-gear['wheel_center_z_m']
        pod(label+'Strut',length,12.,[x,y,zstart],(0,90,0))
    roles = contract['analysis_contract']['component_roles']; sets = contract['analysis_contract']['set_definitions']
    for key,idx in sets.items():
        vsp.SetSetName(idx,key)
        names = roles['lifting_surfaces']+roles['body'] if key=='baseline_airframe' else roles[key]
        for name,gid in ids.items():vsp.SetSetFlag(gid,idx,name in names)
    vsp.Update()
    aero = vsp.FindContainer('VSPAEROSettings',0);ref = contract['references']
    vsp.SetVSPAERORefWingID(ids['MainWing'])
    for name,value in {'RefFlag':vsp.MANUAL_REF,'Sref':ref['area_m2'],'bref':ref['span_m'],'cref':ref['chord_m'],
                       'Xcg':ref['moment_reference_geometry_m'][0],'Ycg':0.,'Zcg':0.,
                       'GeomSet':sets['body'],'ThinGeomSet':sets['lifting_surfaces']}.items():
        setp(aero,name,'VSPAERO',value)
    vsp.Update();errors();return ids


def measurements(ids,contract):
    result = {'lifting_surfaces':{},'sets':{}}
    for s in contract['lifting_surfaces']:
        gid = ids[s['name']]; sec = vsp.GetXSec(vsp.GetXSecSurf(gid,0),1)
        result['lifting_surfaces'][s['name']] = {
            'area_m2':vsp.GetParmVal(gid,'TotalArea','WingGeom'),
            'span_m':vsp.GetParmVal(gid,'TotalSpan','WingGeom'),
            'mac_m':vsp.GetParmVal(gid,'MAC','WingGeom'),
            'root_chord_m':vsp.GetParmVal(vsp.FindParm(sec,'Root_Chord','XSec')),
            'tip_chord_m':vsp.GetParmVal(vsp.FindParm(sec,'Tip_Chord','XSec')),
            'origin_m':[vsp.GetParmVal(gid,a+'_Location','XForm') for a in 'XYZ'],
            'incidence_deg':vsp.GetParmVal(gid,'Y_Rel_Rotation','XForm'),
            'bbox_min_m':xyz(vsp.GetGeomBBoxMin(gid,0,False)),
            'bbox_max_m':xyz(vsp.GetGeomBBoxMax(gid,0,False)),
            'surface_count':vsp.GetTotalNumSurfs(gid)}
        xs=vsp.GetXSecSurf(gid,0)
        result['lifting_surfaces'][s['name']]['airfoils']=[
            {k:vsp.GetParmVal(vsp.GetXSecParm(vsp.GetXSec(xs,i),k)) for k in ('Camber','CamberLoc','ThickChord','SharpTEFlag')}
            for i in (0,1)]
    gid=ids['Fuselage'];xs=vsp.GetXSecSurf(gid,0)
    result['fuselage']={'length_m':vsp.GetParmVal(gid,'Length','Design'),
                        'sections':[[vsp.GetParmVal(vsp.GetXSecParm(vsp.GetXSec(xs,i),'XLocPercent')),
                                     vsp.GetXSecWidth(vsp.GetXSec(xs,i)),vsp.GetXSecHeight(vsp.GetXSec(xs,i))] for i in range(5)]}
    aero=vsp.FindContainer('VSPAEROSettings',0)
    result['vspaero']={k:vsp.GetParmVal(vsp.FindParm(aero,k,'VSPAERO')) for k in
                       ('Sref','bref','cref','Xcg','Ycg','Zcg','RefFlag','GeomSet','ThinGeomSet')}
    result['propeller_diameter_m']=vsp.GetParmVal(ids['PropellerDisk'],'Diameter','Design')
    for name,idx in contract['analysis_contract']['set_definitions'].items():
        result['sets'][name]=sorted(n for n,g in ids.items() if vsp.GetSetFlag(g,idx))
    errors();return result


def check_measurements(actual,contract):
    checks=[]
    def close(name,a,b):
        ok=bool(np.allclose(a,b,rtol=1e-6,atol=1e-8))
        checks.append({'name':name,'passed':ok,'max_abs_difference':float(np.max(np.abs(np.asarray(a)-np.asarray(b))))})
    for s in contract['lifting_surfaces']:
        a=actual['lifting_surfaces'][s['name']]
        close(s['name']+'/incidence',a['incidence_deg'],s['incidence_deg'])
        for k in ('area_m2','span_m','mac_m','root_chord_m','tip_chord_m'):close(s['name']+'/'+k,a[k],s[k])
        from .incidence import physical_origin
        close(s['name']+'/origin',a['origin_m'],physical_origin(s))
        close(s['name']+'/surfaces',a['surface_count'],2 if s['symmetric'] else 1)
        for i,foil in enumerate(a['airfoils']):
            close(s['name']+f'/airfoil_{i}',list(foil.values()),[s['camber'],s['camber_location'],s['thickness_ratio'],1.])
    f=contract['fuselage'];close('fuselage/length',actual['fuselage']['length_m'],f['length_m'])
    close('fuselage/sections',actual['fuselage']['sections'],[[x,w*f['width_m'],h*f['height_m']] for x,w,h in f['sections_fraction']])
    ref=contract['references'];sets=contract['analysis_contract']['set_definitions']
    for k,v in {'Sref':ref['area_m2'],'bref':ref['span_m'],'cref':ref['chord_m'],
                'Xcg':ref['moment_reference_geometry_m'][0],'Ycg':0.,'Zcg':0.,'RefFlag':0.,
                'GeomSet':sets['body'],'ThinGeomSet':sets['lifting_surfaces']}.items():close('vspaero/'+k,actual['vspaero'][k],v)
    close('propeller/diameter',actual['propeller_diameter_m'],contract['propeller']['diameter_m'])
    roles=contract['analysis_contract']['component_roles']
    for key in sets:
        expected=roles['body']+roles['lifting_surfaces'] if key=='baseline_airframe' else roles[key]
        checks.append({'name':'set/'+key,'passed':actual['sets'][key]==sorted(expected)})
    return checks


def degen_export(work,contract):
    vsp.SetComputationFileName(vsp.DEGEN_GEOM_CSV_TYPE,str(work/'airframe_DegenGeom.csv'))
    vsp.ComputeDegenGeom(contract['analysis_contract']['set_definitions']['baseline_airframe'],vsp.DEGEN_GEOM_CSV_TYPE)
    rid=vsp.FindLatestResultsID('DegenGeom');out=[]
    for did in vsp.GetStringResults(rid,'Degen_DegenGeoms'):
        obj={'name':vsp.GetStringResults(did,'name')[0],'type':vsp.GetStringResults(did,'type')[0],
             'sym_copy':vsp.GetIntResults(did,'sym_copy_index')[0],'sticks':[]}
        for sid in vsp.GetStringResults(did,'sticks'):
            r=vsp.parse_results_object(sid)
            obj['sticks'].append({'le_m':np.asarray(r.le).tolist(),'te_m':np.asarray(r.te).tolist(),
                                  'chord_m':list(r.chord)})
        out.append(obj)
    errors();write_json(work/'degen_sections.json',out);return out


def check_degen(objects,contract):
    checks=[];metrics={}
    for s in contract['lifting_surfaces']:
        area=0.;integral=0.;max_error=0.;copies=[o for o in objects if o['name']==s['name']]
        for obj in copies:
            stick=obj['sticks'][0];le=np.array(stick['le_m']);te=np.array(stick['te_m'])
            from .incidence import rotate_points
            le=rotate_points(le,s['quarter_x_m'],s['z_m'],-s['incidence_deg'])
            te=rotate_points(te,s['quarter_x_m'],s['z_m'],-s['incidence_deg'])
            chord=te[:,0]-le[:,0];coordinate=le[:,2]-s['z_m'] if s['vertical'] else np.abs(le[:,1])
            ds=np.abs(np.diff(coordinate));c0=chord[:-1];c1=chord[1:]
            # Exact integral of piecewise-linear chord and squared chord.
            area+=float(np.sum(ds*(c0+c1)/2));integral+=float(np.sum(ds*(c0*c0+c0*c1+c1*c1)/3))
            expected=s['root_chord_m']+(s['tip_chord_m']-s['root_chord_m'])*coordinate/(s['span_m']/(2 if s['symmetric'] else 1))
            # Cap points with zero span intervals do not define aerodynamic sections.
            keep=np.r_[ds>1e-8,False] | np.r_[False,ds>1e-8]
            max_error=max(max_error,float(np.max(np.abs(chord[keep]-expected[keep]))),
                          float(np.max(np.abs((le[:,0]+.25*chord)[keep]-s['quarter_x_m']))))
        metrics[s['name']]={'integrated_area_m2':area,'integrated_mac_m':integral/area if area else 0.,
                             'maximum_section_error_m':max_error,'copies':len(copies)}
        checks.append({'name':s['name']+'/degen_integrals','passed':bool(area>0 and
            np.isclose(area,s['area_m2'],rtol=1e-6) and np.isclose(integral/area,s['mac_m'],rtol=1e-6)
            and max_error<1e-6 and len(copies)==(2 if s['symmetric'] else 1))})
    return checks,metrics


def surface_mesh(ids):
    meshes=[]
    for name,gid in ids.items():
        for surf in range(vsp.GetTotalNumSurfs(gid)):
            us,ws=vsp.GetUWTess01(gid,surf)
            u=np.repeat(np.asarray(us),len(ws));w=np.tile(np.asarray(ws),len(us))
            pts=np.array([xyz(p) for p in vsp.CompVecPnt01(gid,surf,u.tolist(),w.tolist())]);faces=[]
            for i in range(len(us)-1):
                for j in range(len(ws)-1):
                    a=i*len(ws)+j;b=a+len(ws)
                    faces.extend([[a,b,b+1],[a,b+1,a+1]])
            meshes.append({'name':name,'surface':surf,'vertices_m':np.round(pts,9).tolist(),'triangles':faces})
    errors();return meshes


def main(work):
    work=Path(work).resolve();contract=json.loads((work/'geometry_contract.json').read_text('utf-8'))
    ids=build(contract);before=measurements(ids,contract)
    vsp.WriteVSPFile(str(work/'aircraft.vsp3'),vsp.SET_ALL);errors()
    vsp.ClearVSPModel();vsp.ReadVSPFile(str(work/'aircraft.vsp3'));vsp.Update();errors()
    ids={vsp.GetGeomName(g):g for g in vsp.FindGeoms()};after=measurements(ids,contract)
    checks=check_measurements(before,contract)+check_measurements(after,contract)
    # Saved model must preserve the complete numeric readback and analysis membership.
    checks.append({'name':'write_read_round_trip','passed':before==after})
    degen=degen_export(work,contract);dc,metrics=check_degen(degen,contract);checks+=dc
    meshes=surface_mesh(ids);write_json(work/'surface_mesh.json',meshes)
    for name,expected in [('Fuselage',[contract['fuselage'][k] for k in ('length_m','width_m','height_m')]),
                          ('PropellerDisk',[0.,contract['propeller']['diameter_m'],contract['propeller']['diameter_m']])]:
        points=np.concatenate([m['vertices_m'] for m in meshes if m['name']==name]);extent=np.ptp(points,axis=0)
        checks.append({'name':name+'/mesh_extent','passed':bool(np.allclose(extent,expected,rtol=1e-6,atol=1e-8)),
                       'max_abs_difference':float(np.max(np.abs(extent-expected)))})
    interface={'schema_version':1,'coordinates':contract['coordinates'],'references':contract['references'],
               'surfaces':contract['lifting_surfaces'],'analysis':contract['analysis_contract'],
               'source_run_id':work.name,'parent_run_id':contract['parent_run_id'],
               'vspaero_settings':after['vspaero'],'geometry_file_sha256':sha256(work/'aircraft.vsp3'),
               'degen_file_sha256':sha256(work/'airframe_DegenGeom.csv'),'limits':contract['limits']}
    write_json(work/'aerodynamic_geometry.json',interface)
    from .geometry_report import write_geometry_report
    summary={'status':'geometry_checked_with_limits' if all(c['passed'] for c in checks) else 'failed',
             'passed':all(c['passed'] for c in checks),'openvsp_version':vsp.GetVSPVersion(),
             'parent_run_id':contract['parent_run_id'],'parent_status':contract['parent_status'],
             'template_version':contract['options']['template_version'],'component_count':len(ids),
             'measurements':after,'degen_metrics':metrics,'checks':checks,
             'references':contract['references'],'physical_validation_passed':False,
             'native_binary_hashes':{p.name:sha256(p) for p in Path(vsp.__file__).parent.iterdir() if p.suffix.lower() in ('.dll','.pyd')},
             'aerodynamics_run':False,'trim_checked':False,'limits':contract['limits']}
    write_json(work/'summary.json',summary);write_geometry_report(work,contract,summary)
    if not summary['passed']:raise ValueError('全机几何验收未通过，请查看 summary.json')
    print(summary['status'],len(ids),flush=True)


if __name__=='__main__':main(sys.argv[1])
