"""
stream_object_detection_video_to_YT.py - Object detection with overlays to YouTube Live

This script uses the IMX500 AI Camera for object detection, draws overlays,
and streams the output to YouTube Live using ffmpeg for minimal latency.

Usage:
    python stream_object_detection_video_to_YT.py --model /path/to/model.rpk --stream-key your-youtube-stream-key
    Uses environment variables for YouTube stream key, width, height, FPS, bitrate if not specified.
"""
import argparse
import sys
import os
import subprocess
from functools import lru_cache
from typing import List, Optional

import cv2
import numpy as np

from picamera2 import MappedArray, Picamera2
from picamera2.devices import IMX500
from picamera2.devices.imx500 import (NetworkIntrinsics,
                                      postprocess_nanodet_detection)

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
ffmpeg_process = None

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

def get_args_yt_local():
    global args_global
    parser = argparse.ArgumentParser(description="IMX500 Object Detection to YouTube Live")
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
    default_stream_key = os.environ.get('YT_STREAM_KEY')
    parser.add_argument("--stream-key", type=str, default=default_stream_key, required=default_stream_key is None, help="YouTube Live stream key (env: YT_STREAM_KEY)")
    script_default_bitrate_kbps = 2500  # YouTube recommended bitrate (in Kbps)
    env_bitrate_kbps_str = os.environ.get('VIDEO_BITRATE')
    default_bitrate_kbps = script_default_bitrate_kbps
    if env_bitrate_kbps_str:
        try: default_bitrate_kbps = int(env_bitrate_kbps_str)
        except ValueError: print(f"Warning: Invalid VIDEO_BITRATE. Using default {default_bitrate_kbps} Kbps.", file=sys.stderr)
    parser.add_argument("--bitrate", type=int, default=default_bitrate_kbps, help=f"Target bitrate for H.264 encoding in Kbps (env: VIDEO_BITRATE, default: {default_bitrate_kbps} Kbps)")
    script_default_width = 1280  # YouTube recommended minimum for 720p
    env_width_str = os.environ.get('VIDEO_WIDTH')
    default_width = script_default_width
    if env_width_str:
        try: default_width = int(env_width_str)
        except ValueError: print(f"Warning: Invalid VIDEO_WIDTH. Using default {script_default_width}.", file=sys.stderr)
    parser.add_argument("--width", type=int, default=default_width, help=f"Stream width (env: VIDEO_WIDTH, default: {script_default_width})")
    script_default_height = 720  # YouTube recommended minimum for 720p
    env_height_str = os.environ.get('VIDEO_HEIGHT')
    default_height = script_default_height
    if env_height_str:
        try: default_height = int(env_height_str)
        except ValueError: print(f"Warning: Invalid VIDEO_HEIGHT. Using default {script_default_height}.", file=sys.stderr)
    parser.add_argument("--height", type=int, default=default_height, help=f"Stream height (env: VIDEO_HEIGHT, default: {script_default_height})")
    parser.add_argument("--local-display", action="store_true", help="Show video locally as well")
    args_global = parser.parse_args()
    return args_global

def start_ffmpeg_stream(args_val):
    """Start ffmpeg process for streaming to YouTube with silent audio and proper timestamps, using BGR format throughout."""
    ffmpeg_cmd = [
        'ffmpeg',
        '-fflags', '+genpts',  # Generate presentation timestamps
        '-f', 'rawvideo',
        '-pix_fmt', 'bgr24',  # Use BGR format throughout
        '-s', f'{args_val.width}x{args_val.height}',
        '-r', str(args_val.fps),
        '-i', '-',  # Read video from stdin
        '-f', 'lavfi',
        '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100',  # Silent audio
        '-c:v', 'libx264',
        '-preset', 'veryfast',
        '-tune', 'zerolatency',
        '-b:v', f'{args_val.bitrate}k',
        '-maxrate', f'{args_val.bitrate}k',
        '-bufsize', f'{2*args_val.bitrate}k',
        '-g', str(args_val.fps * 2),  # Keyframe interval (2 seconds)
        '-pix_fmt', 'yuv420p',
        '-c:a', 'aac',
        '-b:a', '128k',
        '-ar', '44100',
        '-shortest',  # End stream when video ends
        '-f', 'flv',
        f'rtmp://a.rtmp.youtube.com/live2/{args_val.stream_key}'
    ]
    return subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)

def main():
    global picam2, imx500, intrinsics, args_global, ffmpeg_process

    args_val = get_args_yt_local()

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

    # Start ffmpeg process
    ffmpeg_process = start_ffmpeg_stream(args_val)
    if not ffmpeg_process:
        print("Error: Failed to start ffmpeg process", file=sys.stderr)
        sys.exit(1)

    imx500.show_network_fw_progress_bar()
    picam2.start()
    print(f"Picamera2 started. Streaming to YouTube Live")
    if intrinsics.preserve_aspect_ratio: imx500.set_auto_aspect_ratio()

    try:
        while True:
            request = picam2.capture_request()
            try:
                metadata = request.get_metadata()
                if metadata: last_results = parse_detections(metadata)
                
                frame_array_rgb = request.make_array('main') # This is RGB
                frame_bgr = cv2.cvtColor(frame_array_rgb, cv2.COLOR_RGB2BGR)
                frame_with_overlays_bgr = draw_detections_on_array(frame_bgr, last_results, request)

                if args_val.local_display:
                    cv2.imshow("Local Preview", frame_with_overlays_bgr)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
                
                # Write BGR frame directly to ffmpeg process
                try:
                    ffmpeg_process.stdin.write(frame_with_overlays_bgr.tobytes())
                except IOError as e:
                    print(f"Error writing to ffmpeg: {e}", file=sys.stderr)
                    break
            finally:
                request.release()
            
    except KeyboardInterrupt:
        print("\nStopping stream due to KeyboardInterrupt...")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
        import traceback; traceback.print_exc()
    finally:
        print("Cleaning up resources...")
        if args_val.local_display: cv2.destroyAllWindows()
        if ffmpeg_process:
            print("Stopping ffmpeg process...")
            ffmpeg_process.stdin.close()
            ffmpeg_process.terminate()
            ffmpeg_process.wait()
        if picam2 and picam2.started:
            print("Stopping Picamera2...")
            picam2.stop()
        print("Cleanup finished.")

if __name__ == "__main__":
    main() 