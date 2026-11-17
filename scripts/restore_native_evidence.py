"""Restore checked legacy or content-deduplicated evidence to a NEW directory."""
from pathlib import Path
from zipfile import ZipFile
from io import BytesIO
import argparse,json,hashlib
from wingdesignhub.feedback_evidence import check_native


def restore(archive,manifest_path,destination):
    data=Path(archive).read_bytes();manifest=json.loads(Path(manifest_path).read_text('utf-8'))
    check_native(data,manifest)
    destination=Path(destination).resolve()
    destination.mkdir(parents=True,exist_ok=False)
    with ZipFile(BytesIO(data)) as z:
        for name,h in manifest['files'].items():
            target=destination/name
            if not target.resolve().is_relative_to(destination):raise ValueError('恢复路径越界')
            raw=z.read('objects/'+h if manifest.get('storage')=='sha256_objects_v1' else name)
            if hashlib.sha256(raw).hexdigest()!=h:raise ValueError('恢复内容损坏')
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as f:f.write(raw)
    return len(manifest['files'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('archive');p.add_argument('manifest');p.add_argument('destination')
    a=p.parse_args();print(restore(a.archive,a.manifest,a.destination))
