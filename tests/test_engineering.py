import json
import numpy as np
import pytest
from wingdesignhub.model import WingCase
from wingdesignhub.mechanics import geometry_to_body, map_loads, resultant, solve_beam, uniform_beam
from wingdesignhub.service import run_analysis, get_results, compare_designs


@pytest.mark.parametrize("key,value", [("span_m", 0), ("alpha_deg", 20), ("density_kg_m3", float('nan')),
    ("speed_m_s", float('inf')), ("beam_elements", 2.2), ("aero_panels", True), ("span_m", "10")])
def test_bad_inputs(key, value):
    with pytest.raises(ValueError):
        WingCase.from_dict({key: value})


def test_schema_unknown():
    with pytest.raises(ValueError):
        WingCase.from_dict({"span_ft": 10})


def test_axes_and_moment_covariance():
    r, f = np.array([2., 3., 4.]), np.array([10., -20., 30.])
    np.testing.assert_allclose(geometry_to_body(geometry_to_body(r)), r)
    np.testing.assert_allclose(np.cross(geometry_to_body(r), geometry_to_body(f)), geometry_to_body(np.cross(r, f)))


def test_mapping_conserves_six_components_with_offsets_and_couples():
    p = np.array([[1., .2, .1], [-2., 1.4, .7], [3., 2., -1.]])
    f = np.array([[5., -3., 12.], [-2., 4., -7.], [2., -1., 6.]])
    m = np.array([[1., 2., 3.], [3., 1., 4.], [-2., 0., 1.]])
    n = np.array([[0., 0., 0.], [0., 1., 0.], [0., 2., 0.]])
    nf, nm = map_loads(p, f, n, m)
    np.testing.assert_allclose(resultant(p, f, m, origin=(2, -1, 3)), resultant(n, nf, nm, origin=(2, -1, 3)), atol=1e-12)
    with pytest.raises(ValueError):
        map_loads([[0, 3, 0]], [[0, 0, 1]], n)


@pytest.mark.parametrize("elements", [2, 10, 40])
def test_beam_uniform_exact_displacement_and_reactions(elements):
    L, E, I, w = 5., 70e9, 8e-6, 500.
    r = uniform_beam(L, E, I, w, elements)
    y = np.array(r["y_m"])
    exact = w*y*y*(6*L*L - 4*L*y + y*y)/(24*E*I)
    np.testing.assert_allclose(r["displacement_m"], exact, rtol=1e-7, atol=1e-12)
    assert r["root_force_n"] == pytest.approx(-w*L, rel=1e-7)
    assert r["root_moment_nm"] == pytest.approx(-w*L*L/2, rel=1e-7)


def test_tip_force_and_tip_couple():
    f, m = np.zeros(11), np.zeros(11)
    f[-1], m[-1] = 100., 30.
    r = solve_beam(2., 70e9, 1e-5, f, m)
    assert r["tip_displacement_m"] == pytest.approx(100*2**3/(3*70e9*1e-5)+30*2**2/(2*70e9*1e-5), rel=1e-8)


def test_run_provenance_and_tamper_detection(tmp_path):
    r = run_analysis(WingCase(), tmp_path)
    assert r["status"] == "success"
    assert get_results(tmp_path, r["run_id"]) == r
    p = tmp_path/"runs"/r["run_id"]/"input.json"
    p.write_text("{}")
    with pytest.raises(ValueError, match="完整性"):
        get_results(tmp_path, r["run_id"])


def test_parameter_change_and_comparison(tmp_path):
    a = run_analysis(WingCase(), tmp_path)
    b = run_analysis(WingCase(span_m=12.), tmp_path)
    rows = compare_designs([a, b])
    assert rows[1]["tip_displacement_m"]/rows[0]["tip_displacement_m"] == pytest.approx(1.2**4, rel=1e-7)
    assert a["input_hash"] != b["input_hash"]


def test_solver_missing_and_out_of_domain_are_failed_runs(tmp_path):
    (tmp_path/"local").mkdir()
    (tmp_path/"local/tools.json").write_text(json.dumps({"avl": str(tmp_path/"absent.exe")}))
    result = run_analysis(WingCase(), tmp_path, "avl")
    assert result["status"] == "failed"
    assert (tmp_path/"runs"/result["run_id"]/"error.log").exists()
    assert run_analysis(WingCase(second_moment_m4=1e-10), tmp_path)["status"] == "failed"
