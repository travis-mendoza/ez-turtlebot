#!/bin/bash

# Starts a video stream from the Raspberry Pi Camera Module using GStreamer
# and sends it to both a remote PC and AWS Kinesis Video Streams
#
# USAGE:
#   1. Copy .env.pi_example to .env and modify the variables as needed
#   2. Run the script:
#      ./stream_video_to_both.sh

# Load environment variables from .env if it exists
if [ -f .env ]; then
  source .env
fi

# Check if AWS stream is needed
AWS_ENABLED="${AWS_ENABLED:-true}"

# Video stream settings with defaults
VIDEO_WIDTH="${VIDEO_WIDTH:-1920}"
VIDEO_HEIGHT="${VIDEO_HEIGHT:-1080}"
VIDEO_FRAMERATE="${VIDEO_FRAMERATE:-30/1}"
VIDEO_BITRATE="${VIDEO_BITRATE:-4096}"
VIDEO_UDP_PORT="${VIDEO_UDP_PORT:-5000}"

# AWS settings
KVS_STREAM_NAME="${KVS_STREAM_NAME:-my-kvs-stream}"

echo "GST_PLUGIN_PATH=${GST_PLUGIN_PATH}"
echo "Streaming video to PC: ${REMOTE_PC_IP}:${VIDEO_UDP_PORT}"

if [ "$AWS_ENABLED" = "true" ]; then
  echo "Streaming video to AWS KVS: ${KVS_STREAM_NAME}"
  
  # Check if AWS credentials are available
  if [ -z "$AWS_ACCESS_KEY_ID" ] || [ -z "$AWS_SECRET_ACCESS_KEY" ]; then
    echo "Warning: AWS credentials may not be set. Make sure they are available in your environment or .env file."
  fi
  
  # Pipeline with both outputs
  gst-launch-1.0 -v \
    libcamerasrc \
    ! "video/x-raw,width=${VIDEO_WIDTH},height=${VIDEO_HEIGHT},framerate=${VIDEO_FRAMERATE}" \
    ! videoconvert \
    ! tee name=t \
    t. ! queue ! videoscale ! "video/x-raw,width=640,height=480" \
       ! x264enc bitrate=1000 bframes=0 key-int-max=30 tune=zerolatency speed-preset=ultrafast byte-stream=true \
       ! video/x-h264,profile=baseline,stream-format=avc,alignment=au \
       ! h264parse \
       ! kvssink stream-name="${KVS_STREAM_NAME}" storage-size=512 \
    t. ! queue ! videorate ! "video/x-raw,framerate=${VIDEO_FRAMERATE}" \
       ! x264enc tune=zerolatency bitrate=${VIDEO_BITRATE} speed-preset=superfast \
       ! h264parse \
       ! rtph264pay config-interval=1 pt=96 \
       ! udpsink host=${REMOTE_PC_IP} port=${VIDEO_UDP_PORT}
else
  # Original PC-only pipeline
  echo "AWS streaming disabled. Streaming to PC only."
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
fi
