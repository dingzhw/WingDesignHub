import pytest
pytest.importorskip('openaerostruct')
from wingdesignhub.oas_wingbox import run_benchmark


def test_official_wingbox_and_fuel_bookkeeping(tmp_path):
    r=run_benchmark(tmp_path);o=r['official_wingbox']
    assert r['passed'] and o['mass_relative_error']<1e-6
    assert o['half_wing_fuel_force_n']==pytest.approx(-122583.125)
    assert o['fuel_increment_force_n']==pytest.approx(-4903.325)
    assert not r['buckling_checked'] and not r['physical_validation_passed']
    assert (tmp_path/'input.json').exists()
