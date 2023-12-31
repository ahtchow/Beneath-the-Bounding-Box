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
"""Tests for keypoint_metrics."""
import json
import math

import numpy as np
import tensorflow as tf

# copybara removed file resource import
from waymo_open_dataset.metrics.python import keypoint_metrics as _lib
from waymo_open_dataset.utils import keypoint_data as _data

# Values copied from `computeOks` from pycocotools package:
# https://github.com/matteorr/coco-analyze/blob/9eb8a0a9e57ad1e592661efc2b8964864c0e6f28/pycocotools/cocoeval.py#L216
# The order of keypoints is the same as in the testdata:
#   nose, left_eye, right_eye, left_ear, right_ear, left_shoulder,
#   right_shoulder, left_elbow, right_elbow, left_wrist, right_wrist, left_hip,
#   right_hip, left_knee, right_knee, left_ankle, right_ankle
# https://github.com/matteorr/coco-analyze/blob/9eb8a0a9e57ad1e592661efc2b8964864c0e6f28/pycocotools/cocoanalyze.py#L928
# Note we hardcode 5x values to match the `computeOks` constant, to get actual
# scales use `_coco_scales`.
_COCO_KEYPOINT_SCALES_5X = (.26, .25, .25, .35, .35, .79, .79, .72, .72, .62,
                            .62, 1.07, 1.07, .87, .87, .89, .89)

_LEFT_SHOULDER = _lib.KeypointType.KEYPOINT_TYPE_LEFT_SHOULDER
_RIGHT_SHOULDER = _lib.KeypointType.KEYPOINT_TYPE_RIGHT_SHOULDER


def _coco_scales():
  # We multiply all sigmas from the referenced implementation by 2x to make it
  # consistent with the definition of per keypoint scales.
  return [s / 5.0 for s in _COCO_KEYPOINT_SCALES_5X]


def _create_keypoints_tensors(testdata) -> _data.KeypointsTensors:
  location_and_visibility = tf.reshape(tf.constant(testdata), (-1, 3))
  return _data.KeypointsTensors(
      location=location_and_visibility[:, 0:2],
      visibility=location_and_visibility[:, 2])


def _create_bbox_tensors(testdata) -> _data.KeypointsTensors:
  bbox = tf.constant(testdata)
  top_left = bbox[:2]
  size = bbox[2:]
  return _data.BoundingBoxTensors(center=top_left + size / 2, size=size)


def _convert_sample(sample):
  # See the `testdata/README.md` for details about testdata format.
  gt = _create_keypoints_tensors(sample['ground_truth']['keypoints'])
  box = _create_bbox_tensors(sample['ground_truth']['bbox'])
  pr = _create_keypoints_tensors(sample['prediction']['keypoints'])
  return gt, pr, box, sample['oks']


def _load_testdata():
  """Loads all ground truth and predicted keypoints from testdata."""
  # pylint: disable=line-too-long
  # pyformat: disable
  testdata_path = '{pyglib_resource}waymo_open_dataset/metrics/python/testdata/oks_testdata.json'.format(pyglib_resource='')
  # pyformat: enable
  # pylint: enable=line-too-long
  with open(testdata_path) as f:
    return json.load(f)


def _convert_testdata(testdata):
  """Converts test data into keypoints."""
  converted = [_convert_sample(s) for s in testdata]
  gts, prs, boxes, scores = zip(*converted)
  return (_data.stack_keypoints(gts), _data.stack_keypoints(prs),
          _data.stack_boxes(boxes), scores)


class MiscTest(tf.test.TestCase):

  def test_box_displacement_returns_expected_shifts_for_outside_points_2d(self):
    # batch_size=2, num_points=4
    location = tf.constant(
        [[[0, 0], [2, 0], [4, 0], [0, 2]], [[4, 2], [0, 5], [2, 5], [4, 5]]],
        dtype=tf.float32)
    box = _data.BoundingBoxTensors(
        center=tf.constant([[2, 2.5], [2, 2.5]], dtype=tf.float32),
        size=tf.constant([[2, 3], [2, 3]], dtype=tf.float32))

    shift = _lib.box_displacement(location, box)

    self.assertAllClose(shift, [[[1, 1], [0, 1], [-1, 1], [1, 0]],
                                [[-1, 0], [1, -1], [0, -1], [-1, -1]]])

  def test_box_displacement_returns_expected_shifts_for_inside_points_2d(self):
    # batch_size=2, num_points=1
    location = tf.constant([[[2, 2]], [[2, 3]]], dtype=tf.float32)
    box = _data.BoundingBoxTensors(
        center=tf.constant([[2, 2.5], [2, 2.5]], dtype=tf.float32),
        size=tf.constant([[2, 3], [2, 3]], dtype=tf.float32))

    shift = _lib.box_displacement(location, box)

    self.assertAllClose(shift, [[[0, 0]], [[0, 0]]])


