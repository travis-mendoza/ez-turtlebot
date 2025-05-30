#!/bin/bash

# Path to a test video file
VIDEO_FILE="./nav2.mp4"

# YouTube RTMP URL
YOUTUBE_URL="rtmp://a.rtmp.youtube.com/live2/$YT_STREAM_KEY"

# ffmpeg command: re-encode and stream to YouTube
ffmpeg -re -stream_loop -1 -i "$VIDEO_FILE" \
  -c:v libx264 -preset veryfast -tune zerolatency -b:v 2000k -maxrate 2000k -bufsize 4000k \
  -g 60 -pix_fmt yuv420p -f flv "$YOUTUBE_URL"