"""Separate process: errors in a native extension do not crash the application."""
import json
from pathlib import Path
import openvsp as vsp
from wingdesignhub.model import WingCase


def main():
    case = WingCase.from_dict(json.loads(Path("input.json").read_text(encoding="utf-8")))
    vsp.ClearVSPModel()
    wing = vsp.AddGeom("WING")
    vsp.SetGeomName(wing, "SyntheticWing")
    vsp.SetDriverGroup(wing, 1, vsp.SPAN_WSECT_DRIVER, vsp.ROOTC_WSECT_DRIVER, vsp.TIPC_WSECT_DRIVER)
    for key, val in (("Span", case.span_m/2), ("Root_Chord", case.chord_m),
                     ("Tip_Chord", case.chord_m), ("Sweep", 0.), ("Twist", 0.)):
        vsp.SetParmVal(wing, key, "XSec_1", val)
    for i in (0, 1):
        vsp.SetParmVal(wing, "Camber", f"XSecCurve_{i}", 0.)
        vsp.SetParmVal(wing, "ThickChord", f"XSecCurve_{i}", .12)
    vsp.Update()
    vsp.WriteVSPFile("wing.vsp3", vsp.SET_ALL)
    result = {"version": vsp.GetVSPVersion(), "span_m": vsp.GetParmVal(wing, "TotalSpan", "WingGeom"),
              "area_m2": vsp.GetParmVal(wing, "TotalArea", "WingGeom"), "airfoil": "NACA0012"}
    errors = []
    mgr = vsp.ErrorMgrSingleton.getInstance()
    while mgr.GetNumTotalErrors():
        errors.append(mgr.PopLastError().m_ErrorString)
    if errors:
        raise RuntimeError("; ".join(errors))
    Path("geometry.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