class AveragePrecisionAtOKSTest(tf.test.TestCase):

  def test_oks_returns_exactly_same_values_as_coco_eval(self):
    testdata = _load_testdata()
    gt, pr, gt_box, expected_scores = _convert_testdata(testdata)

    scores = _lib.object_keypoint_similarity(gt, pr, gt_box, _coco_scales())

    self.assertAllClose(scores, expected_scores)

  def test_oks_supports_unbatched_tensors(self):
    testdata = _load_testdata()
    gt, pr, gt_box, expected_score = _convert_sample(testdata[1])

    score = _lib.object_keypoint_similarity(gt, pr, gt_box, _coco_scales())

    self.assertAllClose(score, expected_score)

  def test_average_precision_returns_precision_at_all_thresholds(self):
    thresholds = [0.5, 0.9]
    # We assume that OKS computation is tested directly, so for checking the
    # metric computation we need just one keypoint with a simple scale.
    # batch_size=3, num_keypoints=1
    # For a single visible keypoint OKS = exp(- d^2 / (2*scale^2*k^2)), where
    # scale=sqrt(area) and k is a scale for a specific type of the keypoint.
    # We set per keypoint scale and object area in a way to make the denominator
    # equal to 1.0, so OKS = exp(-d^2). This way for a selected threshold h we
    # can find d = sqrt(-ln(h))
    per_type_scales = [1.0 / math.sqrt(2)]
    gt = _data.KeypointsTensors(
        location=tf.constant([[[1.0, 1.0]], [[2.0, 2.0]], [[3.0, 3.0]]]),
        visibility=tf.constant([[2], [2], [2]]))
    d = lambda h: math.sqrt(-math.log(h))
    # Shift predictions by a delta to get required threshold value.
    pr = _data.KeypointsTensors(
        location=gt.location +
        tf.constant([[[d(0.25), 0.0]], [[d(0.7), 0.0]], [[d(0.95), 0.0]]]),
        visibility=tf.constant([[2.0], [2.0], [2.0]]))
    box = _data.BoundingBoxTensors(
        center=gt.location[:, 0, :],
        size=tf.constant([[1.0, 1.0], [1.0, 1.0], [1.0, 1.0]]))

    ap = _lib.AveragePrecisionAtOKS(
        per_type_scales,
        thresholds,
        name='All Points',
        precision_format='{name} P @ {threshold:.1f}',
        average_precision_format='{name} AP')

    with self.subTest(name='correct_mean_values'):
      ap.reset_state()
      ap.update_state([gt, pr, box])
      metrics = ap.result()

      self.assertIsInstance(metrics, dict)
      self.assertEqual(
          metrics.keys(),
          set(['All Points P @ 0.5', 'All Points P @ 0.9', 'All Points AP']))
      self.assertNear(metrics['All Points P @ 0.5'], 2.0 / 3, err=1e-5)
      self.assertNear(metrics['All Points P @ 0.9'], 1.0 / 3, err=1e-5)
      self.assertNear(metrics['All Points AP'], 1.0 / 2, err=1e-5)

    with self.subTest(name='respects_sample_weights'):
      # Weights for each keypoint.
      sample_weight = tf.constant([[0.0], [1.0], [1.0]])
      ap.reset_state()
      ap.update_state([gt, pr, box], sample_weight=sample_weight)
      metrics = ap.result()

      self.assertNear(metrics['All Points P @ 0.5'], 1.0, err=1e-5)
      self.assertNear(metrics['All Points P @ 0.9'], 0.5, err=1e-5)
      self.assertNear(metrics['All Points AP'], 0.75, err=1e-5)


class MpjpeTest(tf.test.TestCase):

  def test_returns_mean_square_error_for_all_keypoints(self):
    # batch_size = 3, num_points = 2
    gt = _data.KeypointsTensors(
        location=tf.constant([[[1.0, 1.0], [-1.0, -1.0]],
                              [[2.0, 2.0], [-2.0, -2.0]],
                              [[3.0, 3.0], [-3.0, -3.0]]]),
        visibility=tf.constant([[2, 2], [2, 2], [2, 2]]))
    # Predicted points are [1, 2, 3, 4, 5, 6] pixels away from ground truth.
    pr = _data.KeypointsTensors(
        location=tf.constant([[[1.0, 0.0], [1.0, -1.0]],
                              [[2.0, -1.0], [2.0, -2.0]],
                              [[3.0, -2.0], [-3.0, 3.0]]]),
        visibility=tf.constant([[2, 2], [2, 2], [2, 2]]))
    box = None  # is not used by the metric

    mpjpe = _lib.MeanPerJointPositionError(name='MPJPE')
    mpjpe.update_state([gt, pr, box])
    metrics = mpjpe.result()

    self.assertNear(metrics['MPJPE'], (1 + 2 + 3 + 4 + 5 + 6) / 6, err=1e-5)

  def test_takes_into_account_keypoint_visibility(self):
    # batch_size = 3, num_points = 2
    gt = _data.KeypointsTensors(
        location=tf.constant([[[1.0, 1.0], [-1.0, -1.0]],
                              [[2.0, 2.0], [-2.0, -2.0]],
                              [[3.0, 3.0], [-3.0, -3.0]]]),
        visibility=tf.constant([[1.0, 2.0], [0.0, 2.0], [2.0, 0.0]]))
    # Predicted points are [1, 2, 3, 4, 5, 6] pixels away from ground truth.
    pr = _data.KeypointsTensors(
        location=tf.constant([[[1.0, 0.0], [1.0, -1.0]],
                              [[2.0, -1.0], [2.0, -2.0]],
                              [[3.0, -2.0], [-3.0, 3.0]]]),
        visibility=tf.constant([[2, 2], [2, 2], [2, 2]]))
    box = None  # is not used by the metric

    mpjpe = _lib.MeanPerJointPositionError(name='MPJPE')
    mpjpe.update_state([gt, pr, box])
    metrics = mpjpe.result()

    self.assertNear(metrics['MPJPE'], (1 + 2 + 0 + 4 + 5 + 0) / 4, err=1e-5)

  def test_respects_sample_weights(self):
    # batch_size = 3, num_points = 2
    gt = _data.KeypointsTensors(
        location=tf.constant([[[1.0, 1.0], [-1.0, -1.0]],
                              [[2.0, 2.0], [-2.0, -2.0]],
                              [[3.0, 3.0], [-3.0, -3.0]]]),
        visibility=tf.constant([[2, 2], [0, 2], [2, 0]]))
    # Predicted points are [1, 2, 3, 4, 5, 6] pixels away from ground truth.
    pr = _data.KeypointsTensors(
        location=tf.constant([[[1.0, 0.0], [1.0, -1.0]],
                              [[2.0, -1.0], [2.0, -2.0]],
                              [[3.0, -2.0], [-3.0, 3.0]]]),
        visibility=tf.constant([[2, 2], [2, 2], [2, 2]]))
    box = None  # is not used by the metric
    sample_weight = tf.constant([0.0, 0.5, 1.0])

    mpjpe = _lib.MeanPerJointPositionError(name='MPJPE')
    mpjpe.update_state([gt, pr, box], sample_weight=sample_weight)
    metrics = mpjpe.result()

    self.assertNear(
        metrics['MPJPE'], (0 + 0 + 0 + 4 * 0.5 + 5 * 1.0 + 0) / (0.5 + 1.0),
        err=1e-5)


