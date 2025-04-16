#!/bin/bash

# Stops audio streams from the Raspberry Pi
#
# USAGE:
#   ./stop_audio_stream.sh
#
# This script will stop any running GStreamer pipelines that use:
#   - alsasrc (for streaming_scripts/pi/stream_audio_to_remote.sh)
#   - Any other gst-launch-1.0 audio streams

echo "Stopping all audio streams..."

# Kill any GStreamer pipelines using alsasrc (for audio streaming)
pkill -f "gst-launch-1.0.*alsasrc"

# For backward compatibility, also kill specific device streams
pkill -f "gst-launch-1.0.*alsasrc device=hw:3,0"

# Check if any streams were actually stopped
if [ $? -eq 0 ]; then
  echo "Audio streams successfully stopped."
else
  echo "No active audio streams were found."
fi
