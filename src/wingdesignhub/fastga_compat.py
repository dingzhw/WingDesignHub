"""Scoped FAST-GA 1.4.0 adapters; used only in an isolated reference worker.

Furniture group and CSV writer adapted from FAST-OAD_CS23, copyright
(C) 2025 ONERA & ISAE-SUPAERO, GPL-3.0-or-later. See docs/THIRD_PARTY.md.
No installed package is edited. Do not use this context concurrently in threads.
"""
from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path
import numpy as np
import pandas as pd
import fastoad.api as oad
from fastoad.module_management._plugins import FastoadLoader

# Initialize upstream registry before importing decorated upstream model packages.
# Loading an individual FAST-GA subpackage first can cause a loader import cycle.
FastoadLoader()
from fastga.models.performances.mission.dynamic_equilibrium import DynamicEquilibrium
from .fastga_plugins.furniture import FurnitureMass, SEATS, FURNITURE, PROVIDER, SERVICE_FURNITURE_MASS


def save_csv(self):
    """Preserve upstream CSV values, units and append indexing; replace applymap."""
    def as_scalar(value):
        return value.item() if isinstance(value, np.ndarray) else value

    frame = pd.DataFrame(self.flight_points).map(as_scalar)
    frame.rename(columns={name: f"{name} [{unit}]" for name, unit in oad.FlightPoint.get_units().items()}, inplace=True)
    out = Path(self.options["out_file"])
    if not out.exists():
        frame.index = range(len(frame))
        out.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(out)
    else:
        existing = pd.read_csv(out)
        if "Unnamed: 0" in existing.columns:
            existing = existing.drop("Unnamed: 0", axis=1)
        # Keep 1.4.0 indexing for byte-equivalent compatibility (including its overlap).
        frame.index = range(max(existing.index), max(existing.index)+len(frame))
        pd.concat([existing, frame]).to_csv(out)


@contextmanager
def compatibility():
    if version("fast-oad-cs23") != "1.4.0":
        raise RuntimeError("FAST-GA 兼容层仅核验过 1.4.0；升级后须重新验证")
    FastoadLoader().explore_folder("wingdesignhub.fastga_plugins", is_package=True)
    if PROVIDER not in oad.RegisterSubmodel.get_provider_ids(SERVICE_FURNITURE_MASS):
        raise RuntimeError("家具质量插件未成功注册")
    models = dict(oad.RegisterSubmodel.active_models)
    original = DynamicEquilibrium.save_csv
    oad.RegisterSubmodel.active_models[SERVICE_FURNITURE_MASS] = PROVIDER
    DynamicEquilibrium.save_csv = save_csv
    try:
        yield
    finally:
        DynamicEquilibrium.save_csv = original
        oad.RegisterSubmodel.active_models.clear()
        oad.RegisterSubmodel.active_models.update(models)
