"""Exact-input, hash-verified bounded ZIP cache. No rounding or failed entries."""
import json,os,re
from pathlib import Path,PurePosixPath
from uuid import uuid4
import zipfile
from .computation_identity import digest
from .adapters import sha256


def valid_name(name):
    p=PurePosixPath(name)
    return bool(name) and not p.is_absolute() and '..' not in p.parts and '\\' not in name and ':' not in name


class ExactCache:
    def __init__(self,root,namespace):
        scope=os.environ.get('WDH_COMPUTATION_CACHE_NAMESPACE','')
        if scope and not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',scope):raise ValueError('计算缓存命名空间无效')
        self.root=(Path(root)/scope if scope else Path(root))/namespace

    def restore(self,identity,work):
        path=self.root/(digest(identity)+'.zip')
        if not path.exists():return False
        with zipfile.ZipFile(path) as z:
            if len(z.namelist())!=len(set(z.namelist())):raise ValueError('计算缓存重复成员')
            if sum(i.file_size for i in z.infolist())>256*1024*1024:raise ValueError('计算缓存超过容量限制')
            manifest=json.loads(z.read('manifest.json'))
            if manifest['identity']!=json.loads(json.dumps(identity)):raise ValueError('计算缓存身份不匹配')
            files=manifest['files']
            if set(z.namelist())!=set(files)|{'manifest.json'} or not all(valid_name(n) for n in files):raise ValueError('计算缓存文件清单无效')
            import hashlib
            for name,h in files.items():
                data=z.read(name)
                if hashlib.sha256(data).hexdigest()!=h:raise ValueError('计算缓存哈希不匹配：'+name)
            for name in files:
                dest=Path(work)/name
                if dest.exists():raise ValueError('计算缓存禁止覆盖已有产物：'+name)
                dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(z.read(name))
        return True

    def publish(self,identity,work,names):
        if not all(valid_name(n) and n!='manifest.json' for n in names):raise ValueError('计算缓存路径无效')
        self.root.mkdir(parents=True,exist_ok=True);path=self.root/(digest(identity)+'.zip')
        if path.exists():return
        manifest={'identity':identity,'files':{n:sha256(Path(work)/n) for n in names}}
        temp=self.root/(uuid4().hex+'.tmp')
        with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('manifest.json',json.dumps(manifest,sort_keys=True,allow_nan=False))
            for name in names:z.write(Path(work)/name,name)
        try:temp.rename(path)
        except FileExistsError:temp.unlink()
