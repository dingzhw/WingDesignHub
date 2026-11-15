"""Portable, inert project bundles; loading never executes or overwrites a run."""
from datetime import datetime,timezone
from io import BytesIO
from pathlib import Path,PurePosixPath
from uuid import uuid4,UUID
from zipfile import ZipFile,ZIP_DEFLATED,BadZipFile
from importlib.metadata import version,PackageNotFoundError
import hashlib
import json
from . import __version__
from .requirements import DesignProject
from .design_comparison import ComparisonRequest
from .service import get_results

MAX_BYTES=50*1024*1024
MAX_FILES=256


def digest(data):return hashlib.sha256(data).hexdigest()


def encoded(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode('utf-8')


def safe_name(name):
    p=PurePosixPath(name)
    if not isinstance(name,str) or not name or '\\' in name or ':' in name or p.is_absolute() or '..' in p.parts or p.as_posix()!=name:
        raise ValueError('方案包含非法路径')
    return name


def raw_definition(data,kind):
    # Preserve the original schema when checking archived records; migration is separate.
    if kind=='comparison':
        obj={'purpose':data['purpose'],'schema_version':data['schema_version'],
             'definitions':[raw_definition(p,'design') for p in data['projects']]}
        return digest(json.dumps(obj,sort_keys=True).encode())
    obj=dict(data);obj.pop('confirmation_sha256',None)
    def normalize(x):
        if isinstance(x,dict):return {k:normalize(v) for k,v in x.items()}
        return float(x) if type(x) in (int,float) else x
    return digest(json.dumps(normalize(obj),ensure_ascii=False,sort_keys=True,allow_nan=False).encode())


def build_bundle(project,root,record=None):
    kind='comparison' if isinstance(project,ComparisonRequest) else 'design'
    project.validate() if kind=='comparison' else project.check_schema()
    source=project.to_dict();files={'project.json':encoded(source)};ids=[]
    if record is not None:
        actual=get_results(root,record['run_id'])
        if actual!=record:raise ValueError('待保存结果与实际运行记录不符')
        expected='overall_comparison' if kind=='comparison' else 'overall_sizing'
        if actual['mode']!=expected or actual['definition_sha256']!=project.definition_hash():
            raise ValueError('结果属于其他定义，请先重新计算或仅保存需求草案')
        if kind=='comparison' and any(p.confirmation_sha256!=p.definition_hash() for p in project.projects):
            raise ValueError('当前比较尚未确认，不能附上旧计算结果')
        if kind=='design' and project.confirmation_sha256!=project.definition_hash():
            raise ValueError('当前需求尚未确认，不能附上旧计算结果')
        ids=[actual['run_id'],*actual.get('child_runs',[])]
        for rid in ids:
            r=get_results(root,rid);work=Path(root)/'runs'/rid
            for name in ['result.json',*r.get('artifact_hashes',{})]:
                safe_name(name);p=(work/name).resolve()
                if not p.is_relative_to(work.resolve()):raise ValueError('运行产物路径越界')
                files[f'runs/{rid}/{name}']=p.read_bytes()
        for filename in ('report.html','report.md'):
            p=Path(root)/'runs'/ids[0]/filename
            if p.is_file():files['reports/'+filename]=p.read_bytes()
    name=source['name'] if kind=='design' else source['projects'][0]['name']+' 等三方案'
    manifest={'bundle_schema':1,'kind':kind,'name':name,'software_version':__version__,
              'created_utc':datetime.now(timezone.utc).isoformat(),'run_ids':ids,
              'definition_sha256':project.definition_hash(),'files':{n:digest(b) for n,b in files.items()},
              'integrity_scope':'SHA-256 detects damaged contents; this is not a signed authenticity certificate'}
    stream=BytesIO()
    with ZipFile(stream,'w',ZIP_DEFLATED) as z:
        for name,data in files.items():z.writestr(name,data)
        z.writestr('manifest.json',encoded(manifest))
    result=stream.getvalue();read_bundle(result);return result


def read_bundle(data):
    """Check all members in memory, with no extraction and no HTML execution."""
    if not isinstance(data,bytes) or len(data)>MAX_BYTES:raise ValueError('方案包大小超出 50 MB 限制')
    try:
        with ZipFile(BytesIO(data)) as z:
            infos=z.infolist();names=[safe_name(i.filename) for i in infos]
            if len(names)>MAX_FILES or len(names)!=len(set(names)) or 'manifest.json' not in names:
                raise ValueError('方案包文件数量、重复项或清单无效')
            if sum(i.file_size for i in infos)>MAX_BYTES or any(i.flag_bits&1 or i.is_dir() or (i.external_attr>>16)&0o170000==0o120000 for i in infos):
                raise ValueError('方案包解压大小或文件类型不支持')
            files={i.filename:z.read(i) for i in infos}
    except (BadZipFile,RuntimeError,EOFError) as exc:raise ValueError('方案包无法读取或已损坏') from exc
    try:
        manifest=json.loads(files.pop('manifest.json'))
        if type(manifest.get('bundle_schema')) is not int or manifest['bundle_schema']!=1:raise ValueError('方案包版本不支持')
        if manifest['kind'] not in ('design','comparison'):raise ValueError('方案包类型无效')
        if set(manifest['files'])!=set(files) or any(digest(b)!=manifest['files'][n] for n,b in files.items()):
            raise ValueError('方案包文件完整性检查失败')
        source=json.loads(files['project.json']);kind=manifest['kind']
        project=ComparisonRequest.from_dict(source) if kind=='comparison' else DesignProject.from_dict(source)
        if raw_definition(source,kind)!=manifest['definition_sha256']:raise ValueError('方案包需求哈希不符')
        records=[];ids=manifest['run_ids']
        if len(set(ids))!=len(ids) or len(ids)>(4 if kind=='comparison' else 1):raise ValueError('方案包运行列表无效')
        for rid in ids:
            if UUID(rid).hex!=rid:raise ValueError('方案包运行编号无效')
            prefix=f'runs/{rid}/';r=json.loads(files[prefix+'result.json'])
            if r['run_id']!=rid:raise ValueError('方案包运行身份不符')
            for name,h in r['artifact_hashes'].items():
                safe_name(name)
                if digest(files[prefix+name])!=h:raise ValueError('方案包运行产物哈希不符')
            if digest(files[prefix+'input.json'])!=r['input_hash']:raise ValueError('方案包运行输入哈希不符')
            run_kind='comparison' if r['mode']=='overall_comparison' else 'design'
            if raw_definition(json.loads(files[prefix+'input.json']),run_kind)!=r['definition_sha256']:
                raise ValueError('方案包运行输入与定义不符')
            summary_name='comparison.json' if run_kind=='comparison' else 'summary.json'
            if prefix+summary_name in files and json.loads(files[prefix+summary_name])!=r.get('summary'):
                raise ValueError('方案包摘要与运行结果不符')
            records.append(r)
        if records:
            expected='overall_comparison' if kind=='comparison' else 'overall_sizing'
            if records[0]['mode']!=expected or records[0]['definition_sha256']!=manifest['definition_sha256']:
                raise ValueError('方案包结果与需求不符')
            if records[0].get('child_runs',[])!=ids[1:]:raise ValueError('方案包子运行列表不符')
            for i,r in enumerate(records[1:]):
                if r['mode']!='overall_sizing' or r['definition_sha256']!=raw_definition(source['projects'][i],'design'):
                    raise ValueError('方案包子运行与需求不符')
            for filename in ('report.html','report.md'):
                if 'reports/'+filename in files and files['reports/'+filename]!=files[f'runs/{ids[0]}/{filename}']:
                    raise ValueError('方案包报告与运行产物不一致')
        current={p.relative_to(Path(__file__).parent).as_posix():digest(p.read_bytes()) for p in Path(__file__).parent.rglob('*.py')}
        compatible=all(r.get('version')==__version__ and r.get('source_hashes')==current for r in records)
        for r in records:
            for package,recorded in r.get('summary',{}).get('versions',{}).items():
                try:compatible=compatible and version(package)==recorded
                except PackageNotFoundError:compatible=False
        return {'manifest':manifest,'input':source,'project':project,'records':records,'files':files,
                'migration_required':project.definition_hash()!=manifest['definition_sha256'],
                'current_source_matches':compatible,'bundle_sha256':digest(data)}
    except (KeyError,TypeError,UnicodeError,json.JSONDecodeError,AttributeError) as exc:
        raise ValueError('方案包清单或记录格式无效') from exc


def save_bundle(data,root):
    parsed=read_bundle(data);directory=Path(root)/'local'/'projects';directory.mkdir(parents=True,exist_ok=True)
    sid=uuid4().hex;path=directory/(sid+'.wdh')
    with path.open('xb') as f:f.write(data)
    index={k:parsed['manifest'][k] for k in ('name','kind','created_utc','software_version')}
    index.update(archive_id=sid,bundle_sha256=digest(data),has_results=bool(parsed['records']))
    with (directory/(sid+'.json')).open('xb') as f:f.write(encoded(index))
    return index


def list_saved(root):
    rows=[]
    for p in (Path(root)/'local'/'projects').glob('*.json'):
        try:
            row=json.loads(p.read_text('utf-8'))
            if UUID(p.stem).hex!=p.stem or row['archive_id']!=p.stem:continue
            if p.with_suffix('.wdh').is_file():rows.append(row)
        except (ValueError,KeyError,TypeError):continue
    return sorted(rows,key=lambda r:r['created_utc'],reverse=True)


def load_saved(root,archive_id):
    if UUID(archive_id).hex!=archive_id:raise ValueError('本机方案编号无效')
    directory=Path(root)/'local'/'projects';data=(directory/(archive_id+'.wdh')).read_bytes()
    index=json.loads((directory/(archive_id+'.json')).read_text('utf-8'))
    if digest(data)!=index['bundle_sha256']:raise ValueError('本机方案文件完整性检查失败')
    return read_bundle(data)
