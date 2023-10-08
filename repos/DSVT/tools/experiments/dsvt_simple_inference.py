#!/usr/bin/env python3
from pcdet.config import cfg, cfg_from_yaml_file
from pcdet.models import build_network, load_data_to_gpu
from pcdet.datasets import DatasetTemplate
from pcdet.utils import common_utils
from tools.visual_utils import open3d_vis_utils as V
import open3d
import os
import numpy as np
from pathlib import Path
import torch

class DemoDataset(DatasetTemplate):
    def __init__(self, dataset_cfg, class_names, training=True, root_path=None, logger=None, ext='.bin'):
        """
        Args:
            root_path:
            dataset_cfg:
            class_names:
            training:
            logger:
        """
        super().__init__(
            dataset_cfg=dataset_cfg, class_names=class_names, training=training, root_path=root_path, logger=logger
        )
        self.root_path = root_path
        self.ext = ext
        data_file_list = glob.glob(str(root_path / f'*{self.ext}')) if self.root_path.is_dir() else [self.root_path]

        data_file_list.sort()
        self.sample_file_list = data_file_list

    def __len__(self):
        return len(self.sample_file_list)

    def __getitem__(self, index):
        if self.ext == '.bin':
            # nuscenes
            points = np.fromfile(self.sample_file_list[index], dtype=np.float32).reshape(-1, 5)
        elif self.ext == '.npy':
            points = np.load(self.sample_file_list[index])
        else:
            raise NotImplementedError

        input_dict = {
            'points': points,
            'frame_id': index,
        }

        data_dict = self.prepare_data(data_dict=input_dict)
        return data_dict

def main():
    cfg_file = "cfgs/dsvt_models/dsvt_plain_1f_onestage_nusences.yaml"
    ckpt = "experiments/DSVT_Nuscenes_val.pth"
    data_path = "experiments/sample_data.bin"
    cfg_from_yaml_file(cfg_file, cfg)
    logger = common_utils.create_logger()
    logger.info('-----------------Quick Demo of DSVT-------------------------')
    demo_dataset = DemoDataset(
        dataset_cfg=cfg.DATA_CONFIG, class_names=cfg.CLASS_NAMES, training=False,
        root_path=Path(data_path), ext=".bin", logger=logger
    )
    logger.info(f'Total number of samples: \t{len(demo_dataset)}')
    model = build_network(model_cfg=cfg.MODEL, num_class=len(cfg.CLASS_NAMES), dataset=demo_dataset)
    model.load_params_from_file(filename=ckpt, logger=logger, to_cpu=False, pre_trained_path=None)
    model.eval()
    model.cuda()

    with torch.no_grad():
        for idx, data_dict in enumerate(demo_dataset):
            logger.info(f'Visualized sample index: \t{idx + 1}')
            data_dict = demo_dataset.collate_batch([data_dict])
            load_data_to_gpu(data_dict)
            import time
            for i in range(10):
                start_time = time.time()
                pred_dicts, _ = model.forward(data_dict)
                print(f"The function took {time.time() - start_time} seconds to complete")

            V.draw_scenes(
                points=data_dict['points'][:, 1:], ref_boxes=pred_dicts[0]['pred_boxes'],
                ref_scores=pred_dicts[0]['pred_scores'], ref_labels=pred_dicts[0]['pred_labels']
            )
        logger.info('Demo done.')

if __name__ == '__main__':
    main()