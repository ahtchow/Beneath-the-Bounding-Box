PROJECT ?= beneath-the-bounding-box

CURRENT_UID := $(shell id ${USER} -u)
CURRENT_GID := $(shell id ${USER} -g)

XSOCK=/tmp/.X11-unix
XAUTH=/tmp/.docker.xauth
DOCKER_OPTS := \
	--name ${PROJECT} \
	--rm -it \
	-u ${CURRENT_UID}:${CURRENT_GID} \
    -v /etc/passwd:/etc/passwd:ro \
    -v /etc/group:/etc/group:ro \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -v ${HOME}/.Xauthority:${HOME}/.Xauthority \
    -v ${HOME}/.Xauthority:/root/.Xauthority \
    -e DISPLAY \
	--ipc=host \
    --net=host

DOCKER_OPTS_GPU := \
	--runtime nvidia \
	--gpus all \

NVIDIA_DOCKER :=$(shell dpkg -l | grep nvidia-container-toolkit 2>/dev/null)
DOCKER_IMAGE := ${PROJECT}

ifdef NVIDIA_DOCKER
	DOCKER_IMAGE :="${DOCKER_IMAGE}-nv"
	DOCKER_OPTS :=${DOCKER_OPTS_GPU} ${DOCKER_OPTS}
endif

build-base:
	docker build \
		-f docker/base.Dockerfile \
		-t btbb-base .

build-SST:
	docker build \
		-f docker/SST.Dockerfile \
		-t ${USER}sst-base .

exec-SST:
	docker run \
		--runtime nvidia ${DOCKER_OPTS} \
		-v $${PWD}/repos/SST:/work_dir/SST \
		-v ${DATASET_ROOT}:/work_dir/datasets \
		-v $${PWD}/docker_home:/home/${USER} \
		${USER}/sst-base
