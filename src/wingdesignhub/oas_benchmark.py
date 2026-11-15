"""OAS 2.12.1 structural regression plus independent straight-tube checks.

The CRM setup is adapted from mdolab/OpenAeroStruct v2.12.1
tests/integration_tests/test_struct.py (Apache-2.0, see third-party notices).
Changes: explicit num_x default, result/provenance checks and analytic cases.
"""
from importlib.metadata import version
import json
from pathlib import Path
import numpy as np
import openmdao.api as om
from openaerostruct.meshing.mesh_generator import generate_mesh
from openaerostruct.structures.struct_groups import SpatialBeamAlone

REFERENCE_MASS_KG = 71088.4682399
REFERENCE_URL = "https://github.com/mdolab/OpenAeroStruct/blob/v2.12.1/tests/integration_tests/test_struct.py"


def base_surface(mesh):
    return {"name": "wing", "symmetry": True, "fem_model_type": "tube", "mesh": mesh,
            "E": 70e9, "G": 30e9, "yield": 500e6, "safety_factor": 2.5, "mrho": 3e3,
            "fem_origin": .35, "t_over_c_cp": np.array([.15]), "thickness_cp": np.full(3, .1),
            "wing_weight_ratio": 2., "struct_weight_relief": False, "distributed_fuel_weight": False,
            "exact_failure_constraint": False}


def build_problem(surface, loads):
    if loads.shape != (surface["mesh"].shape[1], 6) or not np.isfinite(loads).all():
        raise ValueError("结构载荷须为有限的 n×6 数组：Fx,Fy,Fz[N]，Mx,My,Mz[N·m]")
    problem = om.Problem(reports=False)
    group = SpatialBeamAlone(surface=surface)
    inputs = om.IndepVarComp()
    # OAS packs moments in columns 3:6, despite declaring the whole array as N.
    inputs.add_output("loads", val=loads, units="N")
    inputs.add_output("load_factor", val=1.)
    group.add_subsystem("indep_vars", inputs, promotes=["*"])
    problem.model.add_subsystem("wing", group)
    return problem


def official_case():
    mesh, _ = generate_mesh({"num_x": 3, "num_y": 7, "wing_type": "CRM", "symmetry": True, "num_twist_cp": 5})
    surface = base_surface(mesh)
    problem = build_problem(surface, np.full((mesh.shape[1], 6), 2e5))
    problem.driver = om.ScipyOptimizeDriver()
    problem.driver.options["disp"] = True
    problem.driver.options["tol"] = 1e-9
    problem.model.add_design_var("wing.thickness_cp", lower=.01, upper=.5, ref=.1)
    problem.model.add_constraint("wing.failure", upper=0.)
    problem.model.add_constraint("wing.thickness_intersects", upper=0.)
    problem.model.add_objective("wing.structural_mass", scaler=1e-5)
    try:
        problem.setup(); problem.run_model()
        initial = float(problem.get_val("wing.structural_mass").item())
        driver = problem.run_driver()
        mass = float(problem.get_val("wing.structural_mass").item())
        failure = float(problem.get_val("wing.failure").item())
        intersects = float(np.max(problem.get_val("wing.thickness_intersects")))
        error = abs(mass-REFERENCE_MASS_KG)/REFERENCE_MASS_KG
        result = {"mass_kg": mass, "initial_mass_kg": initial, "reference_mass_kg": REFERENCE_MASS_KG,
                  "mass_relative_error": error, "reference_rtol": 1e-8,
                  "driver_success": bool(driver.success), "failure_ks": failure,
                  "max_thickness_intersects_m": intersects,
                  "thickness_cp_m": problem.get_val("wing.thickness_cp").tolist(),
                  "half_mesh_nodes": int(mesh.shape[1]), "full_wing_mass": True, "wing_weight_ratio": 2.,
                  "load_columns": ["Fx_N", "Fy_N", "Fz_N", "Mx_Nm", "My_Nm", "Mz_Nm"],
                  "load_at_each_node": [2e5]*6, "reference": REFERENCE_URL}
        result["passed"] = bool(driver.success and np.isfinite([mass, failure, intersects]).all()
                                and error <= 1e-8 and failure <= 1e-6 and intersects <= 1e-8)
        return result
    finally:
        problem.cleanup()


