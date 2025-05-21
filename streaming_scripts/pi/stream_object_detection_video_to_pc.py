"""
stream_object_detection_video_to_pc.py - Object detection demo for IMX500 AI Camera with FFmpeg RTP streaming

This script uses the IMX500 AI Camera for object detection
and streams the output to a remote PC using FFmpeg for RTP.

Usage:
    python stream_object_detection_video_to_pc.py --model /path/to/model.rpk --ip 192.168.1.100 --port 5000
"""
import argparse
import sys
from functools import lru_cache
from typing import List, Optional

import cv2
import numpy as np

from picamera2 import MappedArray, Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput
from picamera2.devices import IMX500
from picamera2.devices.imx500 import (NetworkIntrinsics,
                                      postprocess_nanodet_detection)

# --- Constants for default paths ---
DEFAULT_MODEL_PATH = "/usr/share/imx500-models/imx500_network_ssd_mobilenetv2_fpnlite_320x320_pp.rpk"
DEFAULT_COCO_LABELS_PATH = "assets/coco_labels.txt" # Assumes 'assets' dir in CWD or a globally accessible one

# --- Global variable for detections, initialized ---
# This will store the last successfully parsed detections.
last_detections: List['Detection'] = []
# This will store the results to be drawn by the callback.
last_results: Optional[List['Detection']] = None


class Detection:
    def __init__(self, coords, category, conf, metadata):
        """Create a Detection object, recording the bounding box, category and confidence."""
        self.category = category
        self.conf = conf
        # Ensure picam2 is defined in the scope where Detection instances are created (it is, in __main__)
        self.box = imx500.convert_inference_coords(coords, metadata, picam2)


def parse_detections(metadata: dict) -> List['Detection']:
    """Parse the output tensor into a number of detected objects, scaled to the ISP output."""
    global last_detections # To update and return cached detections on failure
    # Accessing global 'intrinsics' and 'args' is common in scripts after __main__ setup
    bbox_normalization = intrinsics.bbox_normalization
    bbox_order = intrinsics.bbox_order
    threshold = args.threshold
    iou = args.iou
    max_detections = args.max_detections

    np_outputs = imx500.get_outputs(metadata, add_batch=True)
    input_w, input_h = imx500.get_input_size()
    if np_outputs is None:
        return last_detections # Return previous detections if current frame yields none
    
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
        # Ensure boxes is a list of arrays/tuples before zipping
        # np.array_split already returns a list. zip(*boxes) is correct.
        split_boxes = np.array_split(boxes, 4, axis=1)
        processed_boxes = zip(*split_boxes)


    current_detections = [
        Detection(box, category, score, metadata)
        for box, score, category in zip(processed_boxes if intrinsics.postprocess != "nanodet" else boxes, scores, classes) # Use correct boxes variable
        if score > threshold
    ]
    last_detections = current_detections # Cache the new detections
    return current_detections


@lru_cache
def get_labels() -> List[str]:
    """Gets and caches the labels, filtering out ignored ones."""
    # Accessing global 'intrinsics'
    labels = intrinsics.labels if intrinsics.labels else []

    if intrinsics.ignore_dash_labels:
        labels = [label for label in labels if label and label != "-"]
    return labels


