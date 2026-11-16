"""Strict AVL 3.40 MRF reader and isolated execution. No low-precision FS parsing."""
import math
from pathlib import Path
import re
import numpy as np
from .adapters import execute, sha256, NUMBER
from .aircraft_aero import avl_input, commands, trim_interface
from .aircraft_geometry import body_vectors, body_points
from .service import write_json


def numbers(line):
    part=line.split('|')[0].strip()
    tokens=re.findall(NUMBER,part)
    remainder=re.sub(NUMBER,'',part).strip()
    if remainder:raise ValueError('AVL 数值行含无法识别/非有限数据：'+part[:80])
    values=[float(t.replace('D','E')) for t in tokens]
    if not values or not all(math.isfinite(v) for v in values):raise ValueError('AVL 数值行为空或非有限')
    return values


def labelled(text, label, count=None):
    lines=[line for line in text.splitlines() if '|' in line and line.split('|',1)[1].strip().split(';')[0].strip()==label]
    if len(lines)!=1:raise ValueError('AVL 缺少或重复字段：'+label)
    v=([float(lines[0][i:i+4]) for i in (0,4,8)] if label=='Strip #, # Chordwise, First Vortex'
       else numbers(lines[0]))
    if count is not None and len(v)!=count:raise ValueError('AVL 字段数量错误：'+label)
    return v


def header(text, kind):
    if text.splitlines()[:2]!=[kind,'VERSION 1.0'] or 'Standard axis orientation,  X fwd, Z down' not in text:
        raise ValueError('AVL 输出版本或坐标方向不支持')
    if re.search(r'\b(?:NaN|Infinity)\b|\*{3}',text,re.I):raise ValueError('AVL 输出包含无效数值')


def parse_total(text):
    header(text,'TOT');out={}
    for keys,label in [(['Sref','Cref','Bref'],'Sref, Cref, Bref'),(['Xref','Yref','Zref'],'Xref, Yref, Zref'),
        (['Alpha','pb/2V',"p'b/2V"],"Alpha, pb/2V, p'b/2V"),(['Beta','qc/2V'],'Beta, qc/2V'),
        (['Mach','rb/2V',"r'b/2V"],"Mach, rb/2V, r'b/2V"),(['CXtot','Cltot',"Cl'tot"],"CXtot, Cltot, Cl'tot"),
        (['CYtot','Cmtot'],'CYtot, Cmtot'),(['CZtot','Cntot',"Cn'tot"],"CZtot, Cntot, Cn'tot"),
        (['CLtot'],'CLtot'),(['CDtot'],'CDtot'),(['CDvis','CDind'],'CDvis, CDind'),
        (['CLff','CDff','CYff','e'],'Trefftz Plane: CLff, CDff, CYff, e')]:
        out.update(zip(keys,labelled(text,label,len(keys))))
    return out


def parse_elements(text):
    header(text,'ELE');surfaces=[];seen=set()
    for block in text.split('\nSURFACE\n')[1:]:
        name=block.splitlines()[0].strip();parts=block.split('\nSTRIP\n');info=parts[0]
        sid,nc,ns,first=labelled(info,'Surface #, # Chordwise, # Spanwise, First strip',4)
        coeff=labelled(info,'CLsurf, Clsurf, CYsurf, Cmsurf, CDsurf, Cnsurf, CDisurf, CDvsurf',8)
        rows=[]
        for part in parts[1:]:
            rid,n,vid=labelled(part,'Strip #, # Chordwise, First Vortex',3)
            if rid in seen:raise ValueError('AVL 条带编号重复')
            seen.add(rid)
            geom=labelled(part,'Xle, Ave. Chord, Incidence (deg), Yle, Strip Width, Strip Area, Zle, Strip Dihed (deg)',8)
            coefs=labelled(part,'cl, cd, cdv, cn, ca, cnc, wake dnwsh, cmLE, cm c/4',9)
            if geom[1]<=0 or geom[4]<=0 or geom[5]<=0:raise ValueError('AVL 条带面积或弦长非正')
            vortices=[line for line in part.splitlines() if '| I, X, Y, Z, DX, Slope, dCp' in line]
            if len(vortices)!=n:raise ValueError('AVL 涡元输出不完整')
            for line in vortices:numbers(line)
            rows.append(dict(zip(['x_le_m','chord_m','incidence_deg','y_le_m','width_m','area_m2','z_le_m','dihedral_deg'],geom)) |
                        dict(zip(['cl','cd','cdv','cn','ca','cnc','downwash','cm_le','cm_quarter'],coefs)) |
                        {'strip_id':int(rid),'surface':name})
        if len(rows)!=ns or nc<=0 or (rows and rows[0]['strip_id']!=first):raise ValueError('AVL 条带数不一致')
        surfaces.append({'name':name,'surface_id':int(sid),'coefficients':dict(zip(
            ['CL','Cl','CY','Cm','CD','Cn','CDi','CDv'],coeff)),'strips':rows})
    if len(surfaces)!=labelled(text.split('\nSURFACE\n')[0],'# surfaces',1)[0]:raise ValueError('AVL 升力面输出不完整')
    return surfaces


