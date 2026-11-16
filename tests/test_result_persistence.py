"""Brief Windows sharing locks must not discard a completed engineering result."""
from pathlib import Path
import json
import pytest
from wingdesignhub.service import write_json


@pytest.mark.parametrize('code',[5,32,33])
def test_atomic_result_retries_sharing_lock_without_partial_target(tmp_path,monkeypatch,code):
    path=tmp_path/'result.json';path.write_text('{"old": true}',encoding='utf-8')
    original=Path.replace;attempts=[];delays=[]
    def replace(source,target):
        attempts.append(1)
        if len(attempts)<3:
            assert json.loads(path.read_text('utf-8'))=={'old':True}
            error=PermissionError('temporary sharing lock');error.winerror=code;raise error
        return original(source,target)
    monkeypatch.setattr(Path,'replace',replace)
    monkeypatch.setattr('wingdesignhub.service.sleep',delays.append)
    write_json(path,{'result':'complete','fuel':80.})
    assert json.loads(path.read_text('utf-8'))=={'result':'complete','fuel':80.}
    assert len(attempts)==3 and delays==[.05,.1] and not path.with_suffix('.json.tmp').exists()


def test_persistent_denial_is_bounded_and_preserves_old_result(tmp_path,monkeypatch):
    path=tmp_path/'result.json';old=b'{"old":true}';path.write_bytes(old);attempts=[];delays=[]
    def deny(*a):
        attempts.append(1);error=PermissionError('persistent denial');error.winerror=5;raise error
    monkeypatch.setattr(Path,'replace',deny);monkeypatch.setattr('wingdesignhub.service.sleep',delays.append)
    with pytest.raises(PermissionError):write_json(path,{'new':True})
    assert len(attempts)==5 and sum(delays)==pytest.approx(.75) and path.read_bytes()==old
    assert json.loads(path.with_suffix('.json.tmp').read_text('utf-8'))=={'new':True}


def test_other_permission_error_is_not_retried(tmp_path,monkeypatch):
    calls=[]
    def deny(*a):calls.append(1);raise PermissionError('not a Windows sharing error')
    monkeypatch.setattr(Path,'replace',deny)
    with pytest.raises(PermissionError):write_json(tmp_path/'result.json',{})
    assert calls==[1]
