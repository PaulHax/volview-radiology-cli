"""Generate a tiny synthetic axial CT DICOM series as test fixtures.

Run once, offline, with pydicom (the Docker image has itk but not pydicom, so
these are committed as binary fixtures rather than generated at test time).

Geometry is deliberately anisotropic -- in-plane 0.7mm, slice step 2.5mm -- so a
correct assemble() recovers z-spacing 2.5 (the anti-[1,1,1] regression), and the
slices are written with filenames in REVERSE z order so filename order != slice
order (proves metadata sorting, not input order).
"""
import os
import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import (
    CTImageStorage,
    ExplicitVRLittleEndian,
    generate_uid,
)

OUT = os.path.join(os.path.dirname(__file__), "dicom_series")
os.makedirs(OUT, exist_ok=True)

ROWS, COLS, NSLICES = 16, 16, 8
PX, PY, DZ = 0.7, 0.7, 2.5

study_uid = generate_uid()
series_uid = generate_uid()
frame_uid = generate_uid()

paths = []
for z in range(NSLICES):
    ds = Dataset()
    fm = FileMetaDataset()
    fm.MediaStorageSOPClassUID = CTImageStorage
    fm.MediaStorageSOPInstanceUID = generate_uid()
    fm.TransferSyntaxUID = ExplicitVRLittleEndian
    fm.ImplementationClassUID = generate_uid()
    ds.file_meta = fm
    ds.preamble = b"\x00" * 128

    ds.SOPClassUID = CTImageStorage
    ds.SOPInstanceUID = fm.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.FrameOfReferenceUID = frame_uid
    ds.Modality = "CT"
    ds.PatientName = "VolView^Synthetic"
    ds.PatientID = "VV-SYNTH-1"
    ds.SeriesNumber = 1
    ds.InstanceNumber = z + 1

    ds.Rows = ROWS
    ds.Columns = COLS
    ds.PixelSpacing = [PY, PX]  # DICOM order: row spacing (y), col spacing (x)
    ds.SliceThickness = DZ
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    ds.ImagePositionPatient = [0.0, 0.0, float(z) * DZ]
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 1  # signed
    ds.RescaleIntercept = 0
    ds.RescaleSlope = 1

    # z-varying ramp so slices are distinguishable; a bright block in one
    # corner breaks any x/y symmetry so a transpose would be visible.
    arr = np.full((ROWS, COLS), z * 100, dtype=np.int16)
    arr[0:4, 0:8] = 1000
    ds.PixelData = arr.tobytes()

    ds.is_little_endian = True
    ds.is_implicit_VR = False

    # filename in REVERSE z order: slice000 holds the LAST slice, etc.
    fname = "slice%03d.dcm" % (NSLICES - 1 - z)
    path = os.path.join(OUT, fname)
    ds.save_as(path, write_like_original=False)
    paths.append(path)

print("wrote", len(paths), "slices to", OUT)

# Verify they read back with pydicom and geometry is as intended.
for p in sorted(os.listdir(OUT)):
    d = pydicom.dcmread(os.path.join(OUT, p))
    assert d.SeriesInstanceUID == series_uid
    print(" ", p, "InstanceNumber", d.InstanceNumber,
          "ImagePositionPatient", list(d.ImagePositionPatient))
print("OK")
