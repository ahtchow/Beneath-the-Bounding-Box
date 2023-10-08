#!/bin/bash

HOME="/work_dir"
SST_PATH="${HOME}/SST"
WAYMO_OD_PATH="${HOME}/waymo-od"

# Symbolically Link Waymo Dataset
WAYMO_DATA_PATH="${SST_PATH}/data/waymo"
if [ -d $WAYMO_DATA_PATH ]; then
    echo "Waymo Dataset already Symbolically Linked!"
else
    mkdir -p data/waymo
    ln -s ${HOME}/datasets/waymo/mmdet3d_format/kitti_format ${WAYMO_DATA_PATH}
fi

# Update Compute Metrics File
cd ${WAYMO_OD_PATH}/src
HOME=${WAYMO_OD_PATH} bazel clean
HOME=${WAYMO_OD_PATH} bazel build waymo_open_dataset/metrics/tools/compute_detection_metrics_main
if [ -f ${SST_PATH}/mmdet3d/core/evaluation/waymo_utils/compute_detection_metrics_main ]; then
    chmod +w ${SST_PATH}/mmdet3d/core/evaluation/waymo_utils/compute_detection_metrics_main
fi
cp bazel-bin/waymo_open_dataset/metrics/tools/compute_detection_metrics_main ${SST_PATH}/mmdet3d/core/evaluation/waymo_utils/
cd ${SST_PATH}