class PckTest(tf.test.TestCase):

  def test_returns_correct_result_for_a_large_abs_threshold_value(self):
    # batch_size = 3, num_points = 2
    gt = _data.KeypointsTensors(
        location=tf.constant([[[1.0, 1.0], [-1.0, -1.0]],
                              [[2.0, 2.0], [-2.0, -2.0]],
                              [[3.0, 3.0], [-3.0, -3.0]]]),
        visibility=tf.constant([[2, 2], [2, 2], [2, 2]]))
    # Predicted points are [1, 2, 3, 4, 5, 6] pixels away from ground truth.
    pr = _data.KeypointsTensors(
        location=tf.constant([[[1.0, 0.0], [1.0, -1.0]],
                              [[2.0, -1.0], [2.0, -2.0]],
                              [[3.0, -2.0], [-3.0, 3.0]]]),
        visibility=tf.constant([[2, 2], [2, 2], [2, 2]]))
    box = None  # is not used by the metric

    pck = _lib.PercentageOfCorrectKeypoints(name='PCK', thresholds=[10])
    pck.update_state([gt, pr, box])
    metrics = pck.result()

    self.assertNear(metrics['PCK @ 10.00'], 1.0, err=1e-5)

  def test_returns_correct_results_for_multiple_thresholds(self):
    # batch_size = 3, num_points = 2
    gt = _data.KeypointsTensors(
        location=tf.constant([[[1.0, 1.0], [-1.0, -1.0]],
                              [[2.0, 2.0], [-2.0, -2.0]],
                              [[3.0, 3.0], [-3.0, -3.0]]]),
        visibility=tf.constant([[2, 2], [2, 2], [2, 2]]))
    # Predicted points are [1, 2, 3, 4, 5, 6] pixels away from ground truth.
    pr = _data.KeypointsTensors(
        location=tf.constant([[[1.0, 0.0], [1.0, -1.0]],
                              [[2.0, -1.0], [2.0, -2.0]],
                              [[3.0, -2.0], [-3.0, 3.0]]]),
        visibility=tf.constant([[2, 2], [2, 2], [2, 2]]))
    box = None  # is not used by the metric

    pck = _lib.PercentageOfCorrectKeypoints(name='PCK', thresholds=[2, 5])
    pck.update_state([gt, pr, box])
    metrics = pck.result()

    self.assertCountEqual(metrics.keys(), ['PCK @ 2.00', 'PCK @ 5.00'])
    self.assertNear(metrics['PCK @ 2.00'], 2 / 6, err=1e-5)
    self.assertNear(metrics['PCK @ 5.00'], 5 / 6, err=1e-5)

  def test_takes_into_account_keypoint_visibility_abs_threshold(self):
    # batch_size = 3, num_points = 2
    gt = _data.KeypointsTensors(
        location=tf.constant([[[1.0, 1.0], [-1.0, -1.0]],
                              [[2.0, 2.0], [-2.0, -2.0]],
                              [[3.0, 3.0], [-3.0, -3.0]]]),
        visibility=tf.constant([[2, 2], [2, 2], [2, 0]]))
    # Predicted points are [1, 2, 3, 4, 5, 6] pixels away from ground truth.
    pr = _data.KeypointsTensors(
        location=tf.constant([[[1.0, 0.0], [1.0, -1.0]],
                              [[2.0, -1.0], [2.0, -2.0]],
                              [[3.0, -2.0], [-3.0, 3.0]]]),
        visibility=tf.constant([[1, 2], [2, 2], [2, 2]]))
    box = None  # is not used by the metric

    pck = _lib.PercentageOfCorrectKeypoints(thresholds=[4], name='PCK')
    pck.update_state([gt, pr, box])
    metrics = pck.result()

    self.assertNear(metrics['PCK @ 4.00'], 0.8, err=1e-5)

  def test_takes_respects_sample_weights_abs_threshold(self):
    # batch_size = 3, num_points = 2
    gt = _data.KeypointsTensors(
        location=tf.constant([[[1.0, 1.0], [-1.0, -1.0]],
                              [[2.0, 2.0], [-2.0, -2.0]],
                              [[3.0, 3.0], [-3.0, -3.0]]]),
        visibility=tf.constant([[2, 2], [0, 2], [2, 0]]))
    # Predicted points are [1, 2, 3, 4, 5, 6] pixels away from ground truth.
    pr = _data.KeypointsTensors(
        location=tf.constant([[[1.0, 0.0], [1.0, -1.0]],
                              [[2.0, -1.0], [2.0, -2.0]],
                              [[3.0, -2.0], [-3.0, 3.0]]]),
        visibility=tf.constant([[2, 2], [2, 2], [2, 2]]))
    box = None  # is not used by the metric
    sample_weight = tf.constant([0.0, 1.0, 1.0])

    pck = _lib.PercentageOfCorrectKeypoints(thresholds=[4.0], name='PCK')
    pck.update_state([gt, pr, box], sample_weight=sample_weight)
    metrics = pck.result()

    # The weights exclude 2 keypoints from the sample #0, visibility mask in
    # samples #1 and #2 excludes 2 more. Only one out of two keypoints left is
    # closer than 4 pixels to the ground truth.
    self.assertNear(metrics['PCK @ 4.00'], 1 / 2, err=1e-5)

  def test_returns_correct_result_when_using_object_scale(self):
    # batch_size = 3, num_points = 2
    gt = _data.KeypointsTensors(
        location=tf.constant([[[1.0, 1.0], [-1.0, -1.0]],
                              [[2.0, 2.0], [-2.0, -2.0]],
                              [[3.0, 3.0], [-3.0, -3.0]]]),
        visibility=tf.constant([[2, 2], [2, 2], [2, 2]]))
    # Predicted points are [[1, 2], [3, 4], [5, 6]] px away from ground truth.
    pr = _data.KeypointsTensors(
        location=tf.constant([[[1.0, 0.0], [1.0, -1.0]],
                              [[2.0, -1.0], [2.0, -2.0]],
                              [[3.0, -2.0], [-3.0, 3.0]]]),
        visibility=tf.constant([[2, 2], [2, 2], [2, 2]]))
    # Objects scales are: 1, 10, 20
    box = _data.BoundingBoxTensors(
        center=tf.constant([[0.0, 0.0], [0.0, 0.0], [0.0, 0.0]]),
        size=tf.constant([[1.0, 1.0], [10.0, 10.0], [20.0, 20.0]]))

    pck = _lib.PercentageOfCorrectKeypoints(
        name='PCK', thresholds=[0.5], use_object_scale=True)
    pck.update_state([gt, pr, box])
    metrics = pck.result()

    self.assertNear(
        metrics['PCK @ 0.50'], (0 + 0 + 1 + 1 + 1 + 1) / 6, err=1e-5)

  def test_returns_correct_result_when_using_keypoint_scale(self):
    # batch_size = 3, num_points = 2
    gt = _data.KeypointsTensors(
        location=tf.constant([[[1.0, 1.0], [-1.0, -1.0]],
                              [[2.0, 2.0], [-2.0, -2.0]],
                              [[3.0, 3.0], [-3.0, -3.0]]]),
        visibility=tf.constant([[2, 2], [2, 2], [2, 2]]))
    # Predicted points are [[1, 2], [3, 4], [5, 6]] px away from ground truth.
    pr = _data.KeypointsTensors(
        location=tf.constant([[[1.0, 0.0], [1.0, -1.0]],
                              [[2.0, -1.0], [2.0, -2.0]],
                              [[3.0, -2.0], [-3.0, 3.0]]]),
        visibility=tf.constant([[2, 2], [2, 2], [2, 2]]))
    # Objects scales are: 1, 10, 20
    box = _data.BoundingBoxTensors(
        center=tf.constant([[0.0, 0.0], [0.0, 0.0], [0.0, 0.0]]),
        size=tf.constant([[1.0, 1.0], [10.0, 10.0], [20.0, 20.0]]))
    per_type_scales = [1.0, 0.5]

    pck = _lib.PercentageOfCorrectKeypoints(
        name='PCK',
        thresholds=[0.5],
        per_type_scales=per_type_scales,
        use_object_scale=True)
    pck.update_state([gt, pr, box])
    metrics = pck.result()

    # NOTE: Effective absolute thresholds for all keypoints will be:
    #   [[0.5 * 1.0 * 1.0 = 0.5, 0.5 * 1.0 * 0.5 = 0.25],
    #    [0.5 * 10.0 * 1.0 = 5.0, 0.5 * 10.0 * 0.5 = 2.5],
    #    [0.5 * 20.0 * 1.0 = 10., 0.5 * 20.0 * 0.5 = 5]]
    # So the second keypoints in all samples are not OK now, compared to the
    # `test_returns_correct_result_when_using_object_scale` test case.
    self.assertNear(
        metrics['PCK @ 0.50'], (0 + 0 + 1 + 0 + 1 + 0) / 6, err=1e-5)

  def test_returns_correct_result_when_using_absolute_keypoint_scales(self):
    # batch_size = 3, num_points = 2
    gt = _data.KeypointsTensors(
        location=tf.constant([[[1.0, 1.0], [-1.0, -1.0]],
                              [[2.0, 2.0], [-2.0, -2.0]],
                              [[3.0, 3.0], [-3.0, -3.0]]]),
        visibility=tf.constant([[2, 2], [2, 2], [2, 2]]))
    # Predicted points are [[1, 2], [3, 4], [5, 6]] px away from ground truth.
    pr = _data.KeypointsTensors(
        location=tf.constant([[[1.0, 0.0], [1.0, -1.0]],
                              [[2.0, -1.0], [2.0, -2.0]],
                              [[3.0, -2.0], [-3.0, 3.0]]]),
        visibility=tf.constant([[2, 2], [2, 2], [2, 2]]))
    box = None  # is not used by the metric
    per_type_scales = [4, 6]

    pck = _lib.PercentageOfCorrectKeypoints(
        name='PCK',
        thresholds=[0.5],
        per_type_scales=per_type_scales,
        use_object_scale=False)
    pck.update_state([gt, pr, box])
    metrics = pck.result()

    # NOTE: Effective absolute thresholds for keypoint types will be:
    #   [0.5 * 4 = 2, 0.5 * 6 = 3] in all samples in the batch.
    self.assertNear(
        metrics['PCK @ 0.50'], (1 + 1 + 0 + 0 + 0 + 0) / 6, err=1e-5)


