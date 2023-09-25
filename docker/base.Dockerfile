ARG CUDA_VERSION=11.3.1
ARG CUDNN_VERSION=8
ARG UBUNTU_VERSION=20.04

FROM nvidia/cuda:${CUDA_VERSION}-cudnn${CUDNN_VERSION}-devel-ubuntu${UBUNTU_VERSION}
ENV LANG C.UTF-8
ENV PATH /opt/conda/bin:$PATH

ARG CUDA_VERSION=11.3.1
ARG CUDNN_VERSION=8
ARG UBUNTU_VERSION=20.04
ARG PYTHON_VERSION=3.9
ARG CONDA_VERSION=latest
ARG TORCH_VERSION=1.10.2
ARG TORCHVISION_VERSION=0.11.*
ARG TORCHSCATTER_VERSION=2.0.9
ARG SPCONV_VERSION=2.1.*
ARG MMCV_VERSION=1.4.0
ARG MMSEG_VERSION=0.14.1
ARG MMDET_VERSION=2.14.0
ARG MMDET3D_VERSION=0.15.0


RUN export CU_VERSION=$(echo ${CUDA_VERSION%.*} | tr -d \.) && \

# ------------------------------------------------------------------------------
# NVIDIA key rotation
# https://forums.developer.nvidia.com/t/notice-cuda-linux-repository-key-rotation/212771
# ------------------------------------------------------------------------------

    apt-key adv --fetch-keys https://developer.download.nvidia.com/compute/cuda/repos/ubuntu$(echo $UBUNTU_VERSION | tr -d \.)/x86_64/3bf863cc.pub && \
    apt-get update -q && \

# ------------------------------------------------------------------------------
# tools
# ------------------------------------------------------------------------------

    DEBIAN_FRONTEND=noninteractive apt-get install -q -y --no-install-recommends \
        bzip2 \
        ca-certificates \
        git \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        mercurial \
        openssh-client \
        procps \
        subversion \
        wget \
        curl \
        vim \
        unzip \
        unrar \
        build-essential \
        software-properties-common \
        libgl1 \
        && \

# ------------------------------------------------------------------------------
# miniconda
# https://github.com/ContinuumIO/docker-images/blob/master/miniconda3/debian/Dockerfile
# ------------------------------------------------------------------------------

    set -x && \
    UNAME_M="$(uname -m)" && \
    if [ "${CONDA_VERSION}" != "latest" ]; then \
        CONDA_VERSION="py$(echo ${PYTHON_VERSION} | tr -d \.)_${CONDA_VERSION}"; \
    fi && \
    if [ "${UNAME_M}" = "x86_64" ]; then \
        MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-${CONDA_VERSION}-Linux-x86_64.sh"; \
    elif [ "${UNAME_M}" = "s390x" ]; then \
        MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-${CONDA_VERSION}-Linux-s390x.sh"; \
    elif [ "${UNAME_M}" = "aarch64" ]; then \
        MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-${CONDA_VERSION}-Linux-aarch64.sh"; \
    elif [ "${UNAME_M}" = "ppc64le" ]; then \
        MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-${CONDA_VERSION}-Linux-ppc64le.sh"; \
    fi && \
    wget "${MINICONDA_URL}" -O miniconda.sh -q && \
    echo "${SHA256SUM} miniconda.sh" > shasum && \
    mkdir -p /opt && \
    sh miniconda.sh -b -p /opt/conda && \
    rm miniconda.sh shasum && \
    ln -s /opt/conda/etc/profile.d/conda.sh /etc/profile.d/conda.sh && \
    echo ". /opt/conda/etc/profile.d/conda.sh" >> ~/.bashrc && \
    echo "conda activate base" >> ~/.bashrc && \
    find /opt/conda/ -follow -type f -name '*.a' -delete && \
    find /opt/conda/ -follow -type f -name '*.js.map' -delete && \
    /opt/conda/bin/conda clean -afy && \

# ------------------------------------------------------------------------------
# essential libraries
# ------------------------------------------------------------------------------

    conda install python=${PYTHON_VERSION} && \
    pip install \
        # file formats
        pyyaml \
        h5py \

        # maths & data
        numpy \
        scipy \
        scikit-learn \
        pandas \

        # image processing
        pillow \
        scikit-image \

        # plotting
        matplotlib \
        seaborn \

        # jupyter
        jupyterlab \

        # -c conda-forge \
        && \

# ------------------------------------------------------------------------------
# pytorch
# ------------------------------------------------------------------------------

    pip install \
        torch==${TORCH_VERSION} \
        torchvision==${TORCHVISION_VERSION} \
        --index-url https://download.pytorch.org/whl/cu${CU_VERSION} && \
    pip install tensorboard && \

# ------------------------------------------------------------------------------
# spconv
# ------------------------------------------------------------------------------

    apt-get update -q && \
    DEBIAN_FRONTEND=noninteractive apt-get install -q -y --no-install-recommends \
        libboost-dev \
        libopenexr-dev \
        && \

    pip install spconv-cu${CU_VERSION}==${SPCONV_VERSION} && \

# ------------------------------------------------------------------------------
# torch-scatter
# ------------------------------------------------------------------------------

    pip install torch-scatter==${TORCHSCATTER_VERSION} \
        -f https://data.pyg.org/whl/torch-${TORCH_VERSION}+cu${CU_VERSION}.html && \

# ------------------------------------------------------------------------------
# open3d
# ------------------------------------------------------------------------------

    pip install open3d && \

# ------------------------------------------------------------------------------
# pcdet dependencies
# ------------------------------------------------------------------------------

    pip install \
        llvmlite \
        numba \
        tensorboardX \
        easydict \
        opencv-python==4.7.* \
        pyquaternion \
        SharedArray \
        kornia==0.6.* \
        &&\

# ------------------------------------------------------------------------------
# mmdet3d dependencies
# ------------------------------------------------------------------------------

    pip install \
        mmcv-full==${MMCV_VERSION} \
        -f https://download.openmmlab.com/mmcv/dist/cu${CU_VERSION}/torch${TORCH_VERSION%.*}/index.html && \


    pip install \
        ipdb \
        mmsegmentation==${MMSEG_VERSION} \
        mmdet==${MMDET_VERSION} \
        && \

# ------------------------------------------------------------------------------
# tracker dependencies
# ------------------------------------------------------------------------------

    pip install filterpy motmetrics && \

# ------------------------------------------------------------------------------
# dataset dependencies
# ------------------------------------------------------------------------------

    pip install \
        tensorflow==2.11.0 \
        waymo-open-dataset-tf-2-11-0 \
        nuscenes-devkit \
        && \

# ------------------------------------------------------------------------------
# version hacks
# ------------------------------------------------------------------------------
    pip install \
        setuptools==58.* \
        protobuf==3.19.0 && \

# ------------------------------------------------------------------------------
# config & cleanup
# ------------------------------------------------------------------------------

    ldconfig && \
    apt-get clean && \
    apt-get autoremove && \
    rm -rf /var/lib/apt/lists/* /tmp/* ~/*
