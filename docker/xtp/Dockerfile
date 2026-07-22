# XTP simulation bridge runtime.
# The official XTP Python bindings ship prebuilt x86_64 .so files for
# CentOS7+Python3.9 only, so this image is linux/amd64 and pins Python 3.9.
# On Apple Silicon run it under Rosetta/qemu (see README.md).
FROM --platform=linux/amd64 python:3.9-slim-bullseye

RUN apt-get update \
    && apt-get install -y --no-install-recommends git libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/ztsec/xtp_api_python.git /opt/xtp_api_python

ENV XTP_BIN=/opt/xtp_api_python/bin/Linux/centos7+python3.9
ENV PYTHONPATH=$XTP_BIN
ENV LD_LIBRARY_PATH=$XTP_BIN

WORKDIR /workspace
CMD ["python", "-c", "import vnxtptrader, vnxtpquote; print('xtp bindings ok')"]
