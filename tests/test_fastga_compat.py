from types import SimpleNamespace
import warnings
import numpy as np
import pytest

pytest.importorskip("fastga")
import openmdao.api as om
import fastoad.api as oad
from wingdesignhub.fastga_compat import FurnitureMass, compatibility, save_csv, SEATS, FURNITURE, SERVICE_FURNITURE_MASS, PROVIDER
from fastga.models.performances.mission.dynamic_equilibrium import DynamicEquilibrium


@pytest.mark.parametrize("mass", [0., 80., 200.])
def test_identity_mass_and_derivative_against_independent_fd(mass):
    problem = om.Problem(reports=False)
    problem.model.add_subsystem("furniture", FurnitureMass(), promotes=["*"])
    problem.setup(); problem.set_val(SEATS, mass, units="kg"); problem.run_model()
    assert problem.get_val(FURNITURE).item() == mass
    check = problem.check_partials(out_stream=None, method="fd", form="central")["furniture"][(FURNITURE, SEATS)]
    assert check["J_fwd"].item() == 1.
    assert check["J_fd"].item() == pytest.approx(1., abs=1e-7)
    problem.cleanup()


def test_upstream_duplicate_input_reproduces_wrong_derivative():
    component = om.AddSubtractComp()
    with pytest.warns(Warning, match="Duplicate inputs"):
        component.add_equation("furniture", ["seats", "seats"], scaling_factors=[.5, .5], units="kg")
    problem = om.Problem(reports=False); problem.model.add_subsystem("old", component)
    problem.setup()
    problem.set_val("old.seats", 80.); problem.run_model()
    assert problem.get_val("old.furniture").item() == 80.
    derivative = problem.compute_totals(of=["old.furniture"], wrt=["old.seats"])
    assert derivative[("old.furniture", "old.seats")].item() == .5
    samples = []
    for mass in (79.99, 80.01):
        problem.set_val("old.seats", mass); problem.run_model()
        samples.append(problem.get_val("old.furniture").item())
    assert (samples[1]-samples[0])/.02 == pytest.approx(1., abs=1e-9)
    problem.cleanup()


def test_csv_compatibility_preserves_values_units_and_append(tmp_path):
    old = tmp_path/"old.csv"; new = tmp_path/"new.csv"
    points = [{"time": np.array([1.]), "altitude": np.array([20.]), "name": "climb"},
              {"time": np.array([2.]), "altitude": np.array([30.]), "name": "climb"}]
    for _ in range(2):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            DynamicEquilibrium.save_csv(SimpleNamespace(flight_points=points, options={"out_file": str(old)}))
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            save_csv(SimpleNamespace(flight_points=points, options={"out_file": str(new)}))
        assert not captured
        assert old.read_bytes() == new.read_bytes()


def test_context_restores_upstream_after_failure():
    original = DynamicEquilibrium.save_csv
    models = dict(oad.RegisterSubmodel.active_models)
    with pytest.raises(RuntimeError, match="deliberate"):
        with compatibility():
            assert DynamicEquilibrium.save_csv is save_csv
            assert oad.RegisterSubmodel.active_models[SERVICE_FURNITURE_MASS] == PROVIDER
            raise RuntimeError("deliberate")
    assert DynamicEquilibrium.save_csv is original
    assert models == oad.RegisterSubmodel.active_models


def test_final_domain_audit_uses_installed_tables():
    from wingdesignhub.fastga_diagnostics import final_domain_checks
    values = {"data:geometry:horizontal_tail:elevator_chord_ratio": .34,
              "data:geometry:horizontal_tail:area": 2.624,
              "data:geometry:vertical_tail:area": 1.,
              "data:mission:sizing:takeoff:elevator_angle": -20.}
    problem = SimpleNamespace(get_val=lambda name: np.array([values[name]]))
    checks = final_domain_checks(problem)
    assert not any(check["within_range"] for check in checks)
    assert checks[0]["upper"] == .3
    assert checks[1]["upper"] == pytest.approx(1.975076546233926)
    assert checks[2]["lower"] == -.08
    values["data:geometry:horizontal_tail:elevator_chord_ratio"] = .2
    values["data:geometry:horizontal_tail:area"] = 1.
    values["data:mission:sizing:takeoff:elevator_angle"] = 20.
    assert all(check["within_range"] for check in final_domain_checks(problem))
