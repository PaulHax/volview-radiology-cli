# Minimal radiology Slicer CLI image for VolView.
#
# Exposes Slicer Execution Model CLIs backed by ITK. Compatible with
# `slicer_cli_web`'s --list_cli convention.

FROM python:3.11-slim AS runtime

LABEL maintainer="VolView <volview@kitware.com>"
LABEL org.opencontainers.image.source="https://github.com/PaulHax/volview-radiology-cli"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
        itk==5.4.0 \
        girder-slicer-cli-web==1.3.5 \
        girder-client==3.2.14

WORKDIR /opt/cli

FROM runtime AS test

RUN pip install --no-cache-dir pytest==8.3.5
COPY . /opt/cli/
RUN python -m pytest -q \
    && python /opt/cli/cli_list.py --list_cli >/dev/null

FROM runtime AS final

COPY . /opt/cli/

ENTRYPOINT ["python", "/opt/cli/cli_list.py"]
