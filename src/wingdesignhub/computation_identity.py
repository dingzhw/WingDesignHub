"""Conservative dependency closures, with explicit subprocess and data edges.

Audit hashes still include all sources. Calculation identity excludes presentation.
Utility boundaries hash the entire utility file plus their execution dependencies;
their unrelated dispatch functions do not expand a numerical cache into all tools.
"""
import ast
import hashlib
import importlib.util
from importlib.metadata import version, PackageNotFoundError
import json
from pathlib import Path
from .adapters import sha256,tool_paths

BASE=Path(__file__).parent
BOUNDARIES={'service':('job_events',),'job_events':(),
            'adapters':('bounded_output','processes'),'jobs':('processes','job_events'),
            'computation_identity':()}
EXTRA={'coupled_worker':('aircraft_vsp_worker','drag_geometry_worker','ccblade_adapter'),
       'feedback_worker':('aircraft_vsp_worker','drag_geometry_worker'),
       'feedback_native':('aircraft_vsp_worker','drag_geometry_worker'),
       'sizing_worker':('fastga_plugins.furniture','fastga_plugins.unusable_fuel'),
       'ccblade_adapter':(), 'geometry_service':('aircraft_vsp_worker',),
       'drag_service':('drag_geometry_worker',)}
ENTRIES={'size':('sizing_worker',),'coupled':('coupled_worker',),'feedback':('feedback_worker',),
         'geometry':('aircraft_vsp_worker','aircraft_geometry'),'aero':('avl_aircraft',),
         'trim':('aircraft_trim',),'drag':('aircraft_drag','drag_geometry_worker'),
       'propulsion':('propulsion_service',),'fastga_reference':('fastga_worker',),
         'tools':('tool_health',),'compare':('coupled_worker','sizing_worker','design_comparison')}
MODES={'overall_sizing':'size','overall_feedback':'feedback','overall_propulsion':'coupled',
       'aircraft_geometry':'geometry','aircraft_aero':'aero','aircraft_trim':'trim','aircraft_drag':'drag',
       'propulsion_replay':'propulsion','overall_comparison':'compare'}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()


def sources(entries,base=None):
    base=Path(base or BASE);pending=list(entries)+['computation_identity'];found={}
    while pending:
        name=pending.pop();path=base/(name.replace('.','/')+'.py')
        if not path.is_file():path=base/name.replace('.','/')/'__init__.py'
        if not path.is_file():raise ValueError('计算依赖源码缺失：'+name)
        key=path.relative_to(base).as_posix()
        if key in found:continue
        found[key]=sha256(path)
        if name in BOUNDARIES:pending.extend(BOUNDARIES[name]);continue
        package=name.split('.')[:-1]
        for node in ast.walk(ast.parse(path.read_text('utf-8-sig'))):
            if isinstance(node,ast.ImportFrom) and node.level:
                prefix=package[:len(package)-node.level+1]
                if node.module:pending.append('.'.join(prefix+[node.module]))
                else:
                    # from . import __version__ comes from the package initializer.
                    pending.append('.'.join(prefix+['__init__']))
        pending.extend(EXTRA.get(name,()))
    return dict(sorted(found.items()))


def environment(root,kind):
    result={};paths=tool_paths(root)
    def file(label,path):
        path=Path(path)
        result[label]=sha256(path) if path.is_file() else 'missing'
    packages=['numpy','scipy']
    aero=kind in ('aero','trim','drag','feedback','coupled','compare')
    prop=kind in ('ccblade','propulsion','coupled','compare','tools')
    geo=kind in ('geometry','drag','feedback','coupled','compare')
    mass=kind in ('size','feedback','coupled','compare','fastga_reference')
    if aero:file('avl',paths['avl'])
    if kind in ('drag','feedback','coupled','compare','propulsion'):file('xfoil',paths['xfoil'])
    if geo:
        spec=importlib.util.find_spec('openvsp')
        if spec:
            folder=Path(spec.origin).parent
            for pattern in ('*.py','*.pyd','*.dll'):
                for p in sorted(folder.rglob(pattern)):file('openvsp/'+p.relative_to(folder).as_posix(),p)
        else:result['openvsp']='missing'
    if mass or kind in ('propulsion','coupled','compare'):
        packages+=['fast-oad-cs23','fast-oad-core','openmdao']
        spec=importlib.util.find_spec('fastga')
        if spec:
            folder=Path(spec.origin).parent
            for part in ('models/weight/mass_breakdown','models/propulsion/fuel_propulsion/basicIC_engine','source_data_files'):
                for p in sorted((folder/part).rglob('*')):
                    if p.is_file() and p.suffix in ('.py','.csv','.xml','.yml'):file('fastga/'+p.relative_to(folder).as_posix(),p)
    if prop:
        file('ccblade_worker.jl',BASE/'ccblade_worker.jl')
        cfg=Path(root)/'local/propulsion-tools.json'
        if cfg.is_file():
            data=json.loads(cfg.read_text('utf-8'))
            file('julia',data['julia'])
            for n in ('Project.toml','Manifest.toml'):file('julia_environment/'+n,Path(data['project'])/n)
            folder=Path(data['package'])
            for p in sorted((folder/'src').rglob('*.jl')):file('CCBlade/'+p.relative_to(folder).as_posix(),p)
            file('CCBlade/Project.toml',folder/'Project.toml')
        else:result['julia_environment']='missing'
    for name in packages:
        try:result['package/'+name]=version(name)
        except PackageNotFoundError:result['package/'+name]='missing'
    return result


def calculation(root,kind):
    if kind not in ENTRIES:raise ValueError('未定义计算依赖入口：'+kind)
    code=sources(ENTRIES[kind])
    for name in ('job_runner.py','job_worker.py','jobs.py'):code[name]=sha256(BASE/name)
    return {'schema':1,'kind':kind,'sources':code,'environment':environment(root,kind)}


def source_compatible(record):
    saved=record.get('calculation_identity')
    if saved:
        code=sources(ENTRIES[saved['kind']])
        for name in ('job_runner.py','job_worker.py','jobs.py'):code[name]=sha256(BASE/name)
        audit=record.get('source_hashes',{})
        return saved['sources']==code and all(audit.get(n)==h for n,h in saved['sources'].items())
    from .geometry_service import source_hashes
    return record.get('source_hashes')==source_hashes()


def compatible(record,root):
    saved=record.get('calculation_identity')
    if saved:return source_compatible(record) and saved==calculation(root,saved['kind'])
    # Legacy evidence remains readable; using it for a new stage is conservative.
    from .geometry_service import source_hashes
    return record.get('source_hashes')==source_hashes()


def comparison_compatible(records):
    """Blocked sizing seeds may have a smaller closure than enhanced results."""
    if len({r['version'] for r in records})!=1:return False
    if not all('calculation_identity' in r for r in records):
        return len({digest(r['source_hashes']) for r in records})==1
    union={}
    for r in records:
        identity=r['calculation_identity']
        for group in ('sources','environment'):
            for name,value in identity[group].items():
                key=group+'/'+name
                if key in union and union[key]!=value:return False
                union[key]=value
    return True
