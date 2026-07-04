# Minimal radiology Slicer CLI image for VolView.
#
# Exposes Slicer Execution Model CLIs backed by ITK. Compatible with
# `slicer_cli_web`'s --list_cli convention.

FROM python:3.11-slim

LABEL maintainer="VolView <volview@kitware.com>"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
        itk==5.4.0 \
        girder-slicer-cli-web \
        girder-client

WORKDIR /opt/cli
COPY . /opt/cli/

ENTRYPOINT ["python", "/opt/cli/cli_list.py"]
