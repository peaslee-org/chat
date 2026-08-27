# Stage 1: compile OpenMVS (CUDA) on the same Ubuntu/CUDA line as the COLMAP image.
FROM nvidia/cuda:12.9.1-devel-ubuntu24.04 AS build
ARG OPENMVS_TAG=v2.4.0
RUN apt-get update && apt-get install -y --no-install-recommends \
      git cmake build-essential ca-certificates libeigen3-dev libcgal-dev libboost-iostreams-dev \
      libboost-program-options-dev libboost-system-dev libboost-serialization-dev libopencv-dev \
      libglu1-mesa-dev libglew-dev libpng-dev libjpeg-dev libtiff-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git clone --depth 1 https://github.com/cdcseacave/VCG.git vcglib \
 && git clone --depth 1 --branch ${OPENMVS_TAG} https://github.com/cdcseacave/openMVS.git openMVS
# USE_PYTHON=OFF: v2.4.0 defaults the Python bindings ON, which makes FIND_PACKAGE(Python3 ... REQUIRED)
# fail on a builder without python3-dev (first CI build, 2026-08-27). The worker calls the CLI tools
# only. VIEWER/TESTS off: no GUI in a worker, and both shorten the ~30 min build.
RUN cmake -S openMVS -B openMVS/build -DCMAKE_BUILD_TYPE=Release -DVCG_ROOT=/src/vcglib -DOpenMVS_USE_CUDA=ON \
      -DOpenMVS_USE_PYTHON=OFF -DOpenMVS_BUILD_VIEWER=OFF -DOpenMVS_ENABLE_TESTS=OFF \
 && cmake --build openMVS/build -j"$(nproc)" \
 && cmake --install openMVS/build --prefix /opt/openmvs

# Stage 2: runtime = the official COLMAP image (Ubuntu 24.04, CUDA 12.9.1 runtime) + OpenMVS + Python.
FROM colmap/colmap:20260729.7651
RUN grep -q 'VERSION_ID="24.04"' /etc/os-release   # the build stage above must match this base
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3.12 python3.12-venv libpython3.12 \
      libopencv-core406t64 libopencv-imgproc406t64 libopencv-imgcodecs406t64 libopencv-calib3d406t64 \
      libboost-iostreams1.83.0 libboost-program-options1.83.0 libboost-system1.83.0 libboost-serialization1.83.0 \
      libcgal-dev libgomp1 libglew2.2 libglu1-mesa libpng16-16t64 libjpeg8 libtiff6 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /opt/openmvs/bin/ /usr/local/bin/
COPY --from=build /opt/openmvs/lib/ /usr/local/lib/
RUN ldconfig && colmap -h >/dev/null && DensifyPointCloud --help >/dev/null && TextureMesh --help >/dev/null

WORKDIR /app
RUN python3.12 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"
COPY gpu-worker/ /app/gpu-worker/
RUN pip install --no-cache-dir /app/gpu-worker boto3 pydantic-settings sqlalchemy psycopg2-binary "trimesh>=4.4" pillow numpy
COPY photogrammetry-worker/ /app/
CMD ["python", "main.py"]
