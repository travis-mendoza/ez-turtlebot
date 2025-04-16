#!/bin/bash

# Stops video streams from the Raspberry Pi Camera Module
#
# USAGE:
#   ./stop_video_stream.sh
#
# This script will stop any running GStreamer pipelines that use:
#   - libcamerasrc (for streaming_scripts/pi/stream_video_to_pc.sh)
#   - kvssink (for streaming_scripts/pi/stream_video_to_AWS.sh)
#   - Any other gst-launch-1.0 video streams

echo "Stopping all video streams..."

# Kill any GStreamer pipelines using libcamerasrc (for regular streaming)
pkill -f "gst-launch-1.0.*libcamerasrc"

# Kill any GStreamer pipelines using kvssink (for AWS streaming)
pkill -f "gst-launch-1.0.*kvssink"

# For backward compatibility, also kill any v4l2src streams
pkill -f "gst-launch-1.0.*v4l2src"

# Check if any streams were actually stopped
if [ $? -eq 0 ]; then
  echo "Video streams successfully stopped."
else
  echo "No active video streams were found."
fi
