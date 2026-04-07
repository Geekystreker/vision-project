# Requirements Document

## Introduction

This document defines the requirements for the Jarvis Autonomous Rover system. The system enables a Windows PC ("Brain") with an NVIDIA RTX 5060 GPU to act as a centralized master controller that ingests a live video stream from an ESP32-CAM ("Vision Node"), runs YOLO-based person detection, and autonomously issues real-time WebSocket commands to control a pan/tilt camera mount ("Neck") and a four-wheel drive chassis ("Legs Node"). The system integrates into the existing Jarvis codebase, reusing the EventBus, StateManager, and RoverController infrastructure.

---

## Glossary

- **Brain**: The Windows PC running the Python control software with an NVIDIA RTX 5060 GPU.
- **Vision_Node**: The ESP32-CAM microcontroller that streams JPEG video frames and controls the pan/tilt servo mount and flashlight LED.
- **Legs_Node**: The ESP32 Dev Board wired to an L298N motor driver that controls the four DC drive wheels.
- **Camera_Stream**: The continuous JPEG frame stream served over WebSocket at `ws://<IP>/Camera` on the Vision_Node.
- **Servo_Controller**: The WebSocket endpoint at `ws://<IP>/ServoInput` on the Vision_Node that accepts CSV pan/tilt/light commands.
- **Motor_Controller**: The WebSocket endpoint at `ws://<IP>/Motors` on the Legs_Node that accepts single-character drive commands.
- **Stream_Thread**: The dedicated background thread on the Brain responsible for consuming raw JPEG bytes from the Camera_Stream.
- **Detection_Engine**: The YOLO-based object detection component running on the Brain's GPU that identifies persons in video frames.
- **Tracking_Controller**: The Brain-side control loop that translates Detection_Engine bounding box output into servo and motor commands.
- **Pan_Angle**: The horizontal servo position in degrees (0–180), where 90 is center.
- **Tilt_Angle**: The vertical servo position in degrees (0–180), where 90 is center.
- **Bounding_Box**: The pixel-coordinate rectangle (x, y, width, height) returned by the Detection_Engine around a detected person.
- **Frame_Center**: The pixel coordinate at the horizontal and vertical midpoint of the current video frame.
- **Dead_Zone**: A configurable pixel tolerance around the Frame_Center within which no servo correction is issued.
- **Autonomous_Mode**: The operational state in which the Brain runs the Detection_Engine and Tracking_Controller without manual keyboard input.
- **Manual_Mode**: The operational state in which the Brain accepts keyboard commands to drive the rover and control the camera.
- **EventBus**: The existing singleton event bus (`core/event_bus.py`) used for decoupled inter-module communication.
- **RoverController**: The existing module (`modules/rover_control.py`) that manages rover motion state and command dispatch.
- **Config**: The existing configuration module (`config.py`) extended to hold network and tracking parameters.

---

## Requirements

### Requirement 1: WebSocket Connection Management

**User Story:** As a developer, I want the Brain to maintain persistent, non-blocking WebSocket connections to both Nodes, so that a dropped packet or temporary network outage does not crash the main application.

#### Acceptance Criteria

1. THE Brain SHALL establish a WebSocket connection to the Vision_Node Camera_Stream endpoint on startup.
2. THE Brain SHALL establish a WebSocket connection to the Vision_Node Servo_Controller endpoint on startup.
3. THE Brain SHALL establish a WebSocket connection to the Legs_Node Motor_Controller endpoint on startup.
4. WHEN a WebSocket connection to any Node is lost, THE Brain SHALL attempt to reconnect at intervals of no more than 5 seconds without terminating the main process.
5. WHILE a WebSocket connection to a Node is unavailable, THE Brain SHALL continue operating all other connected subsystems without interruption.
6. IF a WebSocket send operation raises an exception, THEN THE Brain SHALL log the error via the EventBus and suppress the exception to prevent propagation to the calling thread.
7. THE Brain SHALL apply a socket-level timeout of no more than 2 seconds to all WebSocket receive operations to prevent indefinite blocking.

---

### Requirement 2: Non-Blocking Video Stream Ingestion

**User Story:** As a developer, I want the camera stream to be consumed in a dedicated background thread, so that frame buffering lag does not accumulate and the OpenCV display loop remains responsive.

#### Acceptance Criteria

1. THE Brain SHALL run the Camera_Stream receive loop exclusively within the Stream_Thread, separate from the main display loop.
2. THE Stream_Thread SHALL discard all buffered frames and retain only the most recently received JPEG byte payload at any given time.
3. WHEN the Stream_Thread receives a valid JPEG byte payload, THE Stream_Thread SHALL make it available to the main loop within 50 milliseconds of receipt.
4. IF the Camera_Stream WebSocket raises an exception during receive, THEN THE Stream_Thread SHALL log the error via the EventBus and attempt reconnection without terminating.
5. THE Stream_Thread SHALL be started as a daemon thread so that it does not prevent the main process from exiting.

