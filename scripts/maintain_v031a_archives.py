"""Explicit, reversible removal of duplicate developer validation exports only."""
from pathlib import Path
import argparse,json,hashlib,shutil

ROOT=Path(__file__).resolve().parents[1]
INDEX=ROOT/'local/v031a/history-recovery.json'
ALLOWED={
 'local/v030-native02/three-designs.wdh','local/v030-native03/three-designs.wdh',
 'local/v030-ui/three-designs.wdh','local/v027-validation01/coupled.wdh',
 'local/v026-validation01/propulsion.wdh','local/v025-validation02/baseline.wdh'}

def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def safe(name):
    p=ROOT/name
    if not p.resolve().is_relative_to(ROOT.resolve()):raise ValueError('outside project')
    for parent in [p,*p.parents]:
        if parent==ROOT.parent:break
        if parent.is_symlink() or parent.is_junction():raise ValueError('link in archive path')
    return p

def main(mode):
    if mode=='plan':
        audit=json.loads((ROOT/'local/storage_audit_v031/archives.json').read_text('utf-8'))
        rows=[]
        for group in audit['duplicate_groups']:
            canonical=next((p for p in group['paths'] if p.startswith('local/projects/')),None)
            if not canonical:continue
            for target in group['paths']:
                if target not in ALLOWED:continue
                assert digest(safe(target))==digest(safe(canonical))==group['sha256']
                rows.append({'target':target,'canonical':canonical,'sha256':group['sha256'],'bytes':group['each_bytes']})
        assert len(rows)==len(ALLOWED)
        INDEX.parent.mkdir(parents=True,exist_ok=True)
        with INDEX.open('x',encoding='utf-8') as f:json.dump({'state':'planned','files':rows},f,indent=2)
    else:
        record=json.loads(INDEX.read_text('utf-8'));rows=record['files']
        assert {r['target'] for r in rows}==ALLOWED
        for r in rows:
            assert digest(safe(r['canonical']))==r['sha256']
            p=safe(r['target'])
            if p.exists():assert digest(p)==r['sha256']
        if mode=='restore':
            for r in rows:
                p=safe(r['target'])
                if not p.exists():p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(safe(r['canonical']),p)
                assert digest(p)==r['sha256']
        elif mode=='apply':
            for r in rows:
                p=safe(r['target'])
                if p.exists():p.unlink()
                assert not p.exists() and digest(safe(r['canonical']))==r['sha256']
        else:raise ValueError(mode)
        record['state']=mode
        INDEX.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'mode':mode,'files':len(rows),'bytes':sum(r['bytes'] for r in rows)}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['plan','apply','restore']);main(p.parse_args().mode)
