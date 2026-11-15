import pytest
pytest.importorskip("openaerostruct")
from wingdesignhub.oas_benchmark import official_case, straight_tube


def test_upstream_structural_optimization():
    r=official_case()
    assert r["passed"] and r["driver_success"]
    assert r["mass_relative_error"]<1e-8


def test_tube_independent_analytics_and_signed_load_response():
    base=straight_tube(10)
    negative=straight_tube(20,force=-200.)
    longer=straight_tube(10,length=2.4)
    assert all(r["passed"] for r in (base,negative,longer))
    assert max(base["relative_errors"].values())<1e-8
    assert negative["tip_displacement_m"]/base["tip_displacement_m"]==pytest.approx(-2.)
    assert longer["tip_displacement_m"]/base["tip_displacement_m"]==pytest.approx(1.2**3)
    assert negative["full_mass_kg"]==pytest.approx(base["full_mass_kg"])


def test_tube_bad_input_rejected():
    for kwargs in ({"elements":True},{"force":float('nan')},{"length":0.}):
        with pytest.raises(ValueError):straight_tube(**kwargs)
