"""Correct reserve Jacobian; formula/API from FAST-GA, GPL-3.0-or-later.

Upstream (C) 2022 ONERA & ISAE-SUPAERO. Primal function is unchanged.
"""
import fastoad.api as oad
from fastga.models.performances.mission.constants import SUBMODEL_RESERVES
from fastga.models.performances.mission.mission_components.reserve import ComputeReserve, MIN_CRUISE_DURATION

RESERVE_PROVIDER = 'wingdesignhub.submodel.mission.reserve.correct_derivatives.v1'
PREFIX = 'data:mission:sizing:main_route:'
FUEL = PREFIX+'cruise:fuel'
TIME = PREFIX+'cruise:duration'
RESERVE_TIME = PREFIX+'reserve:duration'
FACTOR = 'settings:mission:sizing:main_route:reserve:k_factor'
OUTPUT = PREFIX+'reserve:fuel'


@oad.RegisterSubmodel(SUBMODEL_RESERVES, RESERVE_PROVIDER)
class CorrectReserve(ComputeReserve):
    def compute_partials(self, inputs, partials):
        m, t, r, k = (inputs[n] for n in (FUEL, TIME, RESERVE_TIME, FACTOR))
        denominator = max(MIN_CRUISE_DURATION, t)
        partials[OUTPUT, FUEL] = r*k/denominator
        partials[OUTPUT, RESERVE_TIME] = m*k/denominator
        partials[OUTPUT, FACTOR] = m*r/denominator
        # Derivative is undefined at exactly the clamp kink; use the lower-side convention.
        partials[OUTPUT, TIME] = -m*r*k/denominator**2 if t > MIN_CRUISE_DURATION else 0.
