from copy import deepcopy
from dataclasses import replace
import json
import math
import numpy as np
import pytest
from wingdesignhub.layout import default_layout,validate_layout,component_ledger,fuel_station
from wingdesignhub.requirements import DesignProject
from wingdesignhub.sizing_physics import geometry
from wingdesignhub.incidence import rotate_points


def sample():
    p=DesignProject();p=replace(p,sizing=replace(p.sizing,layout=default_layout())).confirmed()
    g=geometry(1200,100,p)
    leaves={'airframe:wing':100.,'airframe:fuselage':180.,'airframe:horizontal_tail':20.,
            'propulsion:engine':180.,'propulsion:fuel_lines':15.,'propulsion:unusable_fuel':3.,
            'systems:avionics':40.,'furniture:passenger_seats':30.}
    cats={'airframe':300.,'propulsion':195.,'unusable_fuel':3.,'systems':40.,'furniture':30.}
    detail={'data:weight:'+k+':mass':v for k,v in leaves.items()}
    detail.update({'data:weight:'+k+':mass':v for k,v in cats.items() if k!='unusable_fuel'})
    return p,g,{'owe_kg':sum(cats.values()),'categories_kg':cats,'components_kg':detail}


def test_leaf_mass_and_fuel_moment_conserved_without_category_double_counting():
    p,g,w=sample();m={'takeoff_fuel_kg':100.,'trip_fuel_from_takeoff_kg':60.}
    r=component_ledger(w,g,p,m)
    assert r['loaded_mass_kg']==pytest.approx(w['owe_kg']+p.payload_kg+100)
    moment=sum(x['mass_kg']*x['x_m'] for x in r['rows'])
    assert r['end_cg_x_m']*(r['loaded_mass_kg']-60)==pytest.approx(moment-60*fuel_station(g,p))
    assert sum(x['mass_kg'] for x in r['rows'] if x['category']=='payload')==p.payload_kg
    bad=deepcopy(w);bad['components_kg']['data:weight:airframe:wing:mass']+=1
    with pytest.raises(ValueError,match='合计'):component_ledger(bad,g,p,m)


def test_payload_and_tank_positions_are_independent_and_preserve_total_mass():
    p,g,w=sample();m={'takeoff_fuel_kg':100.,'trip_fuel_from_takeoff_kg':60.}
    old=component_ledger(w,g,p,m);layout=deepcopy(p.sizing.layout)
    layout['stations_fraction']['fuel']+=.1
    q=replace(p,sizing=replace(p.sizing,layout=layout))
    new=component_ledger(w,g,q,m)
    # Fuel lines and unusable fuel follow the configured tank, once each.
    delta=(100+15+3)*.1*g['fuselage_length_m']
    assert (new['cg_x_m']-old['cg_x_m'])*old['loaded_mass_kg']==pytest.approx(delta)
    assert old['loaded_mass_kg']==new['loaded_mass_kg']
    assert p.definition_hash()!=q.definition_hash()


@pytest.mark.parametrize('change',['nan','fractions','unknown','angle','source'])
def test_invalid_layout_rejected(change):
    x=default_layout()
    if change=='nan':x['stations_fraction']['fuel']=float('nan')
    elif change=='fractions':x['payload_fractions']['baggage']=.4
    elif change=='unknown':x['hidden_cg_target']=.25
    elif change=='angle':x['tail_incidence_deg']=4
    else:x['source']=''
    with pytest.raises(ValueError):validate_layout(x)


def test_absent_layout_keeps_old_definition_and_explicit_layout_roundtrips():
    p=DesignProject().confirmed();raw=p.to_dict()
    assert 'layout' not in raw['sizing']
    assert DesignProject.from_dict(json.loads(json.dumps(raw))).definition_hash()==p.definition_hash()
    q,g,w=sample();assert DesignProject.from_dict(q.to_dict())==q


def test_physical_incidence_preserves_quarter_chord_and_chord_length():
    points=np.array([[2.5,1.,0.],[4.5,1.,0.]])
    rotated=rotate_points(points,3.,0.,2.)
    np.testing.assert_allclose(rotate_points(rotated,3.,0.,-2.),points,atol=1e-14)
    assert np.linalg.norm(rotated[1]-rotated[0])==pytest.approx(2.)
    np.testing.assert_allclose(rotated[0]+.25*(rotated[1]-rotated[0]),[3.,1.,0.],atol=1e-14)
    assert rotated[0,2]>0 and rotated[1,2]<0


def test_flight_state_uses_independent_fuel_station_and_describes_the_actual_ledger():
    from wingdesignhub.flight_state import make_flight_state
    p,g,w=sample();p.sizing.layout['stations_fraction']['fuel']=.5
    m={'takeoff_fuel_kg':100.,'trip_fuel_from_takeoff_kg':60.,'takeoff_roll_fuel_kg':2.,
       'segments':[{'fuel_kg':58.}],'reserve_fuel_kg':35.,'taxi_in_fuel_kg':5.}
    cg=component_ledger(w,g,p,m);s={'cg':cg,'mission':m,'geometry':g,
        'required_loaded_mass_kg':cg['loaded_mass_kg'],'design_mtow_kg':cg['loaded_mass_kg']}
    end=make_flight_state(s,'mission_end')
    assert end['cg_geometry_m'][0]==pytest.approx(cg['end_cg_x_m'])
    assert end['remaining_usable_fuel_kg']==40.
    assert 'fuel at declared station' in end['source'] and 'wing quarter chord' not in end['source']
    explicit=make_flight_state(s,'explicit',900.,3.,'test measured CG')
    assert explicit['source']=='test measured CG'
