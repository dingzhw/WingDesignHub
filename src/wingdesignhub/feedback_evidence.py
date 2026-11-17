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


def pack_native(work):
    from .job_events import event
    started=time.monotonic();event('pack_started',directory=str(work))
    work=Path(work);paths=sorted(p for p in (work/'native').rglob('*') if p.is_file())
    manifest={'files':{},'uncompressed_bytes':sum(p.stat().st_size for p in paths),
              'scope':'original native inputs, commands, logs, geometry, trim and drag outputs; never execute on import'}
    if len(paths)>MAX_NATIVE_FILES or manifest['uncompressed_bytes']>MAX_NATIVE_BYTES:raise ValueError('原生证据超过单次运行容量限制')
    with ZipFile(work/'native_evidence.zip','w',ZIP_DEFLATED) as z:
        for p in paths:
            name=p.relative_to(work/'native').as_posix();z.write(p,name);manifest['files'][name]=sha256(p)
    manifest['archive_sha256']=sha256(work/'native_evidence.zip')
    write_json(work/'native_manifest.json',manifest)
    event('pack_finished',directory=str(work),elapsed_s=time.monotonic()-started,
          file_count=len(paths),uncompressed_bytes=manifest['uncompressed_bytes'],archive_bytes=(work/'native_evidence.zip').stat().st_size)
    return manifest


def check_native(data,manifest):
    if hashlib.sha256(data).hexdigest()!=manifest['archive_sha256']:raise ValueError('原生证据包哈希不符')
    with ZipFile(BytesIO(data)) as z:
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

