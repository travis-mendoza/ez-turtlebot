"""
stream_object_detection_video_to_AWS.py - Object detection with overlays to AWS KVS

This script uses the IMX500 AI Camera for object detection, draws overlays,
and streams the output to AWS Kinesis Video Streams using GStreamer via gst-python.

Usage:
    python stream_object_detection_video_to_AWS.py --model /path/to/model.rpk --kvs-stream-name your-kvs-stream
    Uses environment variables for AWS credentials, region, KVS stream name,
    IP, port, width, height, FPS, bitrate if not specified.
"""
import argparse
import sys
import os
from functools import lru_cache
from typing import List, Optional
# import time # Potentially for a small sleep if needed

import cv2
import numpy as np

from picamera2 import MappedArray, Picamera2
from picamera2.devices import IMX500
from picamera2.devices.imx500 import (NetworkIntrinsics,
                                      postprocess_nanodet_detection)

# GStreamer imports
import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstApp', '1.0')
from gi.repository import Gst, GstApp, GLib

# --- Constants for default paths ---
DEFAULT_MODEL_PATH = "/usr/share/imx500-models/imx500_network_ssd_mobilenetv2_fpnlite_320x320_pp.rpk"
DEFAULT_COCO_LABELS_PATH = "assets/coco_labels.txt"

# --- Global variables ---
last_detections: List['Detection'] = []
last_results: Optional[List['Detection']] = None
picam2: Optional[Picamera2] = None
imx500: Optional[IMX500] = None
intrinsics: Optional[NetworkIntrinsics] = None
args_global: Optional[argparse.Namespace] = None

gst_pipeline_obj = None
appsrc_obj = None
glib_loop = None
gst_pipeline_active = True

class Detection:
    def __init__(self, coords, category, conf, metadata):
        global picam2, imx500
        self.category = category
        self.conf = conf
        if picam2 and imx500:
            self.box = imx500.convert_inference_coords(coords, metadata, picam2)
        else:
            self.box = (0,0,0,0)
            print("Warning: picam2 or imx500 not initialized when Detection created.", file=sys.stderr)

def parse_detections(metadata: dict) -> List['Detection']:
    global last_detections, intrinsics, args_global
    if not intrinsics or not args_global:
        print("Error: Intrinsics or args_global not initialized for parse_detections.", file=sys.stderr)
        return last_detections

    bbox_normalization = intrinsics.bbox_normalization
    bbox_order = intrinsics.bbox_order
    threshold = args_global.threshold
    iou = args_global.iou
    max_detections = args_global.max_detections

    np_outputs = imx500.get_outputs(metadata, add_batch=True)
    input_w, input_h = imx500.get_input_size()
    if np_outputs is None:
        return last_detections

    current_detections: List[Detection] = []
    if intrinsics.postprocess == "nanodet":
        boxes, scores, classes = \
            postprocess_nanodet_detection(outputs=np_outputs[0], conf=threshold, iou_thres=iou,
                                          max_out_dets=max_detections)[0]
        from picamera2.devices.imx500.postprocess import scale_boxes
        boxes = scale_boxes(boxes, 1, 1, input_h, input_w, False, False)
    else:
        boxes, scores, classes = np_outputs[0][0], np_outputs[1][0], np_outputs[2][0]
        if bbox_normalization:
            boxes = boxes / input_h
        if bbox_order == "xy":
            boxes = boxes[:, [1, 0, 3, 2]]
        split_boxes = np.array_split(boxes, 4, axis=1)
        processed_boxes = zip(*split_boxes)

    current_detections = [
        Detection(box, category, score, metadata)
        for box, score, category in zip(processed_boxes if intrinsics.postprocess != "nanodet" else boxes, scores, classes)
        if score > threshold
    ]
    last_detections = current_detections
    return current_detections

