"""Explicitly detached debug evidence; no synthetic bytes or implied verification."""
import json
import re


class EvidenceFiles(dict):
    def __init__(self, files, detached):
        super().__init__(files)
        self.detached=detached
        for name,h in detached.items():
            if (not re.fullmatch(r'runs/[0-9a-f]{32}/native_evidence\.zip',name)
                    or not isinstance(h,str) or not re.fullmatch(r'[0-9a-f]{64}',h) or name in files):
                raise ValueError('分离证据引用无效')


def check_packaged_native(files,prefix):
    from .feedback_evidence import check_native
    name=prefix+'native_evidence.zip'
    if prefix+'native_manifest.json' not in files:raise ValueError('缺少原生证据清单')
    manifest=json.loads(files[prefix+'native_manifest.json'])
    if name in files:check_native(files[name],manifest)
    elif getattr(files,'detached',{}).get(name)==manifest['archive_sha256']:
        # Only reference identity is checked. Native bytes are explicitly absent.
        return 'detached_not_verified'
    else:raise ValueError('缺少原生证据或其引用不一致')
    return 'embedded_verified'