---

### Requirement 3: Video Frame Display

**User Story:** As a developer, I want the Brain to decode and display the live camera feed in an OpenCV window, so that I can visually monitor what the rover sees in real time.

#### Acceptance Criteria

1. WHEN a new JPEG frame is available from the Stream_Thread, THE Brain SHALL decode it into an OpenCV BGR image and render it in a named display window.
2. THE Brain SHALL render the display window at the native resolution of the received JPEG frame without upscaling or downscaling.
3. WHILE Autonomous_Mode is active, THE Brain SHALL overlay the Bounding_Box rectangle and a center-point marker on the displayed frame for each detected person.
4. IF a received byte payload cannot be decoded as a valid JPEG image, THEN THE Brain SHALL discard the payload and display the last successfully decoded frame.

---

### Requirement 4: Manual Keyboard Drive Control

**User Story:** As a developer, I want to drive the rover manually using keyboard keys in the OpenCV window, so that I can test movement and positioning without autonomous tracking active.

#### Acceptance Criteria

1. WHEN the 'W' key is pressed in the display window, THE Brain SHALL send the 'F' command to the Motor_Controller.
2. WHEN the 'S' key is pressed in the display window, THE Brain SHALL send the 'B' command to the Motor_Controller.
3. WHEN the 'A' key is pressed in the display window, THE Brain SHALL send the 'L' command to the Motor_Controller.
4. WHEN the 'D' key is pressed in the display window, THE Brain SHALL send the 'R' command to the Motor_Controller.
5. WHEN the spacebar is pressed in the display window, THE Brain SHALL send the 'S' (Stop) command to the Motor_Controller.
6. WHEN a drive key is released in the display window, THE Brain SHALL send the 'S' (Stop) command to the Motor_Controller.
7. WHILE Autonomous_Mode is active, THE Brain SHALL ignore keyboard drive commands.

---

### Requirement 5: Manual Pan/Tilt Servo Control

**User Story:** As a developer, I want to control the camera pan/tilt mount manually using keyboard keys, so that I can aim the camera during testing and setup.

#### Acceptance Criteria

1. WHEN the arrow-left key is pressed in the display window, THE Brain SHALL send a `Pan,<angle>` command to the Servo_Controller decreasing the Pan_Angle by a configurable step value.
2. WHEN the arrow-right key is pressed in the display window, THE Brain SHALL send a `Pan,<angle>` command to the Servo_Controller increasing the Pan_Angle by a configurable step value.
3. WHEN the arrow-up key is pressed in the display window, THE Brain SHALL send a `Tilt,<angle>` command to the Servo_Controller increasing the Tilt_Angle by a configurable step value.
4. WHEN the arrow-down key is pressed in the display window, THE Brain SHALL send a `Tilt,<angle>` command to the Servo_Controller decreasing the Tilt_Angle by a configurable step value.
5. THE Brain SHALL clamp Pan_Angle and Tilt_Angle to the inclusive range [0, 180] before sending any servo command.
6. WHILE Autonomous_Mode is active, THE Brain SHALL ignore manual pan/tilt keyboard commands.

---

### Requirement 6: YOLO Person Detection

**User Story:** As a developer, I want the Brain to run GPU-accelerated YOLO inference on each video frame, so that it can detect and locate a person in the camera's field of view.

#### Acceptance Criteria

1. WHEN Autonomous_Mode is activated, THE Detection_Engine SHALL load a YOLOv8 model onto the CUDA device before processing any frames.
2. WHEN a decoded video frame is available and Autonomous_Mode is active, THE Detection_Engine SHALL run inference on the frame and return all detected bounding boxes with class labels and confidence scores.
3. THE Detection_Engine SHALL filter inference results to retain only detections with the class label "person" and a confidence score of 0.5 or greater.
4. WHEN multiple persons are detected in a single frame, THE Detection_Engine SHALL select the detection with the largest Bounding_Box area as the primary tracking target.
5. WHEN no person is detected in a frame, THE Detection_Engine SHALL emit a no-detection signal via the EventBus so the Tracking_Controller can respond appropriately.
6. THE Detection_Engine SHALL run inference on the CUDA device when an NVIDIA GPU is available, and fall back to CPU inference when a CUDA device is not available.

---

### Requirement 7: Autonomous Pan/Tilt Tracking

**User Story:** As a developer, I want the camera to automatically pan and tilt to keep a detected person centered in the frame, so that the rover maintains visual lock on its target.

#### Acceptance Criteria

