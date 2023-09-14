FROM nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04 as builder

ENV DEBIAN_FRONTEND=noninteractive

ENV TORCH_CUDA_ARCH_LIST="6.0 6.1 7.0 7.5 8.0 8.6+PTX" \
    TORCH_NVCC_FLAGS="-Xfatbin -compress-all" \
    FORCE_CUDA="1"

RUN apt-key adv --fetch-keys https://developer.download.nvidia.com/compute/cuda/repos/ubuntu22.04/x86_64/3bf863cc.pub \
    && apt-key adv --fetch-keys https://developer.download.nvidia.com/compute/machine-learning/repos/ubuntu22.04/x86_64/7fa2af80.pub

RUN apt-get update && apt-get install -y \
    bash-completion \
    build-essential \
    byobu \
    curl \
    cmake \
    git \
    htop \
    iputils-ping \
    iproute2 \
    libgl1-mesa-glx \
    nano \
    nvtop \
    python3-pip \
    software-properties-common \
    sudo \
    tmux \
    tree \
    unzip \
    vim \
    wget \
    && rm -rf /var/lib/apt/lists/*
