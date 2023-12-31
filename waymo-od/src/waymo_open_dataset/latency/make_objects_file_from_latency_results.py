# Copyright 2021 The Waymo Open Dataset Authors.
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
"""Script to convert latency evaluator's numpy output to proto file.

In particular, this script reads the numpy files generated by the latency
evaluator for each example (for the boxes, classes, and scores of the
detections) and generates Object protos for each of those detections. It then
wraps all those Object protos into a single Objects proto that can have its
accuracy evaluated and saves that Objects proto to a protobuf binary file.
"""
import argparse
import os

import numpy as np

from waymo_open_dataset import dataset_pb2
from waymo_open_dataset.protos import metrics_pb2


def make_object_list_from_subdir(np_dir,
                                 frame_context_name,
                                 frame_timestamp_micros):
  """Make a list of Object protos from the detection results in a directory.

  In particular, this function assumes that np_dir is a subdirectory like one
  created by the latency evaluator for a particular frame, and thus that it
  contains three npy files:

  * boxes.npy: a N x 7 float array with the x, y, z, length, width, height, and
               heading for all the detections in this frame.
  * classes.npy: a N-dim uint8 array with the type IDs in {0, 1, 2, 3, 4} for
                 all the detections in this frame.
  * scores.npy: a N-dim float array with the scores in [0, 1] for all the
                detections in this frame.

  These arrays are converted into a list of N Object protos, one for each
  detection, where all the protos have the frame_context_name and
  frame_timestamp_micros set by the arguments.

  Args:
    np_dir: string directory name containing the npy files.
    frame_context_name: string context_name to set for each Object proto.
    frame_timestamp_micros: int timestamp micros to set for each Object proto.

  Returns:
    List of N Object protos, one for each detection present in the npy files.
    They all have the same context name and frame_timestamp_micros, while their
    boxes, scores, and types come from the numpy arrays.
  """
  boxes = np.load(os.path.join(np_dir, 'boxes.npy'))
  classes = np.load(os.path.join(np_dir, 'classes.npy'))
  scores = np.load(os.path.join(np_dir, 'scores.npy'))

  # Read the input fields file if it exists.
  input_fields = []
  input_field_path = os.path.join(np_dir, 'input_fields.txt')
  if os.path.isfile(input_field_path):
    with open(input_field_path, 'r') as input_field_file:
      input_fields = input_field_file.readlines()

  num_objs = boxes.shape[0]
  assert classes.shape[0] == num_objs
  assert scores.shape[0] == num_objs

  obj_list = []
  for i in range(num_objs):
    obj = metrics_pb2.Object()
    obj.context_name = frame_context_name
    obj.frame_timestamp_micros = frame_timestamp_micros
    obj.score = scores[i]
    obj.object.type = classes[i]

    # Handle the box creation differently for 3D boxes (where the inner
    # dimension is 7) and 2D boxes (where the inner dimension is 4).
    if boxes.shape[1] == 7:
      obj.object.box.center_x = boxes[i, 0]
      obj.object.box.center_y = boxes[i, 1]
      obj.object.box.center_z = boxes[i, 2]
      obj.object.box.length = boxes[i, 3]
      obj.object.box.width = boxes[i, 4]
      obj.object.box.height = boxes[i, 5]
      obj.object.box.heading = boxes[i, 6]
    elif boxes.shape[1] == 4:
      obj.object.box.center_x = boxes[i, 0]
      obj.object.box.center_y = boxes[i, 1]
      obj.object.box.length = boxes[i, 2]
      obj.object.box.width = boxes[i, 3]

      # For 2D detection objects, the camera name of the object proto comes from
      # the camera whose image was used as input. Thus, the input_fields
      # specified by the user are checked to ensure that they only used a single
      # input and that the input was the RGB image from one of the cameras.
      if len(input_fields) != 1:
        raise ValueError('Can only use one input when submitting 2D detection '
                         'results; instead was using:\n' +
                         '\n'.join(input_fields))
      input_field = input_fields[0]
      if not input_field.endswith('_IMAGE'):
        raise ValueError('For 2D detection results, the input field should be '
                         'one of the camera images, but got ' + input_field)
      obj.camera_name = dataset_pb2.CameraName.Name.Value(input_field[:-6])

    # Run some checks to avoid adding invalid objects. These are the same checks
    # used in metrics/tools/create_submission.cc
    if (obj.score < 0.03 or obj.object.box.length < 0.01 or
        obj.object.box.width < 0.01 or
        (obj.object.box.HasField('height') and obj.object.box.height < 0.01)):
      print('Skipping invalid object', obj)
      continue

    obj_list.append(obj)

  return obj_list


if __name__ == '__main__':
  parser = argparse.ArgumentParser()
  parser.add_argument('--results_dir', type=str, required=True)
  parser.add_argument('--output_file', type=str, required=True)
  args = parser.parse_args()

  objects = metrics_pb2.Objects()

  # Iterate through the subdirectories for each frame. See
  # wod_latency_evaluator.py for more details.
  for context_name in os.listdir(args.results_dir):
    context_dir = os.path.join(args.results_dir, context_name)
    if not os.path.isdir(context_dir):
      continue
    for timestamp_micros in os.listdir(context_dir):
      timestamp_dir = os.path.join(context_dir, timestamp_micros)
      if not os.path.isdir(timestamp_dir):
        continue

      print('Processing', context_name, timestamp_micros)
      objects.objects.extend(make_object_list_from_subdir(
          timestamp_dir, context_name, int(timestamp_micros)))

  print('Got ', len(objects.objects), 'objects')
  with open(args.output_file, 'wb') as f:
    f.write(objects.SerializeToString())
