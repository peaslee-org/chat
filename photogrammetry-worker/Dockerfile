# Stage 1: compile OpenMVS (CUDA) on the same Ubuntu/CUDA line as the COLMAP image.
FROM nvidia/cuda:12.9.1-devel-ubuntu24.04 AS build
ARG OPENMVS_TAG=v2.4.0
RUN apt-get update && apt-get install -y --no-install-recommends \
      git cmake build-essential pkg-config ca-certificates curl xz-utils libeigen3-dev libnanoflann-dev libboost-iostreams-dev \
      libboost-program-options-dev libboost-system-dev libboost-serialization-dev libopencv-dev \
      libglu1-mesa-dev libglew-dev libpng-dev libjpeg-dev libtiff-dev libgmp-dev libmpfr-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
# CGAL 6.0.1, header-only, from the release tarball (libs + CMake config; ~5 MB, installs in seconds).
# v2.4.0 includes CGAL 6 names (AABB_traits_3.h, AABB_triangle_primitive_3.h); noble's libcgal-dev is
# 5.6 and must not be installed here or find_package could pick it up. Matches upstream's own build.
ARG CGAL_VERSION=6.0.1
RUN curl -fsSL "https://github.com/CGAL/cgal/releases/download/v${CGAL_VERSION}/CGAL-${CGAL_VERSION}-library.tar.xz" | tar -xJ \
 && cmake -S "CGAL-${CGAL_VERSION}" -B cgal-build -DCMAKE_BUILD_TYPE=Release \
 && cmake --install cgal-build \
 && rm -rf "CGAL-${CGAL_VERSION}" cgal-build
RUN git clone --depth 1 https://github.com/cdcseacave/VCG.git vcglib \
 && git clone --depth 1 --branch ${OPENMVS_TAG} https://github.com/cdcseacave/openMVS.git openMVS
# v2.4.0 writes .jxl via cv::IMWRITE_JPEGXL_QUALITY unguarded (OpenCV >= 4.11); noble ships 4.6.0 in
# both stages, and upstream's own ubuntu:24.04 Dockerfile has the same break. The patch turns JXL
# support off (libs/IO/CMakeLists.txt) and guards the one write-path branch (libs/Common/Types.inl).
# The worker never reads or writes .jxl. Regenerate the patch if OPENMVS_TAG changes.
COPY photogrammetry-worker/openmvs-v2.4.0-noble.patch /src/
RUN git -C openMVS apply --verbose /src/openmvs-v2.4.0-noble.patch
# USE_PYTHON=OFF: v2.4.0 defaults the Python bindings ON, which makes FIND_PACKAGE(Python3 ... REQUIRED)
# fail on a builder without python3-dev (first CI build, 2026-08-27). The worker calls the CLI tools
# only. VIEWER/TESTS off: no GUI in a worker, and both shorten the ~30 min build.
# INSTALL_PREFIX at configure time: OpenMVS bakes absolute install dirs (<prefix>/bin/OpenMVS,
# <prefix>/lib/OpenMVS) when it configures, so `cmake --install --prefix` is ignored (attempt 6 put
# everything under /usr/local). Libraries are static; only bin/OpenMVS/ is needed downstream.
RUN cmake -S openMVS -B openMVS/build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/openmvs \
      -DVCG_ROOT=/src/vcglib -DOpenMVS_USE_CUDA=ON \
      -DOpenMVS_USE_PYTHON=OFF -DOpenMVS_BUILD_VIEWER=OFF -DOpenMVS_ENABLE_TESTS=OFF \
 && cmake --build openMVS/build -j"$(nproc)" \
 && cmake --install openMVS/build \
 && ls /opt/openmvs/bin/OpenMVS/DensifyPointCloud /opt/openmvs/bin/OpenMVS/TextureMesh

# Stage 2: runtime = the official COLMAP image (Ubuntu 24.04, CUDA 12.9.1 runtime) + OpenMVS + Python.
FROM colmap/colmap:20260729.7651
RUN grep -q 'VERSION_ID="24.04"' /etc/os-release   # the build stage above must match this base
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3.12 python3.12-venv libpython3.12 \
      libopencv-core406t64 libopencv-imgproc406t64 libopencv-imgcodecs406t64 libopencv-calib3d406t64 \
      libboost-iostreams1.83.0 libboost-program-options1.83.0 libboost-system1.83.0 libboost-serialization1.83.0 \
      libgmp10 libmpfr6 libgomp1 libglew2.2 libglu1-mesa libpng16-16t64 libjpeg8 libtiff6 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /opt/openmvs/bin/OpenMVS/ /usr/local/bin/
RUN ldconfig && colmap -h >/dev/null && DensifyPointCloud --help >/dev/null && TextureMesh --help >/dev/null

WORKDIR /app
RUN python3.12 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"
COPY gpu-worker/ /app/gpu-worker/
RUN pip install --no-cache-dir /app/gpu-worker boto3 pydantic-settings sqlalchemy psycopg2-binary "trimesh>=4.4" pillow numpy
COPY photogrammetry-worker/ /app/
CMD ["python", "main.py"]
