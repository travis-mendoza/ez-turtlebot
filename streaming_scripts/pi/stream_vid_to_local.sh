#! /bin/bash

libcamera-vid -t 0 --inline --listen --width 1280 --height 720 --framerate 30 --bitrate 2500000 -o tcp://0.0.0.0:8000 --codec h264
