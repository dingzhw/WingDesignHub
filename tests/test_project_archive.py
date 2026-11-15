from dataclasses import replace
from io import BytesIO
from zipfile import ZipFile,ZIP_DEFLATED
import json
from pathlib import Path
import pytest
from wingdesignhub.requirements import DesignProject
from wingdesignhub.project_archive import build_bundle,read_bundle,save_bundle,list_saved,load_saved,digest,encoded
from wingdesignhub.sizing_service import run_sizing


def edit_zip(data,change):
    with ZipFile(BytesIO(data)) as z:files={n:z.read(n) for n in z.namelist()}
    change(files);stream=BytesIO()
    with ZipFile(stream,'w',ZIP_DEFLATED) as z:
        for n,b in files.items():z.writestr(n,b)
    return stream.getvalue()


def test_draft_saved_reopened_and_imported_without_runs(tmp_path):
    p=DesignProject();data=build_bundle(p,tmp_path);index=save_bundle(data,tmp_path)
    assert list_saved(tmp_path)==[index]
    q=load_saved(tmp_path,index['archive_id'])
    assert q['project']==p and not q['records'] and not q['migration_required']
    assert not (tmp_path/'runs').exists()
    other=tmp_path/'other';second=save_bundle(data,other)
    assert load_saved(other,second['archive_id'])['input']==p.to_dict()
    assert second['archive_id']!=index['archive_id']


def test_failed_calculation_is_archived_with_real_status_and_report(tmp_path,monkeypatch):
    def fail(*a,**k):raise TimeoutError('synthetic failure')
    monkeypatch.setattr('wingdesignhub.sizing_service.execute',fail)
    p=DesignProject().confirmed();r=run_sizing(p,tmp_path)
    assert r['status']=='failed'
    b=build_bundle(p,tmp_path,r);a=read_bundle(b)
    assert a['records'][0]['error']=='synthetic failure'
    assert b'failed' in a['files']['reports/report.html'] or '计算失败'.encode() in a['files']['reports/report.html']
    with pytest.raises(ValueError,match='其他定义'):build_bundle(replace(p,payload_kg=400).confirmed(),tmp_path,r)
    with pytest.raises(ValueError,match='尚未确认'):build_bundle(replace(p,confirmation_sha256=None),tmp_path,r)


@pytest.mark.parametrize('mutation',['member','path','version','missing'])
def test_corrupted_or_unsupported_archive_rejected(tmp_path,mutation):
    b=build_bundle(DesignProject(),tmp_path)
    def change(files):
        if mutation=='member':files['project.json']+=b' '
        elif mutation=='path':files['../outside.txt']=b'x'
        elif mutation=='missing':del files['project.json']
        else:
            m=json.loads(files['manifest.json']);m['bundle_schema']=99;files['manifest.json']=encoded(m)
    with pytest.raises(ValueError):read_bundle(edit_zip(b,change))
    assert not (tmp_path.parent/'outside.txt').exists()


def test_changed_source_is_historical_not_current(tmp_path,monkeypatch):
    monkeypatch.setattr('wingdesignhub.sizing_service.execute',lambda *a,**k:(_ for _ in ()).throw(TimeoutError('test')))
    r=run_sizing(DesignProject().confirmed(),tmp_path);b=build_bundle(DesignProject().confirmed(),tmp_path,r)
    def change(files):
        m=json.loads(files['manifest.json']);n=f"runs/{r['run_id']}/result.json"
        result=json.loads(files[n]);result['version']='0.0.0';files[n]=encoded(result);m['files'][n]=digest(files[n]);files['manifest.json']=encoded(m)
    a=read_bundle(edit_zip(b,change));assert not a['current_source_matches']


def test_archive_cli_uses_same_persistence_service(tmp_path,monkeypatch,capsys):
    from wingdesignhub.cli import main
    p=tmp_path/'input.json';p.write_bytes(encoded(DesignProject().to_dict()))
    monkeypatch.setattr('sys.argv',['wingdesignhub','archive-save','--root',str(tmp_path),'--input',str(p)])
    assert main()==0
    saved=json.loads(capsys.readouterr().out);assert load_saved(tmp_path,saved['archive_id'])['project']==DesignProject()