@lru_cache
def get_labels() -> List[str]:
    global intrinsics
    if not intrinsics: return []
    labels = intrinsics.labels if intrinsics.labels else []
    if intrinsics.ignore_dash_labels:
        labels = [label for label in labels if label and label != "-"]
    return labels

def draw_detections_on_array(array: np.ndarray, detections_to_draw: Optional[List[Detection]], current_request_for_roi=None):
    global imx500, intrinsics
    if detections_to_draw is None or not intrinsics:
        return array

    labels = get_labels()
    for detection_obj in detections_to_draw:
        x, y, w, h = detection_obj.box
        label_text = f"{labels[int(detection_obj.category)]} ({detection_obj.conf:.2f})"
        (text_width, text_height), baseline = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        text_x = x + 5
        text_y = y + 15
        cv2.rectangle(array, (text_x, text_y - text_height - baseline // 2), (text_x + text_width, text_y + baseline // 2), (255, 255, 255), cv2.FILLED)
        cv2.putText(array, label_text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1) # Red text on RGB
        cv2.rectangle(array, (x, y), (x + w, y + h), (0, 255, 0, 0), thickness=2)
    return array

def get_args_aws_local():
    global args_global
    parser = argparse.ArgumentParser(description="IMX500 Object Detection to AWS KVS")
    parser.add_argument("--model", type=str, help="Path of the model", default=DEFAULT_MODEL_PATH)
    script_default_fps = 30
    env_fps_str = os.environ.get('VIDEO_FRAMERATE')
    default_fps = script_default_fps
    if env_fps_str:
        try: default_fps = int(env_fps_str.split('/')[0]) if '/' in env_fps_str else int(env_fps_str)
        except ValueError: print(f"Warning: Invalid VIDEO_FRAMERATE. Using default {script_default_fps}.", file=sys.stderr)
    parser.add_argument("--fps", type=int, default=default_fps, help=f"Frames per second (env: VIDEO_FRAMERATE, default: {script_default_fps})")
    parser.add_argument("--bbox-normalization", action=argparse.BooleanOptionalAction, help="Normalize bbox")
    parser.add_argument("--bbox-order", choices=["yx", "xy"], default="yx")
    parser.add_argument("--threshold", type=float, default=0.55, help="Detection threshold")
    parser.add_argument("--iou", type=float, default=0.65, help="Set iou threshold")
    parser.add_argument("--max-detections", type=int, default=10, help="Set max detections")
    parser.add_argument("--ignore-dash-labels", action=argparse.BooleanOptionalAction, help="Remove '-' labels")
    parser.add_argument("--postprocess", choices=["", "nanodet"], default=None)
    parser.add_argument("-r", "--preserve-aspect-ratio", action=argparse.BooleanOptionalAction)
    parser.add_argument("--labels", type=str, help=f"Path to labels file (default: {DEFAULT_COCO_LABELS_PATH})")
    parser.add_argument("--print-intrinsics", action="store_true")
    default_kvs_stream_name = os.environ.get('KVS_STREAM_NAME')
    parser.add_argument("--kvs-stream-name", type=str, default=default_kvs_stream_name, required=default_kvs_stream_name is None, help="AWS Kinesis Video Stream name (env: KVS_STREAM_NAME)")
    parser.add_argument("--aws-region", type=str, default=os.environ.get('AWS_REGION'), help="AWS Region for KVS (env: AWS_REGION)")
    script_default_bitrate_kbps = 1000
    env_bitrate_kbps_str = os.environ.get('VIDEO_BITRATE')
    default_bitrate_kbps = script_default_bitrate_kbps
    if env_bitrate_kbps_str:
        try: default_bitrate_kbps = int(env_bitrate_kbps_str)
        except ValueError: print(f"Warning: Invalid VIDEO_BITRATE. Using default {default_bitrate_kbps} Kbps.", file=sys.stderr)
    parser.add_argument("--bitrate", type=int, default=default_bitrate_kbps, help=f"Target bitrate for H.264 encoding in Kbps (env: VIDEO_BITRATE, default: {default_bitrate_kbps} Kbps)")
    script_default_width = 640
    env_width_str = os.environ.get('VIDEO_WIDTH')
    default_width = script_default_width
    if env_width_str:
        try: default_width = int(env_width_str)
        except ValueError: print(f"Warning: Invalid VIDEO_WIDTH. Using default {script_default_width}.", file=sys.stderr)
    parser.add_argument("--width", type=int, default=default_width, help=f"Stream width (env: VIDEO_WIDTH, default: {script_default_width})")
    script_default_height = 480
    env_height_str = os.environ.get('VIDEO_HEIGHT')
    default_height = script_default_height
    if env_height_str:
        try: default_height = int(env_height_str)
        except ValueError: print(f"Warning: Invalid VIDEO_HEIGHT. Using default {script_default_height}.", file=sys.stderr)
    parser.add_argument("--height", type=int, default=default_height, help=f"Stream height (env: VIDEO_HEIGHT, default: {script_default_height})")
    parser.add_argument("--local-display", action="store_true", help="Show video locally as well")
    args_global = parser.parse_args()
    return args_global

def on_bus_message(bus, message, loop_param):
    global gst_pipeline_active
    mtype = message.type
    if mtype == Gst.MessageType.EOS:
        print("GStreamer: End-of-stream received on bus.")
        gst_pipeline_active = False
        if loop_param and loop_param.is_running():
             loop_param.quit()
    elif mtype == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        print(f"GStreamer Error: {err}, {debug}")
        gst_pipeline_active = False
        if loop_param and loop_param.is_running():
            loop_param.quit()
    elif mtype == Gst.MessageType.WARNING:
        err, debug = message.parse_warning()
        print(f"GStreamer Warning: {err}, {debug}")
    return True

def main():
    global picam2, imx500, intrinsics, args_global
    global gst_pipeline_obj, appsrc_obj, glib_loop, gst_pipeline_active, last_results

    Gst.init(None)
    args_val = get_args_aws_local()

    imx500 = IMX500(args_val.model)
    intrinsics = imx500.network_intrinsics
    if not intrinsics:
        intrinsics = NetworkIntrinsics(); intrinsics.task = "object detection"
    elif intrinsics.task != "object detection":
        print("Error: Network is not an object detection task.", file=sys.stderr); sys.exit(1)

    for key, value in vars(args_val).items():
        if key == 'labels' and value is not None:
            try:
                with open(value, 'r') as f: intrinsics.labels = f.read().splitlines()
            except FileNotFoundError: print(f"Error: Labels file '{value}' not found.", file=sys.stderr); sys.exit(1)
        elif hasattr(intrinsics, key) and value is not None: setattr(intrinsics, key, value)

    if intrinsics.labels is None:
        default_labels_path = args_val.labels if args_val.labels else DEFAULT_COCO_LABELS_PATH
        try:
            with open(default_labels_path, "r") as f: intrinsics.labels = f.read().splitlines()
            if not args_val.labels: print(f"Using default labels: {default_labels_path}")
        except FileNotFoundError:
            print(f"Error: Default labels file '{default_labels_path}' not found.", file=sys.stderr); intrinsics.labels = []
    intrinsics.update_with_defaults()

    if args_val.print_intrinsics: print(intrinsics); sys.exit(0)

    picam2 = Picamera2(imx500.camera_num)
    video_config = picam2.create_video_configuration(
        main={"size": (args_val.width, args_val.height), "format": "RGB888"}, # Output RGB
        controls={"FrameRate": float(args_val.fps)}, buffer_count=10)
    picam2.configure(video_config)
    
    # CHANGE 1: appsrc caps format to BGR
    gst_pipeline_str = (
        f"appsrc name=pysrc format=GST_FORMAT_TIME is-live=true do-timestamp=true caps=video/x-raw,format=BGR,width={args_val.width},height={args_val.height},framerate={args_val.fps}/1 ! "
        f"videoconvert ! video/x-raw,format=I420 ! "
        f"x264enc bitrate={args_val.bitrate} bframes=0 key-int-max={int(args_val.fps)} tune=zerolatency speed-preset=ultrafast byte-stream=true ! "
        f"video/x-h264,profile=baseline,stream-format=avc,alignment=au ! "
        f"h264parse ! "
        f"kvssink stream-name=\"{args_val.kvs_stream_name}\" storage-size=512"
    )
    if args_val.aws_region: gst_pipeline_str += f" aws-region=\"{args_val.aws_region}\""
    print(f"Using GStreamer pipeline: {gst_pipeline_str}")
    try:
        gst_pipeline_obj = Gst.parse_launch(gst_pipeline_str)
    except GLib.Error as e: print(f"Failed to parse GStreamer pipeline: {e}", file=sys.stderr); sys.exit(1)

    appsrc_obj = gst_pipeline_obj.get_by_name('pysrc')
    if not appsrc_obj: print("Error: Could not find appsrc 'pysrc'.", file=sys.stderr); sys.exit(1)

    imx500.show_network_fw_progress_bar()
    picam2.start()
    print(f"Picamera2 started. Streaming to KVS: {args_val.kvs_stream_name}")
    if intrinsics.preserve_aspect_ratio: imx500.set_auto_aspect_ratio()

    glib_loop = GLib.MainLoop()
    bus = gst_pipeline_obj.get_bus()
    bus.add_signal_watch()
    bus.connect("message", on_bus_message, glib_loop)

    gst_pipeline_obj.set_state(Gst.State.PLAYING)
    print("GStreamer pipeline playing.")

    pts = 0
    duration = 10**9 / args_val.fps
    gst_pipeline_active = True

    try:
        while gst_pipeline_active:
            request = picam2.capture_request()
            try:
                metadata = request.get_metadata()
                if metadata: last_results = parse_detections(metadata)
                
                frame_array_rgb = request.make_array('main') # This is RGB
                frame_with_overlays_rgb = draw_detections_on_array(frame_array_rgb, last_results, request)

                # CHANGE 2: Convert RGB to BGR before pushing
                frame_with_overlays_bgr = cv2.cvtColor(frame_with_overlays_rgb, cv2.COLOR_RGB2BGR)

                if args_val.local_display:
                    # For local display, you might want to show the BGR image or convert it back to RGB
                    # depending on what cv2.imshow expects on your system, but usually BGR is fine.
                    cv2.imshow("Local Preview", frame_with_overlays_bgr)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        gst_pipeline_active = False; break 
                
                # CHANGE 3: Push the BGR frame bytes
                gst_buffer = Gst.Buffer.new_wrapped(frame_with_overlays_bgr.tobytes())
                gst_buffer.pts = pts
                gst_buffer.duration = duration
                pts += duration
                retval = appsrc_obj.push_buffer(gst_buffer)
                if retval != Gst.FlowReturn.OK:
                    print(f"Error pushing buffer to appsrc: {retval}", file=sys.stderr)
                    gst_pipeline_active = False
            finally:
                request.release()

            while GLib.MainContext.default().pending():
                GLib.MainContext.default().iteration(False)
            
    except KeyboardInterrupt:
        print("\nStopping stream due to KeyboardInterrupt...")
        gst_pipeline_active = False
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
        import traceback; traceback.print_exc()
        gst_pipeline_active = False
    finally:
        print("Cleaning up resources...")
        if args_val.local_display: cv2.destroyAllWindows()
        if gst_pipeline_obj:
            print("Setting GStreamer pipeline to NULL...")
            gst_pipeline_obj.set_state(Gst.State.NULL)
        if glib_loop and glib_loop.is_running():
            glib_loop.quit()
        if picam2 and picam2.started:
            print("Stopping Picamera2...")
            picam2.stop()
        print("Cleanup finished.")

if __name__ == "__main__":
    main()