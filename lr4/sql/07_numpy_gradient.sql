\set ON_ERROR_STOP on

CREATE OR REPLACE FUNCTION lr4.numpy_gradient(
    p_values double precision[],
    p_spacing double precision DEFAULT 1.0
)
RETURNS double precision[]
LANGUAGE plpython3u
IMMUTABLE
STRICT
PARALLEL UNSAFE
AS $python$
import math

try:
    import numpy as np
except ImportError:
    plpy.error(
        "NumPy is required for lr4.numpy_gradient; "
        "install the py3-numpy package in the PostgreSQL runtime"
    )

if not math.isfinite(p_spacing) or p_spacing <= 0:
    plpy.error("spacing must be a finite number greater than zero")

if any(value is None for value in p_values):
    plpy.error("input array must not contain NULL values")

values = np.asarray(p_values, dtype=np.float64)

if values.ndim != 1:
    plpy.error("input must be a one-dimensional array")
if values.size < 2:
    plpy.error("at least two values are required to calculate a gradient")
if not np.all(np.isfinite(values)):
    plpy.error("input array must contain only finite numbers")

gradient = np.gradient(values, p_spacing)
return gradient.astype(float).tolist()
$python$;