1. WHEN a Bounding_Box is available and Autonomous_Mode is active, THE Tracking_Controller SHALL calculate the horizontal and vertical offset between the Bounding_Box center and the Frame_Center.
2. WHEN the horizontal offset exceeds the Dead_Zone threshold, THE Tracking_Controller SHALL send a `Pan,<angle>` command to the Servo_Controller to reduce the horizontal offset.
3. WHEN the vertical offset exceeds the Dead_Zone threshold, THE Tracking_Controller SHALL send a `Tilt,<angle>` command to the Servo_Controller to reduce the vertical offset.
4. WHILE the horizontal and vertical offsets are both within the Dead_Zone, THE Tracking_Controller SHALL not send any servo commands for that frame.
5. THE Tracking_Controller SHALL clamp all computed Pan_Angle and Tilt_Angle values to the inclusive range [0, 180] before issuing any servo command.
6. THE Tracking_Controller SHALL apply a configurable proportional gain factor to scale pixel offset into servo angle correction steps.

---

### Requirement 8: Autonomous Drive Control

**User Story:** As a developer, I want the rover to automatically drive toward or stop near a detected person based on their apparent size in the frame, so that the rover maintains a consistent following distance.

#### Acceptance Criteria

1. WHEN a Bounding_Box is available and Autonomous_Mode is active, THE Tracking_Controller SHALL compute the Bounding_Box area as a fraction of the total frame area.
2. WHEN the Bounding_Box area fraction is below a configurable minimum threshold, THE Tracking_Controller SHALL send the 'F' (Forward) command to the Motor_Controller.
3. WHEN the Bounding_Box area fraction is above a configurable maximum threshold, THE Tracking_Controller SHALL send the 'B' (Backward) command to the Motor_Controller.
4. WHILE the Bounding_Box area fraction is between the minimum and maximum thresholds, THE Tracking_Controller SHALL send the 'S' (Stop) command to the Motor_Controller.
5. WHEN no person is detected for a continuous duration exceeding a configurable timeout, THE Tracking_Controller SHALL send the 'S' (Stop) command to the Motor_Controller.
6. THE Tracking_Controller SHALL route all drive commands through the existing RoverController to maintain consistent motion state tracking.

---

### Requirement 9: Autonomous Mode Toggle

**User Story:** As a developer, I want to toggle autonomous tracking on and off with a single key press, so that I can switch between manual control and autonomous operation without restarting the application.

#### Acceptance Criteria

1. WHEN the 'T' key is pressed in the display window, THE Brain SHALL transition from Manual_Mode to Autonomous_Mode if currently in Manual_Mode.
2. WHEN the 'T' key is pressed in the display window, THE Brain SHALL transition from Autonomous_Mode to Manual_Mode if currently in Autonomous_Mode.
3. WHEN transitioning to Manual_Mode, THE Tracking_Controller SHALL send the 'S' (Stop) command to the Motor_Controller before relinquishing control.
4. WHEN transitioning to Manual_Mode, THE Tracking_Controller SHALL send servo commands to return Pan_Angle and Tilt_Angle to 90 degrees before relinquishing control.
5. THE Brain SHALL emit the current mode change via the EventBus so other subscribers (e.g., the HUD) can reflect the updated state.

---

### Requirement 10: Configuration Parameters

**User Story:** As a developer, I want all network addresses, thresholds, and tuning parameters to be defined in a single configuration file, so that I can adjust the system without modifying logic code.

#### Acceptance Criteria

1. THE Config SHALL define the Vision_Node IP address and WebSocket port for the Camera_Stream endpoint.
2. THE Config SHALL define the Vision_Node IP address and WebSocket port for the Servo_Controller endpoint.
3. THE Config SHALL define the Legs_Node IP address and WebSocket port for the Motor_Controller endpoint.
4. THE Config SHALL define the Dead_Zone pixel threshold used by the Tracking_Controller.
5. THE Config SHALL define the proportional gain factor used by the Tracking_Controller for servo angle correction.
6. THE Config SHALL define the minimum and maximum Bounding_Box area fraction thresholds used for drive control decisions.
7. THE Config SHALL define the no-detection stop timeout duration in seconds.
8. THE Config SHALL define the YOLO model path or model name used by the Detection_Engine.

---

### Requirement 11: Error Handling and Logging

**User Story:** As a developer, I want all errors from network, inference, and control subsystems to be logged through the existing EventBus, so that the application remains stable and all failures are observable in the Jarvis HUD.

#### Acceptance Criteria

1. WHEN any WebSocket operation raises an exception, THE Brain SHALL emit a LOG_MESSAGE event via the EventBus containing the subsystem name and exception message.
2. WHEN the Detection_Engine encounters an inference error, THE Brain SHALL emit a LOG_MESSAGE event via the EventBus and skip the affected frame without halting the tracking loop.
3. WHEN a servo or motor command fails to send, THE Brain SHALL emit a LOG_MESSAGE event via the EventBus and continue the control loop.
4. THE Brain SHALL not raise unhandled exceptions to the main thread from any background thread.