class MetricForSubsetsTest(tf.test.TestCase):

  def test_returns_results_for_all_subsets(self):
    # batch_size = 3, num_points = 2
    gt = _data.KeypointsTensors(
        location=tf.constant([[[1.0, 1.0], [-1.0, -1.0]],
                              [[2.0, 2.0], [-2.0, -2.0]],
                              [[3.0, 3.0], [-3.0, -3.0]]]),
        visibility=tf.constant([[2, 2], [2, 2], [2, 2]]))
    # Predicted points are [1, 2, 3, 4, 5, 6] pixels away from ground truth.
    pr = _data.KeypointsTensors(
        location=tf.constant([[[1.0, 0.0], [1.0, -1.0]],
                              [[2.0, -1.0], [2.0, -2.0]],
                              [[3.0, -2.0], [-3.0, 3.0]]]),
        visibility=tf.constant([[2, 2], [2, 2], [2, 2]]))
    box = None  # is not used by the metric
    src_order = (_LEFT_SHOULDER, _RIGHT_SHOULDER)
    subsets = {
        'LEFT': (_LEFT_SHOULDER,),
        'RIGHT': (_RIGHT_SHOULDER,),
    }
    create_mpjpe = lambda n: _lib.MeanPerJointPositionError(name=f'MPJPE/{n}')

    metric = _lib.MetricForSubsets(
        src_order=src_order, subsets=subsets, create_metric_fn=create_mpjpe)
    metric.update_state([gt, pr, box])
    result = metric.result()

    self.assertCountEqual(result.keys(), ['MPJPE/LEFT', 'MPJPE/RIGHT'])
    self.assertNear(result['MPJPE/LEFT'], (1 + 3 + 5) / 3, err=1e-5)
    self.assertNear(result['MPJPE/RIGHT'], (2 + 4 + 6) / 3, err=1e-5)


class CombinedMetricTest(tf.test.TestCase):

  def test_returns_results_from_all_metrics(self):
    gt = _data.KeypointsTensors(
        location=tf.constant([[[1.0, 1.0], [-1.0, -1.0]],
                              [[2.0, 2.0], [-2.0, -2.0]],
                              [[3.0, 3.0], [-3.0, -3.0]]]),
        visibility=tf.constant([[2, 2], [2, 2], [2, 2]]))
    # Predicted points are [1, 2, 3, 4, 5, 6] pixels away from ground truth.
    pr = _data.KeypointsTensors(
        location=tf.constant([[[1.0, 0.0], [1.0, -1.0]],
                              [[2.0, -1.0], [2.0, -2.0]],
                              [[3.0, -2.0], [-3.0, 3.0]]]),
        visibility=tf.constant([[2, 2], [2, 2], [2, 2]]))
    box = None  # is not used by the metric
    mpjpe = _lib.MeanPerJointPositionError(name='MPJPE')
    pck = _lib.PercentageOfCorrectKeypoints(name='PCK', thresholds=[10])

    metric = _lib.CombinedMetric([mpjpe, pck])
    metric.update_state([gt, pr, box])
    result = metric.result()

    self.assertCountEqual(result.keys(), ['MPJPE', 'PCK @ 10.00'])


def _random_keypoints(batch_size, num_points, dims=2):
  return _data.KeypointsTensors(
      location=tf.random.uniform((batch_size, num_points, dims)),
      visibility=tf.random.uniform((batch_size, num_points),
                                   minval=0,
                                   maxval=2,
                                   dtype=tf.int32))


