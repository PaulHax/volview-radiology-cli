"""Masked-composite primitives using only ``numpy``.

``MaskedMedianFilter`` filters a background volume but keeps the result only
where a painted labelmap is nonzero. The CLI handles image I/O and passes plain
arrays to these functions.

Label values are read from the labelmap **without a float cast** (the CLI never
``to_scalar_float``'s the labelmap the way it does the background), so an
integer labelmap arrives here with its label values intact and
``nonzero_mask`` selects any nonzero label exactly.
"""

import numpy as np


def nonzero_mask(labelmap_array):
    """Boolean mask of voxels carrying any nonzero label.

    Works on the labelmap's native (integer) dtype -- no cast, no threshold
    tuning -- so ``0`` is background and every other label selects a voxel.
    """
    return np.asarray(labelmap_array) != 0


def composite_inside_mask(background, filtered, mask):
    """``filtered`` inside the mask, original ``background`` outside.

    The labelmap is painted on the background, so the three arrays share a voxel
    grid; a shape mismatch is out of scope and fails closed with a clear error
    rather than broadcasting into a wrong-geometry result. The output keeps the
    background's dtype (the filter domain), so writing it back is lossless.
    """
    background = np.asarray(background)
    filtered = np.asarray(filtered)
    mask = np.asarray(mask)
    if not (background.shape == filtered.shape == mask.shape):
        raise ValueError(
            "background %s, filtered %s and mask %s must share one voxel grid"
            % (background.shape, filtered.shape, mask.shape)
        )
    return np.where(mask, filtered, background).astype(background.dtype)
