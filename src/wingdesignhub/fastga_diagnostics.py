"""Collect upstream warnings without silencing them or changing aircraft inputs."""
from contextlib import contextmanager
import inspect
import logging
import warnings
import numpy as np


class DiagnosticLog(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.events = []

    def emit(self, record):
        if not record.name.startswith("fastga"):
            return
        event = {"source": record.name, "function": record.funcName,
                 "message": record.getMessage(), "arguments": {}, "ranges": {}}
        frame = inspect.currentframe()
        try:
            while frame:
                if frame.f_code.co_filename == record.pathname and frame.f_code.co_name == record.funcName:
                    local = frame.f_locals
                    for key in ("chord_ratio", "control_deflection", "flap_angle", "area_ratio"):
                        value = local.get(key)
                        # Some upstream components overwrite locals before warning; keep original input.
                        if "inputs" in local:
                            try:
                                value = local["inputs"][key]
                            except (KeyError, RuntimeError):
                                pass
                        if value is not None and np.asarray(value).size == 1:
                            scalar = float(np.asarray(value).item())
                            if np.isfinite(scalar):
                                event["arguments"][key] = scalar
                    for key, value in local.items():
                        if (key == "x" or key.startswith("x_")) and isinstance(value, (list, np.ndarray)) and len(value):
                            event["ranges"][key] = [float(np.min(value)), float(np.max(value))]
                    break
                frame = frame.f_back
        finally:
            del frame
        if event not in self.events:
            self.events.append(event)


@contextmanager
def collect_diagnostics():
    handler = DiagnosticLog()
    logger = logging.getLogger("fastga")
    logger.addHandler(handler)
    python_events = []
    original = warnings.showwarning

    def show(message, category, filename, lineno, file=None, line=None):
        item = {"category": category.__name__, "message": str(message)}
        if item not in python_events:
            python_events.append(item)
        original(message, category, filename, lineno, file, line)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("always")
            warnings.showwarning = show
            yield handler.events, python_events
    finally:
        logger.removeHandler(handler)


def final_domain_checks(problem):
    """Check three observed active correlations against FAST-GA 1.4.0 bounds.

    This is an explicit scoped audit, not a complete validity check of all FAST-GA models.
    """
    import pandas as pd
    from fastga.models.aerodynamics.components import figure_digitization as fd
    def scalar(name):
        return float(problem.get_val(name).item())

    table = pd.read_csv(fd.RESOURCE_PATH/fd.DELTA_CD_PLAIN_FLAP)
    x15, _ = fd.filter_nans(table, ["DELTA_F_15_X", "DELTA_F_15_Y"])
    x60, _ = fd.filter_nans(table, ["DELTA_F_60_X", "DELTA_F_60_Y"])
    tail = pd.read_csv(fd.RESOURCE_PATH/fd.K_VH)
    x, _ = fd.filter_nans(tail, ["X", "Y"])
    values = [
        ("elevator_chord_ratio", scalar("data:geometry:horizontal_tail:elevator_chord_ratio"),
         max(min(x15), min(x60)), min(max(x15), max(x60)), "delta_cd_plain_flap"),
        ("horizontal_to_vertical_tail_area", scalar("data:geometry:horizontal_tail:area")/
         scalar("data:geometry:vertical_tail:area"), min(x), max(x), "k_vh"),
        # Bounds in 1.4.0 ComputeSingleSlottedLiftEffectiveness.compute;
        # hinge_moments_elevator connects the signed takeoff elevator angle directly.
        ("takeoff_elevator_angle_deg", scalar("data:mission:sizing:takeoff:elevator_angle"),
         -.08, 79.32, "ComputeSingleSlottedLiftEffectiveness")]
    return [{"parameter": key, "value": value, "lower": float(low), "upper": float(high),
             "correlation": method, "within_range": bool(np.isfinite(value) and low <= value <= high)}
            for key, value, low, high, method in values]
