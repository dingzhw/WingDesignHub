"""Physical CAD rotation about the quarter-chord span axis (x aft, z up)."""
import math
import numpy as np


def rotate_points(points,quarter_x,z,angle_deg):
    points=np.asarray(points,dtype=float);origin=np.array([quarter_x,0.,z])
    c,s=math.cos(math.radians(angle_deg)),math.sin(math.radians(angle_deg))
    rotation=np.array([[c,0,s],[0,1,0],[-s,0,c]])
    return (points-origin)@rotation.T+origin


def physical_origin(surface):
    return rotate_points(surface['sections'][0]['leading_edge_m'],surface['quarter_x_m'],surface['z_m'],surface['incidence_deg']).tolist()
