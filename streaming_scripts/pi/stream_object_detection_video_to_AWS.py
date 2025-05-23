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

import cv2
import numpy as np

from picamera2 import MappedArray, Picamera2
# We won't use Picamera2's H264Encoder or FfmpegOutput for AWS streaming
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
picam2: Optional[Picamera2] = None # Make picam2 global for Detection class
imx500: Optional[IMX500] = None # Make imx500 global
intrinsics: Optional[NetworkIntrinsics] = None # Make intrinsics global
args: Optional[argparse.Namespace] = None # Make args global

gst_pipeline = None
appsrc = None
loop = None


class Detection:
    def __init__(self, coords, category, conf, metadata):
        global picam2, imx500 # Access globals
        self.category = category
        self.conf = conf
        if picam2 and imx500:
            self.box = imx500.convert_inference_coords(coords, metadata, picam2)
        else:
            # Fallback or error if picam2/imx500 not initialized
            # This case should ideally not be hit if initialization order is correct
            self.box = (0,0,0,0)
            print("Warning: picam2 or imx500 not initialized when Detection created.", file=sys.stderr)


def parse_detections(metadata: dict) -> List['Detection']:
    global last_detections, intrinsics, args # Access globals
    if not intrinsics or not args:
        print("Error: Intrinsics or args not initialized for parse_detections.", file=sys.stderr)
        return last_detections

    bbox_normalization = intrinsics.bbox_normalization
    bbox_order = intrinsics.bbox_order
    threshold = args.threshold
    iou = args.iou
    max_detections = args.max_detections

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
    global intrinsics # Access global
    if not intrinsics: return []
    labels = intrinsics.labels if intrinsics.labels else []
    if intrinsics.ignore_dash_labels:
        labels = [label for label in labels if label and label != "-"]
    return labels