def straight_tube(elements=10, force=100., length=2.):
    if type(elements) is not int or not 2 <= elements <= 100:
        raise ValueError("管梁单元数须为 2–100 整数")
    if not np.isfinite([force, length]).all() or length <= 0 or force == 0:
        raise ValueError("管梁长度须为正、载荷须有限且非零")
    mesh = np.zeros((2, elements+1, 3))
    mesh[:, :, 1] = np.linspace(-length, 0., elements+1)
    mesh[1, :, 0] = 1.
    radius, thickness, rho = .05, .005, 2700.
    surface = base_surface(mesh)
    surface.update(thickness_cp=np.array([thickness]), radius_cp=np.array([radius]),
                   wing_weight_ratio=1., mrho=rho)
    loads = np.zeros((elements+1, 6)); loads[0, 2] = force
    problem = build_problem(surface, loads)
    try:
        problem.setup(); problem.run_model()
        disp = problem.get_val("wing.disp")
        mass = float(problem.get_val("wing.structural_mass").item())
        stress = float(np.max(problem.get_val("wing.vonmises")))
        inertia = np.pi/4*(radius**4-(radius-thickness)**4)
        area = np.pi*(radius**2-(radius-thickness)**2)
        exact_tip = force*length**3/(3*surface["E"]*inertia)
        exact_mass = 2*rho*area*length  # symmetry=True: returned mass includes both halves
        # OAS tube stress uses average element curvature, so compare at root-element midpoint.
        exact_stress = abs(force)*(length-length/(2*elements))*radius/inertia
        errors = {"tip": abs(disp[0, 2]-exact_tip)/abs(exact_tip),
                  "mass": abs(mass-exact_mass)/exact_mass,
                  "stress_midpoint": abs(stress-exact_stress)/exact_stress}
        return {"elements": elements, "length_m": length, "force_n": force, "radius_m": radius,
                "thickness_m": thickness, "tip_displacement_m": float(disp[0, 2]), "analytical_tip_m": exact_tip,
                "full_mass_kg": mass, "analytical_full_mass_kg": exact_mass,
                "max_stress_pa": stress, "analytical_root_element_midpoint_stress_pa": exact_stress,
                "root_displacement_norm": float(np.linalg.norm(disp[-1])), "relative_errors": errors,
                "y_m": mesh[0, :, 1].tolist(), "displacement_z_m": disp[:, 2].tolist(),
                "passed": bool(all(v < .02 for v in errors.values()) and np.linalg.norm(disp[-1]) < 1e-9)}
    finally:
        problem.cleanup()


def run_benchmark(work):
    if version("openaerostruct") != "2.12.1":
        raise RuntimeError("官方回归值对应 OpenAeroStruct 2.12.1，升级后须重验")
    work = Path(work); work.mkdir(parents=True, exist_ok=True)
    mesh, _ = generate_mesh({"num_x":3,"num_y":7,"wing_type":"CRM","symmetry":True,"num_twist_cp":5})
    prescribed = {"official_surface":base_surface(mesh),"official_loads_N_Nm":np.full((mesh.shape[1],6),2e5),
                  "optimizer":{"name":"SLSQP","tol":1e-9,"thickness_bounds_m":[.01,.5]},
                  "analytic_cases":{"elements":[5,10,20],"length_m":2.,"radius_m":.05,"thickness_m":.005,
                                    "force_n":100.,"density_kg_m3":2700.,"double_load_n":200.,"longer_length_m":2.4}}
    (work/"input.json").write_text(json.dumps(prescribed,indent=2,default=lambda a:a.tolist(),allow_nan=False),encoding="utf-8")
    official = official_case()
    beam = [straight_tube(n) for n in (5, 10, 20)]
    doubled = straight_tube(10, force=200.)
    longer = straight_tube(10, length=2.4)
    ratios = {"double_load_tip": doubled["tip_displacement_m"]/beam[1]["tip_displacement_m"],
              "longer_tip": longer["tip_displacement_m"]/beam[1]["tip_displacement_m"]}
    passed = official["passed"] and all(c["passed"] for c in beam+[doubled,longer])
    passed = passed and np.isclose(ratios["double_load_tip"], 2., rtol=1e-8) and np.isclose(ratios["longer_tip"], 1.2**3, rtol=1e-8)
    result = {"status": "passed" if passed else "failed", "passed": bool(passed),
              "versions": {key: version(key) for key in ("openaerostruct", "openmdao", "numpy", "scipy")},
              "official": official, "straight_tube": beam, "double_load": doubled, "longer_beam": longer,
              "sensitivity_ratios": ratios, "evidence_level": "upstream_regression_and_analytical",
              "physical_validation_passed": False,
              "limits": ["线弹性管梁；不包含蒙皮、肋、连接件或屈曲", "官方 CRM 为合成六分量外载优化，不是本项目目标飞机",
                         "半翼网格，输出质量已计左右对称及 wing_weight_ratio；不得再次翻倍", "载荷来自规定输入；关闭自重和燃油卸载"]}
    (work/"summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return result
