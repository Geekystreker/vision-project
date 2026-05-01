# vision-project

Jarvis rover PC brain for ESP32-CAM video, YOLO person tracking, servo pan/tilt, motor control, voice, and the V.I.S.I.O.N HUD.

## Pull And Run On Another Windows Device

```powershell
git clone https://github.com/Geekystreker/vision-project.git
cd vision-project
git checkout finalv2
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-gpu.txt
.\.venv\Scripts\python.exe launcher.py
```

Use `requirements-gpu.txt` for the RTX/CUDA setup. The runtime model weights such as `yolo26n.pt`, `yolov8n.pt`, and other generated `.pt` files are intentionally not committed; Ultralytics will download/load them locally as needed.

## Current Network Defaults


You can override these without editing code by setting:

```powershell
$env:ROVER_CAMERA_IP="192.168.137.100"
$env:ROVER_ESP32_IP="192.168.137.101"
$env:VISION_PERF_PROFILE="rtx5060"
```
