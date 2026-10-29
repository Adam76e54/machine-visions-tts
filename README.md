# machine-visions-tts
This is a repo for Tool Tracking System (TTS) prototype created by a 3-person team over a two-day hackathon for the opening of Trinity College Dublin's E3 Foundry building. A Raspberry Pi was used with a webcam and a simple limit switch circuit to take photos upon opening a toolbox drawer. The image was sent to a locally hosted app which used a machine-vision model to recognise if a specific tool was present. Note that most of the code was LLM-accelerated using Claude Code & Perplexity in the interest of time constraints.

# 3d-prints
Tool holders were 3D printed to encourage users to avoid stacking tools on top of each other. A stand for the webcam was also printed to hold position it over the drawer. A lever to hold the switch closed when the door was closed was also used. 

# machine-vision
Google's MobileNetV2 was fine-tuned using pytorch on images of tools in our drawer. The model was hosted on Google Cloud. An app was ran locally which fed the webcam images to the neural network and displayed the results.

# raspberry-pi-4
A Raspberry Pi 4 running Raspberry Pi OS Lite was used to drive a webcam with openCV's API. A limit switch circuit with a pull up resistor was used alongside the GPIOZero API to detect the drawer opening. Images were sent via WiFi using the Requests API to a locally-hosted app. 
