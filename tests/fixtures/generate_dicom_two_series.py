"""Generate a tiny two-series DICOM fixture -- one directory holding slices from
TWO distinct SeriesInstanceUIDs.

Run once, offline, with pydicom (the Docker image has itk but not pydicom, so
this is committed as binary fixtures rather than generated at test time). It is
the fail-closed regression wall for the ambiguous multi-series input: assemble()
must RAISE rather than silently keep the first series and drop the rest.
"""
import os

import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid

OUT = os.path.join(os.path.dirname(__file__), "dicom_two_series")
os.makedirs(OUT, exist_ok=True)

ROWS, COLS, NSLICES = 16, 16, 4
PX, PY, DZ = 0.7, 0.7, 2.5

study_uid = generate_uid()
frame_uid = generate_uid()
series_uids = [generate_uid(), generate_uid()]

paths = []
for s, series_uid in enumerate(series_uids):
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
        ds.PatientID = "VV-SYNTH-2SERIES"
        ds.SeriesNumber = s + 1
        ds.InstanceNumber = z + 1

        ds.Rows = ROWS
        ds.Columns = COLS
        ds.PixelSpacing = [PY, PX]
        ds.SliceThickness = DZ
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.ImagePositionPatient = [0.0, 0.0, float(z) * DZ]
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 1
        ds.RescaleIntercept = 0
        ds.RescaleSlope = 1

        arr = np.full((ROWS, COLS), (s + 1) * 100 + z * 10, dtype=np.int16)
        ds.PixelData = arr.tobytes()

        ds.is_little_endian = True
        ds.is_implicit_VR = False

        fname = "series%d_slice%03d.dcm" % (s, z)
        path = os.path.join(OUT, fname)
        ds.save_as(path, write_like_original=False)
        paths.append(path)

print("wrote", len(paths), "slices (2 series) to", OUT)

seen = set()
for p in sorted(os.listdir(OUT)):
    d = pydicom.dcmread(os.path.join(OUT, p))
    seen.add(d.SeriesInstanceUID)
assert len(seen) == 2, "expected exactly two distinct series, got %d" % len(seen)
print("OK -- 2 distinct SeriesInstanceUIDs")
