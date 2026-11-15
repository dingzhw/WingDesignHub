"""Furniture provider adapted from FAST-GA; (C) 2025 ONERA & ISAE-SUPAERO.

GPL-3.0-or-later. The original duplicate half-input sum is replaced by an identity.
"""
import numpy as np
import fastoad.api as oad
import openmdao.api as om
from fastga.models.weight.mass_breakdown.constants import SERVICE_FURNITURE_MASS
from fastga.models.weight.mass_breakdown.d_furniture.constants import SERVICE_SEATS_MASS

SEATS = "data:weight:furniture:passenger_seats:mass"
FURNITURE = "data:weight:furniture:mass"
PROVIDER = "wingdesignhub.submodel.weight.furniture.identity.v1"


class FurnitureMass(om.ExplicitComponent):
    def setup(self):
        self.add_input(SEATS, val=np.nan, units="kg")
        self.add_output(FURNITURE, units="kg")
        self.declare_partials(FURNITURE, SEATS, val=1.)

    def compute(self, inputs, outputs):
        outputs[FURNITURE] = inputs[SEATS]


@oad.RegisterSubmodel(SERVICE_FURNITURE_MASS, PROVIDER)
class FurnitureWeight(om.Group):
    def setup(self):
        self.add_subsystem("seats_weight", oad.RegisterSubmodel.get_submodel(SERVICE_SEATS_MASS), promotes=["*"])
        self.add_subsystem("furniture_weight_sum", FurnitureMass(), promotes=["*"])
