import json
import xml.etree.ElementTree as ET
import pytest
from wingdesignhub.fea_mesh import StructureMeshCase, read_inp, audit_mesh, write_preview


@pytest.fixture
def box_fixture():
    """A deliberately synthetic closed box with shared plate edges for validator tests."""
    c=StructureMeshCase()
    xs=[0.,c.front_spar_fraction*c.chord_m,c.rear_spar_fraction*c.chord_m,c.chord_m]
    ys=[0.]+[v*c.half_span_m for v in c.rib_fractions]+[c.half_span_m]
    zs=[-.06*c.chord_m,.06*c.chord_m]
    nodes={};lookup={};elements={};sets={};types={};sections={}
    for i,x in enumerate(xs):
        for j,y in enumerate(ys):
            for k,z in enumerate(zs):
                n=len(nodes)+1;nodes[n]=[x,y,z];lookup[i,j,k]=n
    def quad(part,indices):
        key=f'E{part}_test';sets.setdefault(key,[])
        ns=[lookup[v] for v in indices]
        for conn in ([ns[0],ns[1],ns[2]],[ns[0],ns[2],ns[3]]):
            e=len(elements)+1;elements[e]=conn;types[e]='S3';sets[key].append(e)
    for k in (0,1):
        for i in range(3):
            for j in range(len(ys)-1):quad('Skin',[(i,j,k),(i+1,j,k),(i+1,j+1,k),(i,j+1,k)])
    for i,part in ((0,'Skin'),(3,'Skin'),(1,'FrontSpar'),(2,'RearSpar')):
        for j in range(len(ys)-1):quad(part,[(i,j,0),(i,j+1,0),(i,j+1,1),(i,j,1)])
    for j in range(len(ys)):
        part='Skin' if j in (0,len(ys)-1) else f'Rib{j-1}'
        for i in range(3):quad(part,[(i,j,0),(i+1,j,0),(i+1,j,1),(i,j,1)])
    for part,t in c.part_thicknesses.items():sections[f'E{part}_test']={'thickness_m':t,'material':'M'}
    return c,{'nodes':nodes,'elements':elements,'sets':sets,'types':types,'sections':sections,
              'materials':{'M':{'density_kg_m3':2700.,'elastic_modulus_pa':70e9,'poisson_ratio':.33}}}


def test_schema_bounds_and_roundtrip():
    case=StructureMeshCase.from_dict(json.loads(json.dumps(StructureMeshCase().to_dict())))
    assert case.rib_fractions[0]==.1
    for change in ({'rib_count':True},{'max_edge_m':float('nan')},{'min_edge_m':.5},{'poisson_ratio':.5},{'front_spar_fraction':.9},{'schema_version':2}):
        with pytest.raises(ValueError):StructureMeshCase.from_dict({**case.to_dict(),**change})


def test_mesh_quality_mass_and_svg(box_fixture,tmp_path):
    c,m=box_fixture;r=audit_mesh(m,c)
    assert r['connected_components']==1 and r['orphan_nodes']==0
    assert r['parts']['FrontSpar']['area_m2']==pytest.approx(c.half_span_m*.12*c.chord_m)
    assert r['shell_material_mass_kg']==pytest.approx(sum(p['mass_kg'] for p in r['parts'].values()))
    p=tmp_path/'preview.svg';write_preview(m,p);assert ET.parse(p).getroot().tag.endswith('svg')


@pytest.mark.parametrize('corruption',['orphan','zero_area','missing_part','wrong_units','wrong_position','duplicate','disconnected'])
def test_bad_mesh_is_rejected(box_fixture,corruption):
    c,m=box_fixture
    if corruption=='orphan':m['nodes'][99999]=[0.,0.,0.]
    if corruption=='zero_area':
        conn=next(iter(m['elements'].values()));m['nodes'][conn[1]]=m['nodes'][conn[0]].copy()
    if corruption=='missing_part':m['sets']['ESkin_test']=[]
    if corruption=='wrong_units':m['materials']['M']['elastic_modulus_pa']=70e3
    if corruption=='wrong_position':
        c=StructureMeshCase(front_spar_fraction=.26)
    if corruption=='duplicate':m['elements'][99999]=next(iter(m['elements'].values())).copy()
    if corruption=='disconnected':
        m['nodes'].update({99001:[10.,0.,0.],99002:[11.,0.,0.],99003:[10.,1.,0.]})
        m['elements'][99999]=[99001,99002,99003]
    with pytest.raises(ValueError):audit_mesh(m,c)


def test_inp_parser_rejects_external_or_ambiguous_input(tmp_path):
    p=tmp_path/'mesh.inp'
    good='*NODE\n1,0,0,0\n2,1,0,0\n3,0,1,0\n*ELEMENT,TYPE=S3,ELSET=A\n1,1,2,3\n'
    p.write_text(good);assert read_inp(p)['elements']=={1:[1,2,3]}
    for bad in (good+'*INCLUDE,INPUT=other.inp',good.replace('1,1,2,3','1,1,2,9'),good.replace('S3','S6'),good+'*NODE\n1,0,0,0',good.replace('2,1,0,0','2,nan,0,0')):
        p.write_text(bad)
        with pytest.raises(ValueError):read_inp(p)


def test_quadrilateral_geometry_and_self_intersection(box_fixture):
    c,m=box_fixture;quads={};newsets={};types={}
    for name,ids in m['sets'].items():
        newsets[name]=[]
        for first,second in zip(ids[::2],ids[1::2]):
            n=len(quads)+1
            quads[n]=m['elements'][first]+[m['elements'][second][-1]]
            newsets[name].append(n);types[n]='S4'
    m.update(elements=quads,sets=newsets,types=types)
    assert audit_mesh(m,c)['element_types']==['S4']
    conn=m['elements'][1];conn[1],conn[2]=conn[2],conn[1]
    with pytest.raises(ValueError,match='四边形'):audit_mesh(m,c)


def test_native_default_mesh_and_center_rib_failure(tmp_path):
    pytest.importorskip('openvsp')
    from wingdesignhub.structure_service import run_structure_mesh
    from wingdesignhub.service import get_results
    ok=run_structure_mesh(StructureMeshCase(),tmp_path)
    assert ok['status']=='mesh_checked',ok
    assert ok['summary']['metrics']['parts']['Skin']['elements']>0
    assert get_results(tmp_path,ok['run_id'])['status']=='mesh_checked'
    bad=run_structure_mesh(StructureMeshCase(rib_count=5),tmp_path)
    assert bad['status']=='failed'
    assert '退化' in bad['diagnostic']
    assert (tmp_path/'runs'/bad['run_id']/'mesh/wing.inp').exists()