def parse_derivatives(text):
    header(text,'DERMATS');d={}
    for prefix,label in [('CL',"z' force CL  : CLa, CLb"),('CY','y force CY   : CYa, CYb'),
                         ('Cl',"x' mom.  Cl' : Cla, Clb"),('Cm','y  mom.  Cm  : Cma, Cmb'),('Cn',"z' mom.  Cn' : Cna, Cnb")]:
        a,b=labelled(text,label,2);d[prefix+'a']=a;d[prefix+'b']=b
    for prefix,label in [('CL',"z' force CL  : CLd*"),('Cm','y mom.  Cm   : Cmd*')]:
        d[prefix+'d']=labelled(text,label)
    return d


def controls_match(actual,expected):
    # MRF E-format rounds arbitrary solved deflections to its printed precision.
    return actual.keys()==expected.keys() and all(math.isclose(actual[k],v,rel_tol=1e-12,abs_tol=1e-12) for k,v in expected.items())


def dimensional_loads(surfaces,total,contract):
    """Project strips without inventing unreported spanwise forces or local moments."""
    r=contract['references'];q=contract['flow']['dynamic_pressure_pa'];a=math.radians(total['Alpha'])
    ref=np.array(r['moment_reference_geometry_m']);rows=[];checks=[];full=[]
    norm=np.array([r['span_m'],r['chord_m'],r['span_m']])*q*r['area_m2']
    for surface in surfaces:
        c=surface['coefficients'];fg=q*r['area_m2']*np.array([c['CD']*math.cos(a)-c['CL']*math.sin(a),c['CY'],c['CD']*math.sin(a)+c['CL']*math.cos(a)])
        mb=norm*np.array([c['Cl'],c['Cm'],c['Cn']]);mg=body_vectors(mb)
        projected=[]
        for row in surface['strips']:
            dih=math.radians(row['dihedral_deg']);normal=np.array([0.,-math.sin(dih),math.cos(dih)])
            tangent=np.array([0.,math.cos(dih),math.sin(dih)])
            point=np.array([row['x_le_m']+.25*row['chord_m'],row['y_le_m'],row['z_le_m']])
            force=q*row['area_m2']*(np.array([row['ca'],0.,0.])+normal*row['cn'])
            free=q*row['area_m2']*row['chord_m']*row['cm_quarter']*tangent
            item={**row,'point_geometry_m':point.tolist(),'force_geometry_n':force.tolist(),'free_moment_geometry_nm':free.tolist(),
                  'point_body_m':body_points(point,ref).tolist(),'force_body_n':body_vectors(force).tolist(),
                  'free_moment_body_nm':body_vectors(free).tolist(),'scope':'axial_normal_projection'}
            rows.append(item);projected.append(item)
        summed_f=np.sum([s['force_geometry_n'] for s in projected],axis=0)
        summed_m=np.sum([np.cross(np.array(s['point_geometry_m'])-ref,s['force_geometry_n'])+s['free_moment_geometry_nm'] for s in projected],axis=0)
        # Exact component audit only for horizontal/vertical template surfaces.
        vertical=all(abs(abs(s['dihedral_deg'])-90)<1e-8 for s in projected)
        horizontal=all(abs(s['dihedral_deg'])<1e-8 for s in projected)
        audited={}
        if horizontal or vertical:
            for key,actual,expected,scale in [('axial_force',summed_f[0],fg[0],q*r['area_m2']),
                ('normal_force',summed_f[1 if vertical else 2],fg[1 if vertical else 2],q*r['area_m2']),
                ('span_moment',summed_m[2 if vertical else 1],mg[2 if vertical else 1],norm[2 if vertical else 1])]:
                err=abs(actual-expected)/scale;audited[key]=err
                checks.append({'name':surface['name']+'/'+key,'coefficient_error':float(err),'passed':bool(err<1e-7)})
        full.append({'name':surface['name'],'coefficients':c,'force_body_n':body_vectors(fg).tolist(),'moment_body_nm':mb.tolist(),
                     'projected_force_residual_geometry_n':(summed_f-fg).tolist(),
                     'projected_moment_residual_geometry_nm':(summed_m-mg).tolist(),'audited_components':audited})
    force=q*r['area_m2']*np.array([total[k] for k in ('CXtot','CYtot','CZtot')])
    moment=norm*np.array([total[k] for k in ('Cltot','Cmtot','Cntot')])
    for key,actual,expected,scale in [('surface_force_sum',np.sum([s['force_body_n'] for s in full],axis=0),force,q*r['area_m2']),
                                    ('surface_moment_sum',np.sum([s['moment_body_nm'] for s in full],axis=0),moment,norm)]:
        error=float(np.max(np.abs((actual-expected)/scale)));checks.append({'name':key,'coefficient_error':error,'passed':error<1e-10})
    return {'schema_version':1,'coordinate_system':'geometry x aft/y right/z up; body x forward/y right/z down',
            'reference_geometry_m':ref.tolist(),'strips':rows,'surface_totals':full,'force_body_n':force.tolist(),
            'moment_body_nm':moment.tolist(),'checks':checks,'complete_six_component_strip_loads':False,
            'limits':contract['limits']}