def draw_detections_on_array(array: np.ndarray, detections_to_draw: Optional[List[Detection]], current_request_for_roi=None):
    """Draws detections directly onto a numpy array. Modified from pre_callback."""
    global imx500, intrinsics # Access globals
    if detections_to_draw is None or not intrinsics:
        return array # Return original array if no detections or intrinsics

    labels = get_labels()
    # Create a copy to draw on, to avoid modifying the original if it's directly from camera
    # However, if this array is already a copy intended for modification, this might be redundant.
    # For appsrc, we'll be sending this array, so drawing on it directly is fine.
    # array_to_draw_on = array.copy() # Let's draw directly on the passed array

    for detection_obj in detections_to_draw:
        x, y, w, h = detection_obj.box
        label_text = f"{labels[int(detection_obj.category)]} ({detection_obj.conf:.2f})"
        (text_width, text_height), baseline = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        text_x = x + 5
        text_y = y + 15

        # Draw background for text
        cv2.rectangle(array,
                      (text_x, text_y - text_height - baseline // 2),
                      (text_x + text_width, text_y + baseline // 2),
                      (255, 255, 255), # White background
                      cv2.FILLED)
        # Draw text
        cv2.putText(array, label_text, (text_x, text_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1) # Red text
        # Draw detection box
        cv2.rectangle(array, (x, y), (x + w, y + h), (0, 255, 0, 0), thickness=2) # Green box

    if intrinsics.preserve_aspect_ratio and current_request_for_roi and imx500:
        # This part might be tricky if we don't have a 'request' object easily available
        # when calling this function. For now, let's assume we might not draw ROI
        # or we need to pass the request if ROI drawing is critical.
        # b_x, b_y, b_w, b_h = imx500.get_roi_scaled(current_request_for_roi)
        # color = (255, 0, 0)
        # cv2.putText(array, "ROI", (b_x + 5, b_y + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        # cv2.rectangle(array, (b_x, b_y), (b_x + b_w, b_y + b_h), (255, 0, 0, 0))
        pass # ROI drawing might need rework for this flow

    return array


def get_args_aws():
    global args # To assign to global args
    parser = argparse.ArgumentParser(description="IMX500 Object Detection to AWS KVS")
    parser.add_argument("--model", type=str, help="Path of the model",
                        default=DEFAULT_MODEL_PATH)

    script_default_fps = 30
    env_fps_str = os.environ.get('VIDEO_FRAMERATE')
    default_fps = script_default_fps
    if env_fps_str:
        try:
            default_fps = int(env_fps_str.split('/')[0]) if '/' in env_fps_str else int(env_fps_str)
        except ValueError:
            print(f"Warning: Invalid VIDEO_FRAMERATE. Using default {script_default_fps}.", file=sys.stderr)
    parser.add_argument("--fps", type=int, default=default_fps,
                        help=f"Frames per second (env: VIDEO_FRAMERATE, script default: {script_default_fps})")

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

    # AWS KVS Specific Arguments
    default_kvs_stream_name = os.environ.get('KVS_STREAM_NAME')
    parser.add_argument("--kvs-stream-name", type=str, default=default_kvs_stream_name, required=default_kvs_stream_name is None,
                        help="AWS Kinesis Video Stream name (env: KVS_STREAM_NAME)")
    parser.add_argument("--aws-region", type=str, default=os.environ.get('AWS_REGION'),
                        help="AWS Region for KVS (env: AWS_REGION, kvssink might pick from default config too)")


    script_default_bitrate_bps = 1000 * 1000 # 1 Mbps for KVS (x264enc uses kbps)
    env_bitrate_kbps_str = os.environ.get('VIDEO_BITRATE') # Assuming VIDEO_BITRATE is in Kbps
    default_bitrate_kbps = script_default_bitrate_bps // 1000
    if env_bitrate_kbps_str:
        try:
            default_bitrate_kbps = int(env_bitrate_kbps_str)
        except ValueError:
            print(f"Warning: Invalid VIDEO_BITRATE. Using default {default_bitrate_kbps} Kbps.", file=sys.stderr)
    parser.add_argument("--bitrate", type=int, default=default_bitrate_kbps,
                        help=f"Target bitrate for H.264 encoding in Kbps (env: VIDEO_BITRATE in Kbps, script default: {default_bitrate_kbps} Kbps)")


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

    parser.add_argument("--local-display", action="store_true", help="Show video locally as well (experimental with GStreamer)")
    
    args = parser.parse_args()
    return args

# --- GStreamer related functions ---
def on_bus_message(bus, message, loop):
    mtype = message.type
    if mtype == Gst.MessageType.EOS:
        print("GStreamer: End-of-stream")
        loop.quit()
    elif mtype == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        print(f"GStreamer Error: {err}, {debug}")
        loop.quit()
    elif mtype == Gst.MessageType.WARNING:
        err, debug = message.parse_warning()
        print(f"GStreamer Warning: {err}, {debug}")
    return True

def main():
    global picam2, imx500, intrinsics, args, gst_pipeline, appsrc, loop, last_results

    Gst.init(None)
    args = get_args_aws()

    imx500 = IMX500(args.model)
    intrinsics = imx500.network_intrinsics
    if not intrinsics:
        intrinsics = NetworkIntrinsics()
        intrinsics.task = "object detection"
    elif intrinsics.task != "object detection":
        print("Error: Network is not an object detection task.", file=sys.stderr)
        sys.exit(1)

    for key, value in vars(args).items():
        if key == 'labels' and value is not None:
            try:
                with open(value, 'r') as f: intrinsics.labels = f.read().splitlines()
            except FileNotFoundError:
                print(f"Error: Labels file '{value}' not found.", file=sys.stderr); sys.exit(1)
        elif hasattr(intrinsics, key) and value is not None:
            setattr(intrinsics, key, value)

    if intrinsics.labels is None:
        default_labels_path = args.labels if args.labels else DEFAULT_COCO_LABELS_PATH
        try:
            with open(default_labels_path, "r") as f: intrinsics.labels = f.read().splitlines()
            if not args.labels: print(f"Using default labels: {default_labels_path}")
        except FileNotFoundError:
            print(f"Error: Default labels file '{default_labels_path}' not found.", file=sys.stderr)
            intrinsics.labels = []
    intrinsics.update_with_defaults()

    if args.print_intrinsics:
        print(intrinsics); sys.exit(0)

    picam2 = Picamera2(imx500.camera_num)
    video_config = picam2.create_video_configuration(
        main={"size": (args.width, args.height), "format": "RGB888"}, # We need RGB for OpenCV drawing
        controls={"FrameRate": float(args.fps)}, # GStreamer framerate needs float
        buffer_count=10 # Increased buffer count slightly
    )
    picam2.configure(video_config)
    
    # --- GStreamer Pipeline Setup ---
    # Note: x264enc bitrate is in Kbps. args.bitrate is already taken as Kbps.
    # key-int-max (GOP size) is roughly fps * seconds_per_keyframe. 30 is 1s @ 30fps.
    # For KVS, profile=baseline, stream-format=avc, alignment=au are often recommended.
    gst_pipeline_str = (
        f"appsrc name=pysrc format=GST_FORMAT_TIME caps=video/x-raw,format=RGB,width={args.width},height={args.height},framerate={args.fps}/1 ! "
        f"videoconvert ! video/x-raw,format=I420 ! "
        f"x264enc bitrate={args.bitrate} bframes=0 key-int-max={args.fps} tune=zerolatency speed-preset=ultrafast byte-stream=true ! "
        f"video/x-h264,profile=baseline,stream-format=avc,alignment=au ! "
        f"h264parse ! "
        f"kvssink stream-name=\"{args.kvs_stream_name}\" storage-size=512"
    )
    if args.aws_region: # kvssink can also pick region from AWS config
        gst_pipeline_str += f" aws-region=\"{args.aws_region}\""

    print(f"Using GStreamer pipeline: {gst_pipeline_str}")
    try:
        gst_pipeline = Gst.parse_launch(gst_pipeline_str)
    except GLib.Error as e:
        print(f"Failed to parse GStreamer pipeline: {e}", file=sys.stderr)
        sys.exit(1)

    appsrc = gst_pipeline.get_by_name('pysrc')
    if not appsrc:
        print("Error: Could not find appsrc element 'pysrc' in GStreamer pipeline.", file=sys.stderr)
        sys.exit(1)
    
    # Optional: Set stream type if needed, though often inferred
    # appsrc.set_property('stream-type', GstApp.AppStreamType.STREAM)
    # appsrc.set_property('is-live', True)


    imx500.show_network_fw_progress_bar() # Do this before picam2.start()
    picam2.start()
    picam2_started = True
    print(f"Picamera2 started. Streaming to KVS: {args.kvs_stream_name}")

    if intrinsics.preserve_aspect_ratio:
        imx500.set_auto_aspect_ratio()

    # GStreamer main loop
    loop = GLib.MainLoop()
    bus = gst_pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", on_bus_message, loop)

    gst_pipeline.set_state(Gst.State.PLAYING)
    print("GStreamer pipeline playing.")

    frame_count = 0
    pts = 0 # Presentation timestamp
    duration = 10**9 / args.fps # Frame duration in nanoseconds

    try:
        while not loop.is_running() or True: # Keep pushing frames as long as picam2 is running
            # For synchronous pushing, we might not need GLib main loop to run the Python loop
            # but it's good for handling bus messages.
            # If loop.quit() is called by EOS/Error, this outer loop should also break.

            request = picam2.capture_request() # Capture a frame and its metadata
            try:
                # Get metadata for parsing detections
                metadata = request.get_metadata()
                if metadata:
                    last_results = parse_detections(metadata)

                # Get the main frame as a NumPy array (RGB888)
                frame_array = request.make_array('main')

                # Draw detections on this array
                # Pass the request object if draw_detections_on_array needs it for ROI scaling
                frame_with_overlays = draw_detections_on_array(frame_array, last_results, request)

                if args.local_display:
                    cv2.imshow("Local Preview", frame_with_overlays)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break # Allow quitting local display

                # Push buffer to GStreamer appsrc
                gst_buffer = Gst.Buffer.new_wrapped(frame_with_overlays.tobytes())
                
                # Set PTS and Duration for GStreamer buffer
                gst_buffer.pts = pts
                gst_buffer.duration = duration
                pts += duration

                retval = appsrc.push_buffer(gst_buffer)
                if retval != Gst.FlowReturn.OK:
                    print(f"Error pushing buffer to appsrc: {retval}", file=sys.stderr)
                    # Consider breaking or handling this error
                    # If EOS or error on bus, loop.quit() will handle exit
                    if not loop.is_running(): break


                frame_count += 1
                # print(f"Pushed frame {frame_count}", end='\r') # For debugging

            finally:
                request.release() # Release the request to free up buffers

            # Check if GLib main loop has quit (e.g., due to GStreamer error/EOS)
            if loop.is_running():
                GLib.MainContext.default().iteration(False) # Process GStreamer events
            else: # GStreamer loop has stopped
                print("GStreamer loop stopped. Exiting video loop.")
                break


    except KeyboardInterrupt:
        print("\nStopping stream due to KeyboardInterrupt...")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
    finally:
        print("Cleaning up resources...")
        if args.local_display:
            cv2.destroyAllWindows()

        if gst_pipeline:
            print("Stopping GStreamer pipeline...")
            gst_pipeline.set_state(Gst.State.NULL)
        
        if loop and loop.is_running():
            loop.quit() # Ensure GLib main loop is quit if it was running

        if picam2 and picam2.started: # Check if picam2 object exists and was started
            print("Stopping Picamera2...")
            picam2.stop()
        
        print("Cleanup finished.")

if __name__ == "__main__":
    main()