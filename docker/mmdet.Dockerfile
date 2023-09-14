FROM btbb-base as builder

ARG PYTORCH="2.0.0"
ARG TORCHVISION="0.15.1"
ARG CUDA="118"
RUN pip install -U pip \
    && pip install torch==${PYTORCH}+cu${CUDA} torchvision==${TORCHVISION}+cu${CUDA} --index-url https://download.pytorch.org/whl/cu${CUDA} \
    && pip install cumm-cu${CUDA} spconv-cu${CUDA}

ARG MMDET3D="1.2.0"
ARG MMDET="3.0.0"
ARG MMCV="2.0.1"
RUN pip install -U pip \
    && pip install mmcv==${MMCV} -f https://download.openmmlab.com/mmcv/dist/cu${CUDA}/torch${PYTORCH}/index.html \
    && pip install --no-cache-dir mmdet3d==${MMDET3D} mmdet==${MMDET}

ARG USER_ID
ARG GROUP_ID
ENV DOCKER_USER adrian

RUN mkdir -p /work_dir; \
    addgroup --gid $GROUP_ID ${DOCKER_USER} \
    && adduser --disabled-password --gecos '' --uid $USER_ID --gid $GROUP_ID ${DOCKER_USER} \
    && adduser ${DOCKER_USER} sudo \
    && echo "${DOCKER_USER} ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/${DOCKER_USER} \
    && chmod 0440 /etc/sudoers.d/${DOCKER_USER} \
    && chown ${DOCKER_USER}:${DOCKER_USER} -R /work_dir

USER ${DOCKER_USER}
WORKDIR /work_dir
CMD ["bash"]

