"""Concept-template unusable fuel assumption; independent of borrowed prop maps."""
import openmdao.api as om
import fastoad.api as oad
from fastga.models.weight.mass_breakdown.b_propulsion.constants import SERVICE_UNUSABLE_FUEL_MASS

UNUSABLE_PROVIDER='wingdesignhub.weight.unusable_fuel.capacity_fraction.v1'


@oad.RegisterSubmodel(SERVICE_UNUSABLE_FUEL_MASS,UNUSABLE_PROVIDER)
class UnusableFuel(om.ExplicitComponent):
    def initialize(self): self.options.declare('propulsion_id',default=None,allow_none=True)
    def setup(self):
        self.add_input('data:weight:aircraft:MFW',units='kg')
        self.add_input('settings:wingdesignhub:unusable_fuel_fraction',val=.02)
        self.add_output('data:weight:propulsion:unusable_fuel:mass',units='kg')
        self.declare_partials('*','*',method='exact')
    def compute(self,inputs,outputs):
        outputs['data:weight:propulsion:unusable_fuel:mass']=inputs['data:weight:aircraft:MFW']*inputs['settings:wingdesignhub:unusable_fuel_fraction']
    def compute_partials(self,inputs,partials):
        out='data:weight:propulsion:unusable_fuel:mass'
        partials[out,'data:weight:aircraft:MFW']=inputs['settings:wingdesignhub:unusable_fuel_fraction']
        partials[out,'settings:wingdesignhub:unusable_fuel_fraction']=inputs['data:weight:aircraft:MFW']
