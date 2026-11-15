import json
from pathlib import Path
import pytest
from wingdesignhub.calculix_benchmark import parse_tip, beam_deck, run_beam
from wingdesignhub.adapters import tool_paths


def test_displacement_parser_requires_single_finite_displacement():
    assert parse_tip("displacements (vx,vy,vz)\n 41 0 4.55D-04 0\n", 41) == .000455
    for text in ("41 0 1 0", "displacements\n41 0 nan 0", "displacements\n41 0 1 0\n41 0 2 0"):
        with pytest.raises(ValueError):
            parse_tip(text, 41)


def test_deck_connectivity_and_clamped_rotations():
    deck = beam_deck(2)
    assert "1,1,2,3\n2,3,4,5" in deck
    assert "*BOUNDARY\n1,1,6" in deck
    assert "*CLOAD\n5,2,100.0" in deck
    for n in (0, 1.5, True):
        with pytest.raises(ValueError):
            beam_deck(n)


def test_solver_version_is_verified_not_assumed(tmp_path, monkeypatch):
    monkeypatch.setattr("wingdesignhub.calculix_benchmark.execute", lambda *a, **k: "CalculiX Version 2.10")
    with pytest.raises(ValueError, match="2.10"):
        run_beam("unused", tmp_path/"old")


def test_solver_config_overrides_bundle_and_blank_legacy_uses_bundle(tmp_path):
    bundled = tmp_path/".runtime/calculix-2.23/CalculiX-2.23.0-win-x64/bin/ccx.exe"
    bundled.parent.mkdir(parents=True); bundled.touch()
    config = tmp_path/"local/tools.json"; config.parent.mkdir()
    config.write_text(json.dumps({"calculix": ""}))
    assert Path(tool_paths(tmp_path)["calculix"]) == bundled
    config.write_text(json.dumps({"calculix": "explicit/ccx.exe"}))
    assert tool_paths(tmp_path)["calculix"] == "explicit/ccx.exe"


@pytest.mark.parametrize("passed,status", [(True, "executed_with_limits"), (False, "failed")])
def test_reference_status_survives_service_and_integrity_check(tmp_path, monkeypatch, passed, status):
    from wingdesignhub.service import run_reference, get_results
    scripts = tmp_path/"scripts"; scripts.mkdir()
    (scripts/"validate_fastga.py").write_text("# test worker")
    def execute_stub(args, work, **kwargs):
        (work/"summary.json").write_text(json.dumps({"passed": passed, "status": status}))
    monkeypatch.setattr("wingdesignhub.service.execute", execute_stub)
    result = run_reference(tmp_path, "fastga")
    assert result["status"] == status
    assert get_results(tmp_path, result["run_id"])["status"] == status
    assert "fastga_plugins/furniture.py" in result["source_hashes"]