def _random_box(batch_size, dims=2):
  return _data.BoundingBoxTensors(
      center=tf.random.uniform((batch_size, dims)),
      size=tf.random.uniform((batch_size, dims)))


def _random_inputs(batch_size, num_points, dims=2):
  gt = _random_keypoints(batch_size, num_points, dims=dims)
  pr = _random_keypoints(batch_size, num_points, dims=dims)
  box = _random_box(batch_size, dims=dims)
  return gt, pr, box


_ALL_METRIC_NAMES = (
    'MPJPE/SHOULDERS', 'MPJPE/ELBOWS', 'MPJPE/WRISTS', 'MPJPE/HIPS',
    'MPJPE/KNEES', 'MPJPE/ANKLES', 'MPJPE/ALL', 'MPJPE/HEAD',
    'PCK/SHOULDERS @ 0.05', 'PCK/SHOULDERS @ 0.10', 'PCK/SHOULDERS @ 0.20',
    'PCK/SHOULDERS @ 0.30', 'PCK/SHOULDERS @ 0.40', 'PCK/SHOULDERS @ 0.50',
    'PCK/ELBOWS @ 0.05', 'PCK/ELBOWS @ 0.10', 'PCK/ELBOWS @ 0.20',
    'PCK/ELBOWS @ 0.30', 'PCK/ELBOWS @ 0.40', 'PCK/ELBOWS @ 0.50',
    'PCK/WRISTS @ 0.05', 'PCK/WRISTS @ 0.10', 'PCK/WRISTS @ 0.20',
    'PCK/WRISTS @ 0.30', 'PCK/WRISTS @ 0.40', 'PCK/WRISTS @ 0.50',
    'PCK/HIPS @ 0.05', 'PCK/HIPS @ 0.10', 'PCK/HIPS @ 0.20', 'PCK/HIPS @ 0.30',
    'PCK/HIPS @ 0.40', 'PCK/HIPS @ 0.50', 'PCK/KNEES @ 0.05',
    'PCK/KNEES @ 0.10', 'PCK/KNEES @ 0.20', 'PCK/KNEES @ 0.30',
    'PCK/KNEES @ 0.40', 'PCK/KNEES @ 0.50', 'PCK/ANKLES @ 0.05',
    'PCK/ANKLES @ 0.10', 'PCK/ANKLES @ 0.20', 'PCK/ANKLES @ 0.30',
    'PCK/ANKLES @ 0.40', 'PCK/ANKLES @ 0.50', 'PCK/ALL @ 0.05',
    'PCK/ALL @ 0.10', 'PCK/ALL @ 0.20', 'PCK/ALL @ 0.30', 'PCK/ALL @ 0.40',
    'PCK/ALL @ 0.50', 'PCK/HEAD @ 0.05', 'PCK/HEAD @ 0.10', 'PCK/HEAD @ 0.20',
    'PCK/HEAD @ 0.30', 'PCK/HEAD @ 0.40', 'PCK/HEAD @ 0.50',
    'OKS/SHOULDERS P @ 0.50', 'OKS/SHOULDERS P @ 0.55',
    'OKS/SHOULDERS P @ 0.60', 'OKS/SHOULDERS P @ 0.65',
    'OKS/SHOULDERS P @ 0.70', 'OKS/SHOULDERS P @ 0.75',
    'OKS/SHOULDERS P @ 0.80', 'OKS/SHOULDERS P @ 0.85',
    'OKS/SHOULDERS P @ 0.90', 'OKS/SHOULDERS P @ 0.95', 'OKS/SHOULDERS AP',
    'OKS/ELBOWS P @ 0.50', 'OKS/ELBOWS P @ 0.55', 'OKS/ELBOWS P @ 0.60',
    'OKS/ELBOWS P @ 0.65', 'OKS/ELBOWS P @ 0.70', 'OKS/ELBOWS P @ 0.75',
    'OKS/ELBOWS P @ 0.80', 'OKS/ELBOWS P @ 0.85', 'OKS/ELBOWS P @ 0.90',
    'OKS/ELBOWS P @ 0.95', 'OKS/ELBOWS AP', 'OKS/WRISTS P @ 0.50',
    'OKS/WRISTS P @ 0.55', 'OKS/WRISTS P @ 0.60', 'OKS/WRISTS P @ 0.65',
    'OKS/WRISTS P @ 0.70', 'OKS/WRISTS P @ 0.75', 'OKS/WRISTS P @ 0.80',
    'OKS/WRISTS P @ 0.85', 'OKS/WRISTS P @ 0.90', 'OKS/WRISTS P @ 0.95',
    'OKS/WRISTS AP', 'OKS/HIPS P @ 0.50', 'OKS/HIPS P @ 0.55',
    'OKS/HIPS P @ 0.60', 'OKS/HIPS P @ 0.65', 'OKS/HIPS P @ 0.70',
    'OKS/HIPS P @ 0.75', 'OKS/HIPS P @ 0.80', 'OKS/HIPS P @ 0.85',
    'OKS/HIPS P @ 0.90', 'OKS/HIPS P @ 0.95', 'OKS/HIPS AP',
    'OKS/KNEES P @ 0.50', 'OKS/KNEES P @ 0.55', 'OKS/KNEES P @ 0.60',
    'OKS/KNEES P @ 0.65', 'OKS/KNEES P @ 0.70', 'OKS/KNEES P @ 0.75',
    'OKS/KNEES P @ 0.80', 'OKS/KNEES P @ 0.85', 'OKS/KNEES P @ 0.90',
    'OKS/KNEES P @ 0.95', 'OKS/KNEES AP', 'OKS/ANKLES P @ 0.50',
    'OKS/ANKLES P @ 0.55', 'OKS/ANKLES P @ 0.60', 'OKS/ANKLES P @ 0.65',
    'OKS/ANKLES P @ 0.70', 'OKS/ANKLES P @ 0.75', 'OKS/ANKLES P @ 0.80',
    'OKS/ANKLES P @ 0.85', 'OKS/ANKLES P @ 0.90', 'OKS/ANKLES P @ 0.95',
    'OKS/ANKLES AP', 'OKS/ALL P @ 0.50', 'OKS/ALL P @ 0.55', 'OKS/ALL P @ 0.60',
    'OKS/ALL P @ 0.65', 'OKS/ALL P @ 0.70', 'OKS/ALL P @ 0.75',
    'OKS/ALL P @ 0.80', 'OKS/ALL P @ 0.85', 'OKS/ALL P @ 0.90',
    'OKS/ALL P @ 0.95', 'OKS/ALL AP', 'OKS/HEAD P @ 0.50', 'OKS/HEAD P @ 0.55',
    'OKS/HEAD P @ 0.60', 'OKS/HEAD P @ 0.65', 'OKS/HEAD P @ 0.70',
    'OKS/HEAD P @ 0.75', 'OKS/HEAD P @ 0.80', 'OKS/HEAD P @ 0.85',
    'OKS/HEAD P @ 0.90', 'OKS/HEAD P @ 0.95', 'OKS/HEAD AP')


