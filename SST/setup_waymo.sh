#!/bin/bash

HOME="/work_dir"
SST_PATH="${HOME}/SST"

# Symbolically Link Waymo Dataset
WAYMO_DATA_PATH="${SST_PATH}/data/waymo"
if [ -d $WAYMO_DATA_PATH ]; then
    echo "Waymo Dataset already Symbolically Linked!"
else
    mkdir -p data/waymo
    ln -s ${HOME}/datasets/waymo/mmdet3d_format/kitti_format ${WAYMO_DATA_PATH}
fi
