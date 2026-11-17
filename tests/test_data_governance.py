import json
import sys
from pathlib import Path
import pytest
from wingdesignhub.adapters import execute
from wingdesignhub.project_archive import build_bundle,read_bundle,save_bundle,load_saved
from wingdesignhub.requirements import DesignProject


def test_bounded_output_normal_timeout_and_flood(tmp_path):
    for name,code,timeout,expected in [
        ('normal','print("hello")',5,None),
        ('flood','import os\nwhile True: os.write(1,b"NaN "*16384)',5,'容量'),
        ('timeout','import time; time.sleep(10)',.2,'超过')]:
        work=tmp_path/name;work.mkdir()
        args=[sys.executable,'-c',code]
        if expected:
            with pytest.raises(RuntimeError,match=expected):execute(args,work,timeout=timeout,output_limit=65536)
        else:assert execute(args,work,timeout=timeout,output_limit=65536).strip()=='hello'
        m=json.loads((work/'command.json').read_text())
        assert (work/'stdout.log').stat().st_size<=65536
        assert m['returncode'] is not None
        assert m['output_capture']['status']=={'normal':'completed','flood':'output_limit','timeout':'timeout'}[name]


def test_portable_draft_deduplicates_save(tmp_path):
    p=DesignProject()
    b=build_bundle(p,tmp_path,profile='portable')
    first=save_bundle(b,tmp_path)
    second=save_bundle(build_bundle(p,tmp_path,profile='portable'),tmp_path)
    assert first==second
    assert load_saved(tmp_path,first['archive_id'])['input']==p.to_dict()
    assert read_bundle(build_bundle(p,tmp_path))['manifest']['bundle_schema']==1


def test_detached_evidence_restricted():
    from wingdesignhub.archive_evidence import EvidenceFiles,check_packaged_native
    prefix='runs/'+'a'*32+'/'
    h='b'*64
    f=EvidenceFiles({prefix+'native_manifest.json':json.dumps({'archive_sha256':h}).encode()}, {prefix+'native_evidence.zip':h})
    assert check_packaged_native(f,prefix)=='detached_not_verified'
    with pytest.raises(ValueError):EvidenceFiles({}, {prefix+'summary.json':h})
    with pytest.raises(ValueError):check_packaged_native(EvidenceFiles({},{}),prefix)


def test_native_content_deduplication(tmp_path):
    from wingdesignhub.feedback_evidence import pack_native,check_native
    from zipfile import ZipFile
    work=tmp_path/'work';(work/'native'/'nested').mkdir(parents=True)
    (work/'native'/'a.txt').write_bytes(b'original evidence'*100)
    (work/'native'/'nested'/'b.txt').write_bytes(b'original evidence'*100)
    m=pack_native(work)
    assert len(m['files'])==2
    with ZipFile(work/'native_evidence.zip') as z:
        assert len(z.namelist())==1
        assert all(z.read('objects/'+h)==(work/'native'/n).read_bytes() for n,h in m['files'].items())
    check_native((work/'native_evidence.zip').read_bytes(),m)
    m['files']['../escape']=next(iter(m['files'].values()))
    with pytest.raises(ValueError):check_native((work/'native_evidence.zip').read_bytes(),m)


def test_light_result_keeps_non_native_integrity(tmp_path):
    import hashlib
    from wingdesignhub.service import get_results
    rid='a'*32;work=tmp_path/'runs'/rid;work.mkdir(parents=True)
    (work/'summary.json').write_bytes(b'{}')
    (work/'result.json').write_text(json.dumps({'artifact_hashes':{
        'summary.json':hashlib.sha256(b'{}').hexdigest(),'native_evidence.zip':'b'*64}}))
    assert get_results(tmp_path,rid,verify_native=False)
    with pytest.raises(ValueError):get_results(tmp_path,rid)
    (work/'summary.json').write_bytes(b'{"corrupt":true}')
    with pytest.raises(ValueError):get_results(tmp_path,rid,verify_native=False)
