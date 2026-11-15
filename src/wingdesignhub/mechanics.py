"""SI mechanics; geometric axes x aft, y right, z up. No material allowables."""
import numpy as np


def geometry_to_body(vector):
    """Proper rotation, determinant +1; valid for forces and axial moments."""
    return np.asarray(vector, dtype=float) * np.array([-1., 1., -1.])


def resultant(positions, forces, moments=None, origin=(0., 0., 0.)):
    p, f = np.asarray(positions, float), np.asarray(forces, float)
    m = np.zeros_like(f) if moments is None else np.asarray(moments, float)
    if p.shape != f.shape or m.shape != f.shape or p.ndim != 2 or p.shape[1] != 3:
        raise ValueError("载荷必须为相同长度的 N×3 坐标、力和力矩")
    if not all(np.isfinite(a).all() for a in (p, f, m)):
        raise ValueError("载荷包含非有限值")
    return f.sum(axis=0), (np.cross(p - origin, f) + m).sum(axis=0)


def map_loads(positions, forces, nodes, moments=None):
    """Span interpolation plus a nodal couple conserves all six resultant components.

    Used for straight span-ordered beam stations; out-of-range points are rejected.
    """
    p, f, n = map(lambda a: np.asarray(a, float), (positions, forces, nodes))
    m = np.zeros_like(f) if moments is None else np.asarray(moments, float)
    resultant(p, f, m)
    if n.ndim != 2 or n.shape[1] != 3 or len(n) < 2 or not np.isfinite(n).all():
        raise ValueError("结构节点必须为有限的 N×3 数组")
    y = n[:, 1]
    if np.any(np.diff(y) <= 0):
        raise ValueError("结构节点必须沿展向严格递增")
    if np.any(p[:, 1] < y[0] - 1e-10) or np.any(p[:, 1] > y[-1] + 1e-10):
        raise ValueError("气动载荷超出结构节点范围")
    nf, nm = np.zeros_like(n), np.zeros_like(n)
    for pos, force, moment in zip(p, f, m):
        j = int(np.clip(np.searchsorted(y, pos[1]) - 1, 0, len(y) - 2))
        t = float(np.clip((pos[1] - y[j]) / (y[j+1] - y[j]), 0., 1.))
        for k, w in ((j, 1-t), (j+1, t)):
            nf[k] += w * force
            nm[k] += w * (moment + np.cross(pos - n[k], force))
    return nf, nm


def solve_beam(length, elastic_modulus, inertia, nodal_fz, nodal_mx=None):
    """Euler–Bernoulli uniform cantilever, w along +z; rotation about +x.

    Solves nodal forces and couples. Clamp at y=0. Small elastic deflections only.
    """
    force = np.asarray(nodal_fz, float)
    moment = np.zeros_like(force) if nodal_mx is None else np.asarray(nodal_mx, float)
    if force.ndim != 1 or len(force) < 3 or moment.shape != force.shape:
        raise ValueError("至少需要三个节点及等长的力和力矩")
    if min(length, elastic_modulus, inertia) <= 0 or not np.isfinite([length, elastic_modulus, inertia]).all():
        raise ValueError("梁参数必须为正有限值")
    if not np.isfinite(force).all() or not np.isfinite(moment).all():
        raise ValueError("节点载荷必须有限")
    count = len(force); h = length / (count - 1)
    k = np.zeros((2*count, 2*count))
    ke = elastic_modulus*inertia/h**3 * np.array([
        [12, 6*h, -12, 6*h], [6*h, 4*h*h, -6*h, 2*h*h],
        [-12, -6*h, 12, -6*h], [6*h, 2*h*h, -6*h, 4*h*h]])
    for i in range(count-1):
        k[2*i:2*i+4, 2*i:2*i+4] += ke
    rhs = np.empty(2*count); rhs[0::2] = force; rhs[1::2] = moment
    u = np.zeros(2*count); u[2:] = np.linalg.solve(k[2:, 2:], rhs[2:])
    reactions = k @ u - rhs
    return {"y_m": np.linspace(0, length, count).tolist(), "displacement_m": u[0::2].tolist(),
            "rotation_rad": u[1::2].tolist(), "root_force_n": float(reactions[0]),
            "root_moment_nm": float(reactions[1]), "tip_displacement_m": float(u[-2])}


def uniform_beam(length, elastic_modulus, inertia, load, elements):
    """Consistent Euler–Bernoulli load vector (including nodal couples)."""
    h = length/elements
    f = np.full(elements+1, load*h); f[[0, -1]] *= .5
    m = np.zeros(elements+1); m[0], m[-1] = load*h*h/12, -load*h*h/12
    r = solve_beam(length, elastic_modulus, inertia, f, m)
    exact = load * length**4 / (8*elastic_modulus*inertia)
    r.update(analytical_tip_m=exact, tip_absolute_error_m=abs(r["tip_displacement_m"]-exact),
             tip_relative_error=abs(r["tip_displacement_m"]-exact)/abs(exact) if exact else 0.)
    return r
