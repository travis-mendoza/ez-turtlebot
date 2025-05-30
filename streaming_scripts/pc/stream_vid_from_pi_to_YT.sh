#! /bin/bash

ffmpeg -fflags +genpts -i tcp://$PI_IP:8000 -f lavfi -i anullsrc -c:v copy -c:a aac -b:a 128k -shortest -f flv "rtmp://a.rtmp.youtube.com/live2/$YT_STREAM_KEY"
