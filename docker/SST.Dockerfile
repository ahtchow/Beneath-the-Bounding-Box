FROM btbb-base as builder

ENV TORCH_CUDA_ARCH_LIST="6.0 6.1 7.0 7.5 8.0 8.6+PTX" \
    TORCH_NVCC_FLAGS="-Xfatbin -compress-all" \
    FORCE_CUDA="1"

# Install TorchEx
RUN conda clean --all \
    && git clone https://github.com/Abyssaledge/TorchEx.git \
    && cd /TorchEx \
    && pip install --no-cache-dir -e .

# Common Tools
RUN apt-get update && apt-get install -y \
    bash-completion \
    build-essential \
    curl \
    cmake \
    git \
    htop \
    nano \
    software-properties-common \
    sudo \
    tmux \
    tree \
    unzip \
    vim \
    wget \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update && \
    apt-get install --assume-yes pkg-config zip g++ zlib1g-dev unzip python3 python3-pip wget && \
    rm -rf /var/lib/apt/lists/*

# Download and install Bazel
ARG BAZEL_VERSION=5.4.0
RUN wget https://github.com/bazelbuild/bazel/releases/download/${BAZEL_VERSION}/bazel-${BAZEL_VERSION}-installer-linux-x86_64.sh && \
    chmod +x bazel-${BAZEL_VERSION}-installer-linux-x86_64.sh && \
    ./bazel-${BAZEL_VERSION}-installer-linux-x86_64.sh && \
    rm bazel-${BAZEL_VERSION}-installer-linux-x86_64.sh

RUN mkdir -p /work_dir;

WORKDIR /work_dir

ENV NVIDIA_VISIBLE_DEVICES all
ENV NVIDIA_DRIVER_CAPABILITIES all
