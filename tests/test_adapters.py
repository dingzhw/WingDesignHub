import sys
import pytest
from wingdesignhub.adapters import parse_avl, execute


@pytest.mark.parametrize("header,row", [
    ("j Yle Chord Area c_cl ai cl_norm cl cd cdv cm_c/4 cm_LE C.P.x/c", "1 1 1.5 0.2 .3 0 .2 .2 .01 0 0 0 .25"),
    ("j Xle Yle Zle Chord Area c_cl ai cl_norm cl cd cdv cm_c/4 cm_LE C.P.x/c", "1 0 1 0 1.5 .2 .3 0 .2 .2 .01 0 0 0 .25")])
def test_avl_formats(header, row):
    output = "Vortex Lattice Output -- Total Forces\nCLtot=.2 CDff=.01 Cmtot=0 Sref=15 Cref=1.5 Bref=10"
    _, strips = parse_avl(output, header+"\n"+row)
    assert strips == [{"y_m": 1., "area_m2": .2, "cl": .2}]


def test_timeout_retains_log(tmp_path):
    with pytest.raises(RuntimeError, match="超过"):
        execute([sys.executable, "-c", "import time; print('started',flush=True); time.sleep(10)"], tmp_path, timeout=.5)
    assert (tmp_path/"stdout.log").exists()
    assert (tmp_path/"command.json").exists()