class AllMetricsTest(tf.test.TestCase):
  maxDiff = 10000

  def test_all_metrics_for_camera_returns_results_with_expected_names(self):
    gt, pr, box = _random_inputs(batch_size=3, num_points=14)

    metric = _lib.create_combined_metric(_lib.DEFAULT_CONFIG_CAMERA)
    metric.update_state([gt, pr, box])
    result = metric.result()

    self.assertCountEqual(result.keys(), _ALL_METRIC_NAMES)

  def test_all_metrics_for_laser_returns_expected_number_of_results(self):
    gt, pr, box = _random_inputs(batch_size=3, num_points=14)

    metric = _lib.create_combined_metric(_lib.DEFAULT_CONFIG_LASER)
    metric.update_state([gt, pr, box])
    result = metric.result()

    self.assertCountEqual(result.keys(), _ALL_METRIC_NAMES)

  def test_all_metrics_for_all_returns_expected_number_of_results(self):
    gt, pr, box = _random_inputs(batch_size=3, num_points=15)

    metric = _lib.create_combined_metric(_lib.DEFAULT_CONFIG_ALL)
    metric.update_state([gt, pr, box])
    result = metric.result()

    self.assertCountEqual(result.keys(), _ALL_METRIC_NAMES)


class MissingIdsTest(tf.test.TestCase):

  def test_missing_ids_empty_if_nothing_is_missing(self):
    ids = tf.constant([0, 1, 2], dtype=tf.int32)
    missing = _lib.missing_ids(ids, count=3)
    self.assertEqual(missing.numpy().tolist(), [])

  def test_missing_ids_is_correct(self):
    ids = tf.constant([1, 3, 5], dtype=tf.int32)
    missing = _lib.missing_ids(ids, count=6)
    self.assertEqual(missing.numpy().tolist(), [0, 2, 4])