def draw_detections(request, stream="main"):
    """Draw the detections for this request onto the ISP output."""
    # Accessing global 'last_results', 'intrinsics', 'imx500'
    detections = last_results
    if detections is None:
        return
    
    labels = get_labels()
    with MappedArray(request, stream) as m:
        for detection_obj in detections: # Renamed 'detection' to 'detection_obj' to avoid conflict
            x, y, w, h = detection_obj.box
            label_text = f"{labels[int(detection_obj.category)]} ({detection_obj.conf:.2f})"

            (text_width, text_height), baseline = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            text_x = x + 5
            text_y = y + 15

            # Create a copy of the array to draw the background with opacity
            overlay = m.array.copy()

            # Draw the background rectangle on the overlay
            cv2.rectangle(overlay,
                          (text_x, text_y - text_height - baseline//2), # Adjusted for better background fit
                          (text_x + text_width, text_y + baseline//2),
                          (255, 255, 255),
                          cv2.FILLED)

            alpha = 0.30
            cv2.addWeighted(overlay, alpha, m.array, 1 - alpha, 0, m.array)

            # Draw the text on top of the background
            cv2.putText(m.array, label_text, (text_x, text_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

            # Draw detection box
            cv2.rectangle(m.array, (x, y), (x + w, y + h), (0, 255, 0, 0), thickness=2)

        if intrinsics.preserve_aspect_ratio:
            b_x, b_y, b_w, b_h = imx500.get_roi_scaled(request)
            color = (255, 0, 0)  # red
            cv2.putText(m.array, "ROI", (b_x + 5, b_y + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
            cv2.rectangle(m.array, (b_x, b_y), (b_x + b_w, b_y + b_h), (255, 0, 0, 0))


def get_args():
    parser = argparse.ArgumentParser(description="IMX500 Object Detection with FFmpeg RTP Streaming") # Added description
    parser.add_argument("--model", type=str, help="Path of the model",
                        default=DEFAULT_MODEL_PATH)
    parser.add_argument("--fps", type=int, help="Frames per second", default=30)
    parser.add_argument("--bbox-normalization", action=argparse.BooleanOptionalAction, help="Normalize bbox")
    parser.add_argument("--bbox-order", choices=["yx", "xy"], default="yx",
                        help="Set bbox order yx -> (y0, x0, y1, x1) xy -> (x0, y0, x1, y1)")
    parser.add_argument("--threshold", type=float, default=0.55, help="Detection threshold")
    parser.add_argument("--iou", type=float, default=0.65, help="Set iou threshold")
    parser.add_argument("--max-detections", type=int, default=10, help="Set max detections")
    parser.add_argument("--ignore-dash-labels", action=argparse.BooleanOptionalAction, help="Remove '-' labels ")
    parser.add_argument("--postprocess", choices=["", "nanodet"],
                        default=None, help="Run post process of type")
    parser.add_argument("-r", "--preserve-aspect-ratio", action=argparse.BooleanOptionalAction,
                        help="preserve the pixel aspect ratio of the input tensor")
    parser.add_argument("--labels", type=str,
                        help=f"Path to the labels file (default: {DEFAULT_COCO_LABELS_PATH} if not overridden by model intrinsics)")
    parser.add_argument("--print-intrinsics", action="store_true",
                        help="Print JSON network_intrinsics then exit")
    # FFmpeg streaming options
    parser.add_argument("--ip", type=str, default="127.0.0.1", help="IP address to stream to")
    parser.add_argument("--port", type=int, default=5000, help="Port to stream to")
    parser.add_argument("--bitrate", type=int, default=2000000, help="Bitrate for H.264 encoding")
    parser.add_argument("--width", type=int, default=640, help="Stream width")
    parser.add_argument("--height", type=int, default=480, help="Stream height")
    parser.add_argument("--local-display", action="store_true", help="Show video locally as well")
    return parser.parse_args()


if __name__ == "__main__":
    args = get_args()

    imx500 = IMX500(args.model) # This must be called before instantiation of Picamera2
    intrinsics = imx500.network_intrinsics
    if not intrinsics:
        intrinsics = NetworkIntrinsics()
        intrinsics.task = "object detection"
    elif intrinsics.task != "object detection":
        print("Error: Network is not an object detection task.", file=sys.stderr)
        sys.exit(1) # Exit if not an object detection task

    # Override intrinsics from args
    for key, value in vars(args).items():
        if key == 'labels' and value is not None:
            try:
                with open(value, 'r') as f:
                    intrinsics.labels = f.read().splitlines()
            except FileNotFoundError:
                print(f"Error: Specified labels file '{value}' not found.", file=sys.stderr)
                sys.exit(1)
        elif hasattr(intrinsics, key) and value is not None:
            setattr(intrinsics, key, value)

    # Defaults for labels if not set by model or args
    if intrinsics.labels is None:
        default_labels_path = args.labels if args.labels else DEFAULT_COCO_LABELS_PATH
        try:
            with open(default_labels_path, "r") as f:
                intrinsics.labels = f.read().splitlines()
            if not args.labels: # Inform if default was used
                 print(f"Using default labels from: {default_labels_path}")
        except FileNotFoundError:
            print(f"Error: Default labels file '{default_labels_path}' not found. Object names may not be displayed.", file=sys.stderr)
            intrinsics.labels = [] # Set to empty list to avoid errors later, but detections will lack names
    intrinsics.update_with_defaults()

    if args.print_intrinsics:
        print(intrinsics)
        sys.exit(0) # Exit after printing

    picam2 = Picamera2(imx500.camera_num) # Define picam2 here so it's in scope for Detection class
    
    picam2_started = False
    encoder_started = False

    try:
        video_config = picam2.create_video_configuration(
            main={"size": (args.width, args.height), "format": "RGB888"},
            controls={"FrameRate": args.fps},
            buffer_count=12 
        )

        imx500.show_network_fw_progress_bar()
        picam2.start(video_config, show_preview=args.local_display)
        picam2_started = True

        if intrinsics.preserve_aspect_ratio:
            imx500.set_auto_aspect_ratio()

        encoder = H264Encoder(bitrate=args.bitrate)
        # Using FFmpeg for RTP output
        output_command = f"-f h264 -y -an -r {args.fps} -c:v copy -f rtp rtp://{args.ip}:{args.port}"
        output = FfmpegOutput(output_command)
        
        encoder.output = output
        picam2.start_encoder(encoder)
        encoder_started = True

        print(f"Streaming to {args.ip}:{args.port} at {args.width}x{args.height}, {args.fps}fps, {args.bitrate/1000000:.1f}Mbps")
        print("To view the stream on the receiving end, run:")
        print(f"gst-launch-1.0 udpsrc port={args.port} caps=\"application/x-rtp, media=(string)video, clock-rate=(int)90000, encoding-name=(string)H264\" ! rtph264depay ! h264parse ! avdec_h264 ! videoconvert ! autovideosink")
        print("Alternatively, with ffplay: ffplay rtp://{args.ip}:{args.port}")


        picam2.pre_callback = draw_detections
        
        while True:
            metadata = picam2.capture_metadata()
            if metadata:
                 last_results = parse_detections(metadata)
            # If no metadata, last_results remains from previous frame, draw_detections handles None

    except KeyboardInterrupt:
        print("\nStopping stream due to KeyboardInterrupt...")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc() # Print full traceback for unexpected errors
    finally:
        print("Cleaning up resources...")
        if encoder_started:
            try:
                print("Stopping encoder...")
                picam2.stop_encoder()
            except Exception as e_enc:
                print(f"Error stopping encoder: {e_enc}", file=sys.stderr)
        if picam2_started:
            try:
                print("Stopping Picamera2...")
                picam2.stop()
            except Exception as e_cam:
                print(f"Error stopping Picamera2: {e_cam}", file=sys.stderr)
        print("Cleanup finished.")
