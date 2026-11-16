"""Method/data identity is invariant to design sizing and runtime directories."""
import hashlib,json


def model_identity(mass_sources,engine,propeller,aero,geometry_versions):
    engine=dict(engine);engine.pop('equivalent_volume_m3',None)
    evidence={'schema':1,'mass_sources':mass_sources,'engine_method':engine,
              'propeller_solver':propeller['metadata'],
              'propeller_airfoil_sha256':hashlib.sha256(json.dumps(propeller['airfoil'],sort_keys=True).encode()).hexdigest(),
              'aero_solver':{k:aero[k] for k in ('avl_sha256','xfoil_sha256')},
              'geometry_versions':geometry_versions}
    return evidence,hashlib.sha256(json.dumps(evidence,sort_keys=True).encode()).hexdigest()
