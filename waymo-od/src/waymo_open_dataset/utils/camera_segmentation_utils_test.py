# Copyright 2022 The Waymo Open Dataset Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Tests for keypoint_data."""
import numpy as np
import tensorflow as tf

# copybara removed file resource import
from waymo_open_dataset import dataset_pb2
from waymo_open_dataset.protos import camera_segmentation_pb2
from waymo_open_dataset.utils import camera_segmentation_utils


class CameraSegmentationUtilsTest(tf.test.TestCase):

  def setUp(self):
    super().setUp()
    self._proto1, self._proto2 = (
        self._get_test_camerasegmentationlabel_protos())

  def _get_test_data(self):
    # pylint: disable=line-too-long
    # pyformat: disable
    test_data_path = '{pyglib_resource}waymo_open_dataset/utils/testdata/pvps_data_one_frame.tfrecord'.format(pyglib_resource='')
    self._dataset = tf.data.TFRecordDataset(test_data_path, compression_type='')

  def _get_test_camerasegmentationlabel_protos(
      self,
      panoptic_label1=np.array([[[2001, 3002, 3002, 2001]]], dtype=np.uint16),
      panoptic_label2=np.array([[[2001, 4002, 4002, 2001]]], dtype=np.uint16)):
    panoptic_label_encoded1 = tf.io.encode_png(panoptic_label1).numpy()
    panoptic_label_encoded2 = tf.io.encode_png(panoptic_label2).numpy()
    proto1 = dataset_pb2.CameraSegmentationLabel()
    proto1.panoptic_label = panoptic_label_encoded1
    proto1.panoptic_label_divisor = 1000
    proto1.num_cameras_covered = tf.io.encode_png(
        np.ones_like(panoptic_label1, dtype=np.uint8)
    ).numpy()
    proto1.sequence_id = 'one'
    proto1.instance_id_to_global_id_mapping.append(
        dataset_pb2.CameraSegmentationLabel.InstanceIDToGlobalIDMapping(
            local_instance_id=1, global_instance_id=50, is_tracked=True))
    proto1.instance_id_to_global_id_mapping.append(
        dataset_pb2.CameraSegmentationLabel.InstanceIDToGlobalIDMapping(
            local_instance_id=2, global_instance_id=60, is_tracked=False))
    proto2 = dataset_pb2.CameraSegmentationLabel()
    proto2.panoptic_label_divisor = 1000
    proto2.num_cameras_covered = tf.io.encode_png(
        np.ones_like(panoptic_label2, dtype=np.uint8)).numpy()
    proto2.sequence_id = 'two'
    proto2.panoptic_label = panoptic_label_encoded2
    proto2.instance_id_to_global_id_mapping.append(
        dataset_pb2.CameraSegmentationLabel.InstanceIDToGlobalIDMapping(
            local_instance_id=1, global_instance_id=50, is_tracked=True))
    proto2.instance_id_to_global_id_mapping.append(
        dataset_pb2.CameraSegmentationLabel.InstanceIDToGlobalIDMapping(
            local_instance_id=2, global_instance_id=60, is_tracked=False))
    return [proto1, proto2]

  def test_generate_color_map(self):
    test_color_map = ({
        camera_segmentation_pb2.CameraSegmentation.TYPE_CAR:
            [10, 10, 10],
        camera_segmentation_pb2.CameraSegmentation.TYPE_PEDESTRIAN:
            [20, 20, 20],
    })
    color_map = camera_segmentation_utils._generate_color_map(
        test_color_map)
    expected_color_map = np.zeros(
        (camera_segmentation_pb2.CameraSegmentation.TYPE_PEDESTRIAN + 1, 3),
        dtype=np.uint8)
    expected_color_map[camera_segmentation_pb2.CameraSegmentation.TYPE_CAR] = 10
    expected_color_map[
        camera_segmentation_pb2.CameraSegmentation.TYPE_PEDESTRIAN] = 20
    self.assertAllEqual(color_map, expected_color_map)

  def test_decode_semantic_and_instance_labels_from_panoptic_label(self):
    panoptic_label = [32001, 53002, 0]
    semantic_label, instance_label = (
        camera_segmentation_utils
        .decode_semantic_and_instance_labels_from_panoptic_label(
            panoptic_label, 1000))
    self.assertAllEqual(semantic_label, [32, 53, 0])
    self.assertAllEqual(instance_label, [1, 2, 0])

  def test_encode_semantic_and_instance_labels_to_panoptic_label(self):
    semantic_label = [0, 23, 1, 2]
    instance_label = [1, 2, 5, 999]
    panoptic_label = camera_segmentation_utils.encode_semantic_and_instance_labels_to_panoptic_label(
        semantic_label, instance_label, 1000)
    self.assertAllEqual(panoptic_label, [1, 23002, 1005, 2999])

  def test_remap_global_ids(self):
    remapped_instance_ids = camera_segmentation_utils._remap_global_ids(
        (self._proto1, self._proto2), remap_to_sequential=True
    )
    self.assertEqual(remapped_instance_ids, {
        'one': {
            50: 1,
            60: 2
        },
        'two': {
            50: 3,
            60: 4
        }
    })

  def test_decode_single_panoptic_label_from_proto(self):
    panoptic_label = np.array([[[1, 23002, 1005, 2999]]], dtype=np.uint16)
    proto1, _ = self._get_test_camerasegmentationlabel_protos(
        panoptic_label1=panoptic_label)
    panoptic_label_decoded = (
        camera_segmentation_utils.decode_single_panoptic_label_from_proto(
            proto1))
    self.assertAllEqual(panoptic_label_decoded, panoptic_label)

  def test_decode_multi_frame_panoptic_labels_from_protos(self):
    decoded_elements = (
        camera_segmentation_utils
        .decode_multi_frame_panoptic_labels_from_protos(
            [self._proto1, self._proto2], remap_to_sequential=True))
    panoptic_labels, is_tracked_masks = decoded_elements[0:2]
    num_cameras_covered, panoptic_label_divisor = decoded_elements[2:4]
    expected_panoptic_labels = [
        np.array([[[2001, 3002, 3002, 2001]]], dtype=np.uint16),
        np.array([[[2003, 4004, 4004, 2003]]], dtype=np.uint16)
    ]
    expected_num_cameras_covered = [
        np.array([[[1, 1, 1, 1]]], dtype=np.uint8),
        np.array([[[1, 1, 1, 1]]], dtype=np.uint8)
    ]
    expected_is_tracked_masks = [
        np.array([[[1, 0, 0, 1]]], dtype=np.uint8),
        np.array([[[1, 0, 0, 1]]], dtype=np.uint8)
    ]
    self.assertAllEqual(panoptic_labels, expected_panoptic_labels)
    self.assertAllEqual(num_cameras_covered, expected_num_cameras_covered)
    self.assertAllEqual(is_tracked_masks, expected_is_tracked_masks)
    self.assertEqual(panoptic_label_divisor, 1000)

  def test_semantic_label_to_rgb(self):
    semantic_label = np.array([[0, 2, 1]])
    color_map = np.array([[0, 1, 2], [1, 2, 0], [2, 0, 1]])
    rgb = camera_segmentation_utils.semantic_label_to_rgb(
        semantic_label, color_map)
    self.assertAllEqual(rgb, [[color_map[0], color_map[2], color_map[1]]])

  def test_panoptic_label_to_rgb(self):
    semantic_label = np.array([[0, 2, 1]])
    color_map = np.array([[0, 1, 2], [1, 2, 0], [2, 0, 1]])
    instance_label = np.array([[1, 2, 1]])
    rgb = camera_segmentation_utils.panoptic_label_to_rgb(
        semantic_label, instance_label, color_map=color_map)
    expected_rgb = color_map[np.newaxis, [0, 2, 1]]
    self.assertAllEqual(rgb[..., [0, 2]], expected_rgb[..., [0, 2]])
    self.assertEqual(rgb[0, 0, 1], rgb[0, 2, 1])
    self.assertNotEqual(rgb[0, 0, 1], rgb[0, 1, 1])

  def test_save_panoptic_label_to_proto(self):
    # Test that saving to proto and decoding recovers the same label.
    semantic_label = np.array([1, 3, 4, 9])[np.newaxis, :, np.newaxis]
    instance_label = np.array([2, 4, 1, 2])[np.newaxis, :, np.newaxis]
    panoptic_label_divisor = 1000
    new_panoptic_label_divisor = 1023
    sequence_id = 'test'

    panoptic_label = semantic_label * panoptic_label_divisor + instance_label
    proto = camera_segmentation_utils.save_panoptic_label_to_proto(
        panoptic_label, panoptic_label_divisor=panoptic_label_divisor,
        sequence_id=sequence_id,
        new_panoptic_label_divisor=new_panoptic_label_divisor)
    decoded_panoptic_label, _, _, decoded_panoptic_label_divisor = (
        camera_segmentation_utils
        .decode_multi_frame_panoptic_labels_from_protos([proto]))
    expected_panoptic_label = (semantic_label * new_panoptic_label_divisor
                               + instance_label)
    self.assertEqual(sequence_id, proto.sequence_id)
    self.assertAllEqual(decoded_panoptic_label[0], expected_panoptic_label)
    self.assertEqual(new_panoptic_label_divisor, decoded_panoptic_label_divisor)

  def test_load_frames_with_labels_from_dataset(self):
    self._get_test_data()
    frames_with_seg, sequence_id = (
        camera_segmentation_utils.load_frames_with_labels_from_dataset(
            self._dataset
        )
    )
    self.assertLen(frames_with_seg, 1)
    self.assertIsNotNone(sequence_id)


if __name__ == '__main__':
  tf.test.main()
