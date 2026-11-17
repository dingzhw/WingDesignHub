"""Lossless native run evidence; archives are checked in memory, never executed."""
from pathlib import Path, PurePosixPath
from zipfile import ZipFile, ZIP_DEFLATED
from io import BytesIO
import hashlib
import time
from .adapters import sha256
from .service import write_json

MAX_NATIVE_BYTES=4*1024**3
MAX_NATIVE_FILES=100000


def pack_native(work, *, native_root=None):
    from .job_events import event
    started=time.monotonic();event('pack_started',directory=str(work))
    work=Path(work);source=Path(native_root) if native_root is not None else work/'native'
    paths=sorted(p for p in source.rglob('*') if p.is_file())
    manifest={'files':{},'uncompressed_bytes':sum(p.stat().st_size for p in paths),
              'scope':'original native inputs, commands, logs, geometry, trim and drag outputs; never execute on import'}
    if len(paths)>MAX_NATIVE_FILES or manifest['uncompressed_bytes']>MAX_NATIVE_BYTES:raise ValueError('原生证据超过单次运行容量限制')
    manifest['storage']='sha256_objects_v1';written=set()
    with ZipFile(work/'native_evidence.zip','w',ZIP_DEFLATED) as z:
        for p in paths:
            name=p.relative_to(source).as_posix();h=sha256(p);manifest['files'][name]=h
            if h not in written:z.write(p,'objects/'+h);written.add(h)
    manifest['archive_sha256']=sha256(work/'native_evidence.zip')
    write_json(work/'native_manifest.json',manifest)
    event('pack_finished',directory=str(work),elapsed_s=time.monotonic()-started,
          file_count=len(paths),uncompressed_bytes=manifest['uncompressed_bytes'],archive_bytes=(work/'native_evidence.zip').stat().st_size)
    return manifest


def check_native(data,manifest):
    if hashlib.sha256(data).hexdigest()!=manifest['archive_sha256']:raise ValueError('原生证据包哈希不符')
    with ZipFile(BytesIO(data)) as z:
        if manifest.get('storage')=='sha256_objects_v1':
            import re
            logical=manifest['files'];infos=z.infolist();sizes={i.filename:i.file_size for i in infos}
            hashes=set(logical.values())
            if (len(logical)>MAX_NATIVE_FILES or len(sizes)!=len(infos) or
                any(not isinstance(h,str) or not re.fullmatch('[0-9a-f]{64}',h) for h in hashes) or
                set(sizes)!={'objects/'+h for h in hashes}):raise ValueError('去重证据清单无效')
            total=0
            for name,h in logical.items():
                p=PurePosixPath(name)
                if not name or p.is_absolute() or '..' in p.parts or ':' in name or '\\' in name or p.as_posix()!=name:raise ValueError('去重证据路径无效')
                total+=sizes['objects/'+h]
            if total!=manifest['uncompressed_bytes'] or total>MAX_NATIVE_BYTES:raise ValueError('去重证据大小不符')
            for i in infos:
                if i.flag_bits&1 or i.is_dir() or (i.external_attr>>16)&0o170000==0o120000:raise ValueError('去重证据类型无效')
                h=hashlib.sha256()
                with z.open(i) as stream:
                    while chunk:=stream.read(1024*1024):h.update(chunk)
                if h.hexdigest()!=i.filename.split('/')[1]:raise ValueError('去重证据内容损坏')
            return
        if manifest.get('storage') is not None:raise ValueError('未知证据格式')
        infos=z.infolist();names=[i.filename for i in infos]
        if len(names)>MAX_NATIVE_FILES or len(set(names))!=len(names) or set(names)!=set(manifest['files']):raise ValueError('原生证据清单不符')
        total=sum(i.file_size for i in infos)
        if total>MAX_NATIVE_BYTES or total!=manifest['uncompressed_bytes']:raise ValueError('原生证据大小无效')
        for info in infos:
            name=info.filename;p=PurePosixPath(name)
            if (not name or p.is_absolute() or '..' in p.parts or ':' in name or '\\' in name or p.as_posix()!=name or
                info.flag_bits&1 or info.is_dir() or (info.external_attr>>16)&0o170000==0o120000):raise ValueError('原生证据路径或文件类型无效')
            h=hashlib.sha256()
            with z.open(info) as stream:
                while chunk:=stream.read(1024*1024):h.update(chunk)
            if h.hexdigest()!=manifest['files'][name]:raise ValueError('原生证据文件损坏：'+name)

