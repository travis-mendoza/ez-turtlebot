#!/bin/bash

# Starts a video stream from the Raspberry Pi Camera Module using GStreamer
#
# USAGE:
#   1. Copy .env.pi_example to .env and modify the variables as needed
#   2. Run the script:
#      ./stream_video_to_pc.sh

# Load environment variables from .env if it exists
if [ -f .env ]; then
  source .env
fi

# Video stream settings with defaults
VIDEO_WIDTH="${VIDEO_WIDTH:-1920}"
VIDEO_HEIGHT="${VIDEO_HEIGHT:-1080}"
VIDEO_FRAMERATE="${VIDEO_FRAMERATE:-30/1}"
VIDEO_BITRATE="${VIDEO_BITRATE:-4096}"
VIDEO_UDP_PORT="${VIDEO_UDP_PORT:-5000}"

echo "GST_PLUGIN_PATH=${GST_PLUGIN_PATH}"
echo "Streaming video to ${REMOTE_PC_IP}:${UDP_PORT}"
echo "Starting GStreamer pipeline..."

# GStreamer pipeline to capture from webcam, encode, and send over UDP
gst-launch-1.0 -v \
    libcamerasrc \
    ! "video/x-raw,width=${VIDEO_WIDTH},height=${VIDEO_HEIGHT},framerate=${VIDEO_FRAMERATE}" \
    ! videoconvert \
    ! videorate \
    ! "video/x-raw,framerate=${VIDEO_FRAMERATE}" \
    ! x264enc tune=zerolatency bitrate=${VIDEO_BITRATE} speed-preset=superfast \
    ! h264parse \
    ! rtph264pay config-interval=1 pt=96 \
    ! udpsink host=${REMOTE_PC_IP} port=${VIDEO_UDP_PORT}