class MatchPoseEstimationsTest(tf.test.TestCase):

  def test_keeps_gt_as_is(self):
    # 3 objects with 3 keypoints each:
    gt_kp = _data.KeypointsTensors(
        location=tf.constant(
            [
                [[1, 1, 1], [2, 2, 2], [3, 3, 3]],
                [[4, 4, 4], [5, 5, 5], [6, 6, 6]],
                [[7, 7, 7], [8, 8, 8], [9, 9, 9]],
            ],
            dtype=tf.float32,
        ),
        visibility=tf.constant([[2, 2, 2], [2, 2, 2], [2, 2, 2]]),
    )
    gt_box = _data.BoundingBoxTensors(
        center=gt_kp.location[:, 0, :],
        size=tf.constant([[1, 1, 1], [1, 1, 1], [1, 1, 1]], dtype=tf.float32),
        heading=tf.constant([0.1, 0.2, 0.3], dtype=tf.float32),
    )
    gt = _data.PoseEstimationTensors(keypoints=gt_kp, box=gt_box)

    gtm, prm = _lib.match_pose_estimations(gt, gt)

    self.assertAllClose(gtm.keypoints.location, gt.keypoints.location)
    self.assertAllClose(gtm.keypoints.visibility, gt.keypoints.visibility)
    self.assertAllClose(gtm.box.center, gt.box.center)
    self.assertAllClose(gtm.box.size, gt.box.size)
    self.assertAllClose(gtm.box.heading, gt.box.heading)
    self.assertAllClose(gtm.keypoints.location, prm.keypoints.location)
    self.assertAllClose(gtm.keypoints.visibility, prm.keypoints.visibility)
    self.assertAllClose(gtm.box.center, prm.box.center)
    self.assertAllClose(gtm.box.size, prm.box.size)
    self.assertAllClose(gtm.box.heading, prm.box.heading)

  def test_reorders_pr_to_match_gr(self):
    # 3 objects with 1 keypoint each:
    gt_kp = _data.KeypointsTensors(
        location=tf.constant(
            [[[1, 1, 1]], [[4, 4, 4]], [[7, 7, 7]]],
            dtype=tf.float32,
        ),
        visibility=tf.constant([[2], [2], [2]]),
    )
    gt_box = _data.BoundingBoxTensors(
        center=gt_kp.location[:, 0, :],
        size=tf.constant([[1.1] * 3, [1.2] * 3, [1.3] * 3]),
        heading=tf.constant([0.1, 0.2, 0.3], dtype=tf.float32),
    )
    gt = _data.PoseEstimationTensors(keypoints=gt_kp, box=gt_box)
    # Predictions are the same, but reordered: 2, 0, 1
    reorder = lambda t: tf.gather(t, [2, 0, 1])
    pr_kp = _data.KeypointsTensors(
        location=reorder(gt_kp.location), visibility=reorder(gt_kp.visibility)
    )
    pr_box = _data.BoundingBoxTensors(
        center=reorder(gt_box.center),
        size=reorder(gt_box.size),
        heading=reorder(gt_box.heading),
    )
    pr = _data.PoseEstimationTensors(keypoints=pr_kp, box=pr_box)

    gtm, prm = _lib.match_pose_estimations(gt, pr)

    self.assertCountEqual(
        gtm.keypoints.location.numpy().flatten(),
        gt.keypoints.location.numpy().flatten(),
    )
    self.assertCountEqual(
        gtm.keypoints.visibility.numpy().flatten(),
        gt.keypoints.visibility.numpy().flatten(),
    )
    self.assertCountEqual(
        gtm.box.center.numpy().flatten(), gt.box.center.numpy().flatten()
    )
    self.assertCountEqual(
        gtm.box.size.numpy().flatten(), gt.box.size.numpy().flatten()
    )
    self.assertCountEqual(
        gtm.box.heading.numpy().flatten(), gt.box.heading.numpy().flatten()
    )
    self.assertAllClose(gtm.keypoints.location, prm.keypoints.location)
    self.assertAllClose(gtm.keypoints.visibility, prm.keypoints.visibility)
    self.assertAllClose(gtm.box.center, prm.box.center)
    self.assertAllClose(gtm.box.size, prm.box.size)
    self.assertAllClose(gtm.box.heading, prm.box.heading)

  def test_inexact_pr_to_gr_match(self):
    # 3 objects with 1 keypoint each:
    gt_kp = _data.KeypointsTensors(
        location=tf.constant(
            [[[1, 1, 1]], [[4, 4, 4]], [[7, 7, 7]]],
            dtype=tf.float32,
        ),
        visibility=tf.constant([[2], [2], [2]]),
    )
    gt_box = _data.BoundingBoxTensors(
        center=gt_kp.location[:, 0, :],
        size=tf.constant([[1.1] * 3, [1.2] * 3, [1.3] * 3]),
        heading=tf.constant([0.1, 0.2, 0.3], dtype=tf.float32),
    )
    gt = _data.PoseEstimationTensors(keypoints=gt_kp, box=gt_box)
    # Predicted boxes are similar to the gt ordered: 2, 0, 1
    pr_kp = _data.KeypointsTensors(
        location=tf.constant(
            [[[7, 7, 7]], [[1, 1, 1]], [[4, 4, 4]]],
            dtype=tf.float32,
        ),
        visibility=tf.constant([[2], [2], [2]]),
    )
    pr_box = _data.BoundingBoxTensors(
        center=tf.constant([[7.1, 7.1, 7.1], [0.9, 1.1, 1.1], [3.9, 4, 4.1]]),
        size=tf.constant([[1.2] * 3, [1.2] * 3, [1.2] * 3], dtype=tf.float32),
        heading=tf.constant([0.1, 0.1, 0.1], dtype=tf.float32),
    )
    pr = _data.PoseEstimationTensors(keypoints=pr_kp, box=pr_box)

    gt_m, pr_m = _lib.match_pose_estimations(gt, pr)

    # Spot checking coordinates to assert the order of objects.
    self.assertCountEqual(gt_m.keypoints.location[:, 0, 0].numpy(), [1, 4, 7])
    self.assertCountEqual(gt_m.box.center[:, 0].numpy(), [1, 4, 7])
    self.assertCountEqual(pr_m.keypoints.location[:, 0, 0].numpy(), [1, 4, 7])
    self.assertCountEqual(
        pr_m.box.center[:, 0].numpy(), np.asarray([0.9, 3.9, 7.1], np.float32)
    )
    self.assertAllClose(gt_m.keypoints.location, pr_m.keypoints.location)

  def test_appends_false_negatives_and_false_positives(self):
    # 2 object with 1 keypoint each:
    gt = _data.PoseEstimationTensors(
        keypoints=_data.KeypointsTensors(
            location=tf.constant(
                [[[1.5, 1.5, 1.5]], [[3.5, 3.5, 3.5]]], dtype=tf.float32
            ),
            visibility=tf.constant([[2], [2]]),
        ),
        box=_data.BoundingBoxTensors(
            center=tf.constant([[1, 1, 1], [3, 3, 3]], dtype=tf.float32),
            size=tf.constant([[1, 1, 1], [1, 1, 1]], dtype=tf.float32),
            heading=tf.constant([0.1, 0.1], dtype=tf.float32),
        ),
    )
    # 2 predicted boxes: one far away and one match.
    pr = _data.PoseEstimationTensors(
        keypoints=_data.KeypointsTensors(
            location=tf.constant(
                [[[10.5, 10.5, 10.5]], [[3.4, 3.4, 3.4]]], dtype=tf.float32
            ),
            visibility=tf.constant([[2], [2]]),
        ),
        box=_data.BoundingBoxTensors(
            center=tf.constant(
                [[10, 10, 10], [2.9, 2.9, 2.9]], dtype=tf.float32
            ),
            size=tf.constant([[1, 1, 1], [1, 1, 1]], dtype=tf.float32),
            heading=tf.constant([0.1, 0.2], dtype=tf.float32),
        ),
    )

    gt_m, pr_m = _lib.match_pose_estimations(gt, pr)

    # The order of objects: true positives, false negatives, false positives.
    self.assertAllClose(gt_m.keypoints.visibility, [[2], [2], [0]])
    self.assertAllClose(pr_m.keypoints.visibility, [[2], [0], [2]])
    # Check just the x coordinate to verify the order.
    self.assertAllClose(gt_m.box.center[:, 0], [3, 1, 0])
    self.assertAllClose(pr_m.box.center[:, 0], [2.9, 0, 10])

  def test_padds_correctly_even_if_pad_size_is_greater_than_orig_size(self):
    # Single object
    gt = _data.PoseEstimationTensors(
        keypoints=_data.KeypointsTensors(
            location=tf.constant([[[1.5, 2.5, 3.5]]], dtype=tf.float32),
            visibility=tf.constant([[2]]),
        ),
        box=_data.BoundingBoxTensors(
            center=tf.constant([[1.0, 2.0, 3.0]], dtype=tf.float32),
            size=tf.constant([[1, 1, 1]], dtype=tf.float32),
            heading=tf.constant([0.1], dtype=tf.float32),
        ),
    )
    # Two objects with the same box in the same center as the ground truth.
    pr = _data.PoseEstimationTensors(
        keypoints=_data.KeypointsTensors(
            location=tf.constant(
                [[[1.5, 2.5, 3.5]], [[1.4, 2.4, 3.4]]], dtype=tf.float32
            ),
            visibility=tf.constant([[2], [2]]),
        ),
        box=_data.BoundingBoxTensors(
            center=tf.constant([[1, 2, 3], [1, 2, 3]], dtype=tf.float32),
            size=tf.constant([[5, 4, 5], [5, 4, 6]], dtype=tf.float32),
            heading=tf.constant([0.001, 0.001], dtype=tf.float32),
        ),
    )

    gt_m, pr_m = _lib.match_pose_estimations(gt, pr)

    # There is no match between gt and pr objects, so ground truth needs to be
    # padded with more objects that it had. Previously `_reorder` used
    # `tf.zeros_like(tensor[:num])`, which lead to incorrect shapes if
    # tensor.shape[0] < num.
    self.assertEqual(gt_m.box.center.shape, (3, 3))
    self.assertEqual(pr_m.box.center.shape, (3, 3))


