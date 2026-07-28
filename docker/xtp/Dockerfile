# XTP simulation bridge runtime.
# The official XTP Python bindings ship prebuilt x86_64 .so files for
# CentOS7+Python3.9 only, so this image is linux/amd64 and pins Python 3.9.
# On Apple Silicon run it under Rosetta/qemu (see README.md).
FROM --platform=linux/amd64 python:3.9-slim-bullseye

RUN apt-get update \
    && apt-get install -y --no-install-recommends git libstdc++6 g++ make wget ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# The bindings were built against boost_python 1.80.0 + Python 3.9 on CentOS 7
# (repo README), i.e. the pre-C++11 libstdc++ ABI — hence _GLIBCXX_USE_CXX11_ABI=0.
# Download boost_1_80_0.tar.gz into this directory before building (see README.md);
# in-build downloads are unusably slow on mainland networks.
COPY boost_1_80_0.tar.gz /boost_1_80_0.tar.gz
RUN tar -xzf boost_1_80_0.tar.gz \
    && cd boost_1_80_0 \
    && ./bootstrap.sh --with-python=python3.9 \
        --with-libraries=python,thread,chrono,system,atomic,date_time \
    && ./b2 -j"$(nproc)" variant=release link=shared \
        define=_GLIBCXX_USE_CXX11_ABI=0 install \
    && ldconfig \
    && cd / && rm -rf boost_1_80_0 boost_1_80_0.tar.gz

# GitHub connectivity can be flaky from mainland networks; retry the clone.
RUN for attempt in 1 2 3 4 5; do \
        git clone --depth 1 https://github.com/ztsec/xtp_api_python.git /opt/xtp_api_python && break; \
        rm -rf /opt/xtp_api_python; sleep 10; \
    done \
    && test -d /opt/xtp_api_python/bin/Linux

ENV XTP_BIN=/opt/xtp_api_python/bin/Linux/centos7+python3.9
ENV PYTHONPATH=$XTP_BIN
ENV LD_LIBRARY_PATH=$XTP_BIN

# The bridge compares the instruction date against today; that must be the
# A-share calendar date, not UTC.
ENV TZ=Asia/Shanghai

WORKDIR /workspace
CMD ["python", "-c", "import vnxtptrader, vnxtpquote; print('xtp bindings ok')"]
