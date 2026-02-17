#!/bin/bash
# Start Xvfb (Virtual Monitor)
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99
# Start PulseAudio (Virtual Sound Card)
pulseaudio -D --exit-idle-time=-1 --system=false
# Create the "Null Sink" that FFmpeg and Chrome will use
pactl load-module module-null-sink sink_name=VirtualSink sink_properties=device.description="Virtual_Speaker"
# Run your Python bot (passing arguments from the command line)
python3 rena_bot_pilot.py "$@"