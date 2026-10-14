"""Generate deterministic synthetic CT and PET DICOM fixtures."""

from pathlib import Path
from uuid import NAMESPACE_OID, uuid5

import numpy as np


def _uid(name):
    return f"2.25.{uuid5(NAMESPACE_OID, 'volview.synthetic.' + name).int}"


def _write_slice(output_dir, group, filename, pixels, *, patient_id, instance,
                 position, series=1, spacing=(0.7, 0.7, 2.5), modality="CT",
                 slope=1, intercept=0):
    import pydicom
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import (
        CTImageStorage,
        ExplicitVRLittleEndian,
        PositronEmissionTomographyImageStorage,
    )

    pixels = np.asarray(pixels, dtype="<i2")
    data = Dataset()
    data.file_meta = FileMetaDataset()
    data.file_meta.MediaStorageSOPClassUID = (
        CTImageStorage if modality == "CT" else PositronEmissionTomographyImageStorage
    )
    data.file_meta.MediaStorageSOPInstanceUID = _uid(f"{group}.{filename}")
    data.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    data.file_meta.ImplementationClassUID = _uid("writer")
    data.preamble = b"\x00" * 128
    data.SOPClassUID = data.file_meta.MediaStorageSOPClassUID
    data.SOPInstanceUID = data.file_meta.MediaStorageSOPInstanceUID
    data.StudyInstanceUID = _uid(f"{group}.study")
    data.SeriesInstanceUID = _uid(f"{group}.series.{series}")
    data.FrameOfReferenceUID = _uid(f"{group}.frame")
    data.Modality = modality
    data.PatientName, data.PatientID = "VolView^Synthetic", patient_id
    data.SeriesNumber, data.InstanceNumber = series, instance
    data.Rows, data.Columns = pixels.shape
    # DICOM pixel spacing is ordered by row (y), then column (x).
    data.PixelSpacing, data.SliceThickness = list(spacing[:2]), spacing[2]
    data.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    data.ImagePositionPatient = list(position)
    data.SamplesPerPixel, data.PhotometricInterpretation = 1, "MONOCHROME2"
    data.BitsAllocated, data.BitsStored, data.HighBit, data.PixelRepresentation = 16, 16, 15, 1
    data.RescaleSlope, data.RescaleIntercept = slope, intercept
    if modality == "PT":
        data.Units = "BQML"
    data.PixelData = pixels.tobytes()
    destination = output_dir / group / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    pydicom.dcmwrite(destination, data, enforce_file_format=True)


def generate_dicom_fixtures(output_dir):
    """Write three fixture directories beneath ``output_dir``."""
    output_dir = Path(output_dir)
    for z in range(8):
        pixels = np.full((16, 16), z * 100, dtype="<i2")
        # The bright corner makes x/y transposition observable.
        pixels[:4, :8] = 1000
        _write_slice(
            output_dir, "dicom_series", f"slice{7 - z:03d}.dcm", pixels,
            patient_id="VV-SYNTH-1", instance=z + 1, position=(0.0, 0.0, z * 2.5),
        )

    for series in range(2):
        for z in range(4):
            pixels = np.full((16, 16), (series + 1) * 100 + z * 10, dtype="<i2")
            _write_slice(
                output_dir, "dicom_two_series", f"series{series}_slice{z:03d}.dcm", pixels,
                patient_id="VV-SYNTH-2SERIES", instance=z + 1, series=series + 1,
                position=(0.0, 0.0, z * 2.5),
            )

    for z, pixels in enumerate([
        [[3, 7, 11], [19, 23, 31]],
        [[101, 103, 107], [109, 113, 123]],
    ]):
        _write_slice(
            output_dir, "dicom_rescale", f"slice{1 - z}.dcm", pixels,
            patient_id="VV-RESCALE", instance=z + 1, position=(10.0, 20.0, 30.0 + z * 3.0),
            spacing=(2.0, 0.5, 3.0), modality="PT", slope=0.25, intercept=-9.5,
        )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    generate_dicom_fixtures(parser.parse_args().output_dir)