def solve(contract,executable,work):
    work=Path(work)
    if not Path(executable).is_file():raise FileNotFoundError('未找到 AVL，请在工具设置中指定 avl.exe')
    (work/'model.avl').write_text(avl_input(contract),encoding='ascii')
    out=execute([executable],work,commands(contract),timeout=120)
    match=re.search(r'Program\s+Version\s+(\d+\.\d+)',out)
    if not match or match[1]!='3.40':raise ValueError('本版已验证 AVL 3.40 MRF；当前可执行版本未验证')
    if re.search(r'not recognized|forrtl:|convergence failed',out,re.I):raise ValueError('AVL 未完成指定工况，请查看日志')
    total=parse_total((work/'total.mrf').read_text('ascii'))
    surfaces=parse_elements((work/'elements.mrf').read_text('ascii'))
    derivatives=parse_derivatives((work/'stability.mrf').read_text('ascii'))
    r=contract['references'];f=contract['flow'];o=contract['options']
    pairs={'Sref':r['area_m2'],'Cref':r['chord_m'],'Bref':r['span_m'],
           **dict(zip(['Xref','Yref','Zref'],r['moment_reference_geometry_m'])),
           'Alpha':f['alpha_deg'],'Beta':f['beta_deg'],'Mach':f['mach'],'pb/2V':0.,'qc/2V':0.,'rb/2V':0.}
    checks=[{'name':'readback/'+k,'passed':math.isclose(total[k],v,rel_tol=1e-10,abs_tol=1e-10)} for k,v in pairs.items()]
    raw=(work/'total.mrf').read_text('ascii').split('CONTROL\n',1)[1].split('DESIGN')[0].strip().splitlines()
    controls={line.split()[1]:float(line.split()[0]) for line in raw[1:]}
    checks.append({'name':'controls_readback','passed':controls_match(controls,{c['name']:o[c['name']+'_deg'] for c in contract['controls']})})
    checks.append({'name':'five_surface_copies','passed':len(surfaces)==5 and
        {s['name'] for s in surfaces}=={'MainWing','MainWing (YDUP)','HorizontalTail','HorizontalTail (YDUP)','VerticalTail'}})
    checks.append({'name':'three_control_derivatives','passed':len(derivatives['CLd'])==len(derivatives['Cmd'])==3})
    for surface in surfaces:
        original=next(s for s in contract['surfaces'] if s['name']==surface['name'].replace(' (YDUP)',''))
        expected=original['area_m2']/(2 if original['symmetric'] else 1)
        actual=sum(row['area_m2'] for row in surface['strips'])
        # AVL's segmented cosine lattice samples chord at strip stations; this is
        # a discretized area integral, not the exact trapezoidal source planform.
        checks.append({'name':surface['name']+'/actual_strip_area','relative_error':abs(actual/expected-1),
                       'passed':math.isclose(actual,expected,rel_tol=1e-3)})
    case=(work/'case.run').read_text('ascii')
    for key,value in [('velocity',f['speed_m_s']),('density',f['density_kg_m3']),('mass',f['mass_kg']),('grav.acc.',9.80665)]:
        matches=re.findall(r'^\s*'+re.escape(key)+r'\s*=\s*('+NUMBER+r')',case,re.M)
        checks.append({'name':'dimensional_readback/'+key,'passed':len(matches)==1 and math.isclose(float(matches[0]),value,rel_tol=1e-5)})
    loads=dimensional_loads(surfaces,total,contract);checks+=loads['checks']
    if not all(c['passed'] for c in checks):
        write_json(work/'checks_failed.json',checks);raise ValueError('AVL 工况、参考量或载荷积分检查失败')
    trim=trim_interface(contract,total,derivatives)
    write_json(work/'strip_loads.json',loads);write_json(work/'trim_interface.json',trim)
    return {'status':'aero_checked_with_limits','passed':True,'solver_version':match[1],'solver_sha256':sha256(executable),
            'references':r,'flow':f,'coefficients':total,'derivatives':derivatives,'derivative_axes':'AVL standard stability axes; angles per radian, controls per degree',
            'controls':contract['controls'],'options':o,'strip_count':len(loads['strips']),'checks':checks,'trim':trim,
            'force_body_n':loads['force_body_n'],'moment_body_nm':loads['moment_body_nm'],
            'trim_checked':False,'physical_validation_passed':False,'mission_polar_updated':False,'limits':contract['limits']}