class PemTest(tf.test.TestCase):

  def test_returns_mean_square_error_for_all_visible_keypoints(self):
    # batch_size = 3, num_points = 2
    gt = _data.KeypointsTensors(
        location=tf.constant([
            [[1.0, 1.0], [-1.0, -1.0]],
            [[2.0, 2.0], [-2.0, -2.0]],
            [[3.0, 3.0], [-3.0, -3.0]],
        ]),
        visibility=tf.constant([[2, 2], [2, 2], [2, 2]]),
    )
    # Predicted points are [1, 2, 3, 4, 5, 6] pixels away from ground truth.
    pr = _data.KeypointsTensors(
        location=tf.constant([
            [[1.0, 0.0], [1.0, -1.0]],
            [[2.0, -1.0], [2.0, -2.0]],
            [[3.0, -2.0], [-3.0, 3.0]],
        ]),
        visibility=tf.constant([[2, 2], [2, 2], [2, 2]]),
    )
    box = None  # is not used by the metric

    pem = _lib.PoseEstimationMetric(name='PEM', mismatch_penalty=0.25)
    pem.update_state([gt, pr, box])
    metrics = pem.result()

    self.assertNear(metrics['PEM'], (1 + 2 + 3 + 4 + 5 + 6) / 6, err=1e-5)

  def test_adds_penalty_for_mismatches(self):
    # Three objects with two keypoints:
    #  0 - match
    #  1 - false negative
    #  2 - false positive
    # Mismatched keypoints have visibility=0
    gt = _data.KeypointsTensors(
        location=tf.constant([
            [[1.0, 1.0], [-1.0, -1.0]],
            [[2.0, 2.0], [-2.0, -2.0]],
            [[0.0, 0.0], [0.0, 0.0]],
        ]),
        visibility=tf.constant([[2, 2], [2, 2], [0, 0]]),
    )
    pr = _data.KeypointsTensors(
        location=tf.constant([
            [[1.0, 0.0], [1.0, -1.0]],
            [[0.0, 0.0], [0.0, 0.0]],
            [[3.0, -2.0], [-3.0, 3.0]],
        ]),
        visibility=tf.constant([[2, 2], [0, 0], [2, 2]]),
    )
    box = None  # is not used by the metric

    pem = _lib.PoseEstimationMetric(name='PEM', mismatch_penalty=0.25)
    pem.update_state([gt, pr, box])
    metrics = pem.result()

    self.assertNear(metrics['PEM'], (1 + 2 + 4 * 0.25) / 6, err=1e-5)

  def test_correctly_predicted_invisible_points_are_not_penalized(self):
    gt = _data.KeypointsTensors(
        # Values for keypoints with visibility 0 could be anything.
        location=tf.constant([
            [[1.0, 1.0], [-1.0, -1.0]],
            [[2.0, 2.0], [666.0, 666.0]],
            [[777.0, 777.0], [3.0, 3.0]],
        ]),
        visibility=tf.constant([[2, 2], [2, 0], [0, 2]]),
    )
    pr = _data.KeypointsTensors(
        location=tf.constant([
            [[1.0, 0.0], [1.0, -1.0]],
            [[2.0, -1.0], [0.0, 0.0]],
            [[3.0, -2.0], [-3.0, 3.0]],
        ]),
        visibility=tf.constant([[2, 2], [2, 0], [0, 2]]),
    )
    box = None  # is not used by the metric

    pem = _lib.PoseEstimationMetric(name='PEM', mismatch_penalty=0.25)
    pem.update_state([gt, pr, box])
    metrics = pem.result()

    # Expected errors per keypoint: 1, 2, 3, 0, 0, 6
    self.assertNear(metrics['PEM'], (1 + 2 + 3 + 6) / 4, err=1e-5)

  def test_respects_sample_weights(self):
    # batch_size = 3, num_points = 2
    gt = _data.KeypointsTensors(
        location=tf.constant([
            [[1.0, 1.0], [-1.0, -1.0]],
            [[2.0, 2.0], [-2.0, -2.0]],
            [[3.0, 3.0], [-3.0, -3.0]],
        ]),
        visibility=tf.constant([[2, 2], [0, 2], [2, 0]]),
    )
    # Predicted points are [1, 2, 3, 4, 5, 6] pixels away from ground truth.
    pr = _data.KeypointsTensors(
        location=tf.constant([
            [[1.0, 0.0], [1.0, -1.0]],
            [[2.0, -1.0], [2.0, -2.0]],
            [[3.0, -2.0], [-3.0, 3.0]],
        ]),
        visibility=tf.constant([[2, 2], [2, 2], [2, 2]]),
    )
    box = None  # is not used by the metric
    sample_weight = tf.constant([0.0, 0.5, 1.0])

    pem = _lib.PoseEstimationMetric(name='PEM', mismatch_penalty=0.25)
    pem.update_state([gt, pr, box], sample_weight=sample_weight)
    metrics = pem.result()

    self.assertNear(
        metrics['PEM'],
        (0 + 0 + (0.25 + 4) * 0.5 + (5 + 0.25) * 1.0)
        / (2 * 0 + 2 * 0.5 + 2 * 1.0),
        err=1e-5,
    )


class KeypointVisibilityPrecisionTest(tf.test.TestCase):

  def test_ratio_of_num_true_positives_to_predicted(self):
    # batch_size = 3, num_points = 2
    # Location is ignored by this metric
    gt = _data.KeypointsTensors(
        location=tf.constant(0.0, shape=[3, 2, 2]),
        visibility=tf.constant([[2, 2], [2, 0], [0, 0]]),
    )
    pr = _data.KeypointsTensors(
        location=tf.constant(0.0, shape=[3, 2, 2]),
        visibility=tf.constant([[2, 2], [0, 0], [2, 2]]),
    )
    box = None  # is not used by the metric

    precision = _lib.KeypointVisibilityPrecision(name='P')
    precision.update_state([gt, pr, box])
    metrics = precision.result()

    self.assertNear(metrics['P'], 2.0 / 4, err=1e-5)


class KeypointVisibilityRecallTest(tf.test.TestCase):

  def test_ratio_of_num_true_positives_to_ground_truth(self):
    # batch_size = 3, num_points = 2
    # Location is ignored by this metric
    gt = _data.KeypointsTensors(
        location=tf.constant(0.0, shape=[3, 2, 2]),
        visibility=tf.constant([[2, 2], [2, 0], [0, 0]]),
    )
    pr = _data.KeypointsTensors(
        location=tf.constant(0.0, shape=[3, 2, 2]),
        visibility=tf.constant([[2, 2], [0, 0], [2, 2]]),
    )
    box = None  # is not used by the metric

    recall = _lib.KeypointVisibilityRecall(name='R')
    recall.update_state([gt, pr, box])
    metrics = recall.result()

    self.assertNear(metrics['R'], 2.0 / 3, err=1e-5)


if __name__ == '__main__':
  tf.test.main()
