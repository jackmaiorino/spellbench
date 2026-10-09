FROM python:3.13-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26 AS base
RUN python -m pip install --no-cache-dir --no-deps --index-url https://download.pytorch.org/whl/cpu torch==2.8.0+cpu
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir --requirement /app/requirements.txt
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MZ_DEVICE=cpu OMP_NUM_THREADS=1 MKL_NUM_THREADS=1

# DraftZero FDN graph network: `docker build --target gnn`. Its extra package stays out of the default image.
FROM base AS gnn
COPY requirements-gnn.txt /app/requirements-gnn.txt
RUN python -m pip install --no-cache-dir --no-deps --requirement /app/requirements-gnn.txt
COPY gnn_reference_probe.py /app/
WORKDIR /tmp
USER 65534:65534
ENTRYPOINT ["python", "-I", "/app/gnn_reference_probe.py"]

FROM base
COPY checkpoint_runtime.py checkpoint_format.py maintainer_runtime.py /app/
WORKDIR /tmp
USER 65534:65534
ENTRYPOINT ["python", "/app/checkpoint_runtime.py"]
