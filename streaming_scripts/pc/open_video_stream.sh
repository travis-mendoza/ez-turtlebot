#!/bin/bash

# Opens the Raspberry Pi video stream using GStreamer
# USAGE:
#   1. In the Raspberry Pi, start the video stream
#   2. In the remote pc, copy .env.pc_example to .env and modify the variables as needed
#   3. In the remote pc, run the script:
#      ./open_video_stream.sh

# Load environment variables from .env if it exists
if [ -f .env ]; then
  source .env
fi

gst-launch-1.0 -v \
    udpsrc port=$VIDEO_UDP_PORT \
    ! "application/x-rtp,media=(string)video,clock-rate=(int)90000,encoding-name=(string)H264,payload=(int)96" \
    ! rtph264depay \
    ! h264parse \
    ! avdec_h264 \
    ! videoconvert \
    ! autovideosink sync=false
