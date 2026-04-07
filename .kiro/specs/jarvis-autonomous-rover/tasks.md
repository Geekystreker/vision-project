# Implementation Plan: Jarvis Autonomous Rover

## Overview

Implement the autonomous rover vision system in Python by adding five new modules (`vision_stream.py`, `servo_controller.py`, `detection_engine.py`, `tracking_controller.py`, `rover_vision_app.py`), extending `config.py` with `RoverConfig`, adding new `SystemEvents` constants, and wiring everything together. Each task builds incrementally so no code is left orphaned.

## Tasks

- [x] 1. Extend config.py and event_bus.py with new types
  - Add `RoverConfig` dataclass to `config.py` with all network, tracking, drive, timeout, and YOLO fields from the design
  - Add `ROVER_MODE_CHANGE`, `ROVER_NO_DETECTION`, and `ROVER_DETECTION` constants to `SystemEvents` in `core/event_bus.py`
  - Add `RoverMode` enum and `BoundingBox` dataclass (with `area`, `center_x`, `center_y` properties) to a new `modules/rover_types.py`
  - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 9.5_

- [x] 2. Implement VisionStream
  - [x] 2.1 Create `modules/vision_stream.py` with `VisionStream` class
    - Implement `start()`, `stop()`, `get_latest_frame()`, `is_connected()` as specified in the design
    - Background daemon thread uses `threading.Lock` to protect the latest-frame buffer
    - Reconnect loop logs all exceptions via `bus.emit(SystemEvents.LOG_MESSAGE, ...)` and sleeps `reconnect_interval`
    - Top-level `try/except Exception` wraps the entire thread `run()` body
    - _Requirements: 1.1, 1.4, 1.5, 1.7, 2.1, 2.2, 2.3, 2.4, 2.5, 11.1, 11.4_

  - [ ]* 2.2 Write property test for VisionStream latest-frame retention (P2)
    - **Property 2: Stream_Thread retains only the latest frame**
    - **Validates: Requirements 2.2**
    - Use `hypothesis` with `st.lists(st.binary(), min_size=1)` to feed N payloads; assert `get_latest_frame()` returns the last one
    - Tag: `# Feature: jarvis-autonomous-rover, Property 2: Stream_Thread retains only the latest frame`

  - [ ]* 2.3 Write property test for VisionStream exception handling (P3)
    - **Property 3: Stream recv exceptions are logged and reconnection is attempted**
    - **Validates: Requirements 2.4, 11.4**
    - Simulate WebSocket recv raising arbitrary exceptions; assert LOG_MESSAGE emitted and thread stays alive
    - Tag: `# Feature: jarvis-autonomous-rover, Property 3: Stream_Thread exceptions logged, thread alive`

- [x] 3. Implement ServoController
  - [x] 3.1 Create `modules/servo_controller.py` with `ServoController` class
    - Implement `start()`, `stop()`, `send(command: str)`, `is_connected()` as specified in the design
    - Keep-alive daemon thread with reconnect logic identical to `VisionStream`
    - `send()` wraps WebSocket send in `try/except`, logs via EventBus on failure, suppresses exception
    - _Requirements: 1.2, 1.4, 1.5, 1.6, 1.7, 11.1, 11.3_

  - [ ]* 3.2 Write property test for ServoController send exception suppression (P1)
    - **Property 1: WebSocket send exceptions are always logged and suppressed**
    - **Validates: Requirements 1.6, 11.1, 11.3**
    - Use `hypothesis` with exception subclass strategies; assert LOG_MESSAGE emitted and no exception propagates from `send()`
    - Tag: `# Feature: jarvis-autonomous-rover, Property 1: WS send exceptions logged & suppressed`

- [x] 4. Implement DetectionEngine
  - [x] 4.1 Create `modules/detection_engine.py` with `DetectionEngine` class
    - Implement `load()` selecting CUDA when available, CPU otherwise
    - Implement `detect(frame)` running YOLOv8 inference, filtering person class + confidence >= 0.5, returning largest bbox or None
    - On inference exception: log via EventBus, return None
    - Emit `ROVER_NO_DETECTION` when detect returns None; emit `ROVER_DETECTION` with BoundingBox otherwise
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 11.2_

  - [ ]* 4.2 Write property test for detection filter (P7)
    - **Property 7: Detection filter retains only high-confidence person detections**
    - **Validates: Requirements 6.3**
    - Use `hypothesis` with lists of arbitrary detection dicts; assert output contains only person class with conf >= 0.5
    - Tag: `# Feature: jarvis-autonomous-rover, Property 7: Detection filter`

  - [ ]* 4.3 Write property test for largest bbox selection (P8)
    - **Property 8: Largest bounding box is always selected as primary target**
    - **Validates: Requirements 6.4**
    - Use `hypothesis` with non-empty lists of BoundingBox; assert returned bbox has maximum area
    - Tag: `# Feature: jarvis-autonomous-rover, Property 8: Largest bbox selected`

  - [ ]* 4.4 Write unit tests for DetectionEngine
    - Test CUDA/CPU device selection by mocking `torch.cuda.is_available()`
    - Test that `detect()` returns None and emits `ROVER_NO_DETECTION` when no persons found
    - Test that inference exceptions are caught and None is returned

- [x] 5. Implement TrackingController
  - [x] 5.1 Create `modules/tracking_controller.py` with `TrackingController` class and `TrackingState` dataclass
    - Implement `update(bbox, frame_w, frame_h)`: compute offsets, apply gain, clamp angles, send servo/drive commands
    - Implement `reset()`: send 'S' via RoverController, send `Pan,90` and `Tilt,90` via ServoController
    - All servo angle values clamped to [0, 180] before dispatch
    - Drive command logic: 'F' when fraction < min, 'B' when fraction > max, 'S' when between thresholds
    - Route all drive commands through `RoverController.send_command()`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 9.3, 9.4_

  - [ ]* 5.2 Write property test for servo angle clamping (P6)
    - **Property 6: Servo angle clamping is always enforced**
    - **Validates: Requirements 5.5, 7.5**
    - Use `hypothesis` with `st.floats(min_value=-1000, max_value=1000)`; assert output is always in [0, 180]
    - Tag: `# Feature: jarvis-autonomous-rover, Property 6: Servo angle clamping`

  - [ ]* 5.3 Write property test for offset computation (P9)
    - **Property 9: Tracking offset computation is correct**
    - **Validates: Requirements 7.1**
    - Use `hypothesis` with integer bbox coords and frame dims; assert `offset_x == center_x - frame_w/2` and `offset_y == center_y - frame_h/2`
    - Tag: `# Feature: jarvis-autonomous-rover, Property 9: Offset computation`

  - [ ]* 5.4 Write property test for dead zone behavior (P10)
    - **Property 10: Dead zone suppresses servo commands; outside dead zone triggers correction**
    - **Validates: Requirements 7.2, 7.3, 7.4**
    - Use `hypothesis` with float offsets and integer dead_zone; assert no servo send within zone, servo send outside zone
    - Tag: `# Feature: jarvis-autonomous-rover, Property 10: Dead zone behavior`

  - [ ]* 5.5 Write property test for drive command from bbox fraction (P11)
    - **Property 11: Drive command matches bbox area fraction relative to thresholds**
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.4**
    - Use `hypothesis` with `st.floats(0, 1)` for fraction; assert 'F'/'B'/'S' matches threshold comparison
    - Tag: `# Feature: jarvis-autonomous-rover, Property 11: Drive command from fraction`

  - [ ]* 5.6 Write unit tests for TrackingController
    - Test no-detection timeout: simulate elapsed time > timeout, verify 'S' sent
    - Test `reset()` sends 'S', `Pan,90`, `Tilt,90`

- [x] 6. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement RoverVisionApp
  - [x] 7.1 Create `modules/rover_vision_app.py` with `RoverVisionApp` class
    - Implement OpenCV main loop: get latest frame, decode JPEG, run detection in Autonomous_Mode, call `tracking_controller.update()`, display frame with overlay
    - Implement `_decode_frame(data)`: use `cv2.imdecode`; on None result return last good frame (Property 4)
    - Implement `_handle_key(key)`: map W/A/S/D/Space to motor commands, arrows to servo pan/tilt, 'T' to mode toggle; suppress drive/servo keys in Autonomous_Mode (Property 5)
    - Implement `_toggle_mode()`: switch `RoverMode`, call `tracking_controller.reset()` on exit from Autonomous, emit `ROVER_MODE_CHANGE` via EventBus; wrap in try/except, log and revert on error
    - Draw bounding box rectangle and center-point marker overlay when in Autonomous_Mode and detection present
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 9.1, 9.2, 9.3, 9.4, 9.5_

  - [ ]* 7.2 Write property test for invalid JPEG frame handling (P4)
    - **Property 4: Invalid JPEG payloads preserve the last good frame**
    - **Validates: Requirements 3.4**
    - Use `hypothesis` with `st.binary()` for arbitrary bytes; assert last good frame returned and no exception propagates
    - Tag: `# Feature: jarvis-autonomous-rover, Property 4: Invalid JPEG preserves last good frame`

  - [ ]* 7.3 Write property test for autonomous mode keyboard suppression (P5)
    - **Property 5: Autonomous mode suppresses all keyboard drive and servo commands**
    - **Validates: Requirements 4.7, 5.6**
    - Use `hypothesis` with `st.sampled_from(DRIVE_KEYS + SERVO_KEYS)`; assert no motor/servo send called when mode is AUTONOMOUS
    - Tag: `# Feature: jarvis-autonomous-rover, Property 5: Autonomous mode suppresses keyboard commands`

  - [ ]* 7.4 Write property test for mode change EventBus emission (P12)
    - **Property 12: Mode change always emits an EventBus event**
    - **Validates: Requirements 9.5**
    - Use `hypothesis` with `st.sampled_from(RoverMode)`; assert `ROVER_MODE_CHANGE` emitted with new mode on every toggle
    - Tag: `# Feature: jarvis-autonomous-rover, Property 12: Mode change emits event`

  - [ ]* 7.5 Write property test for background thread exception isolation (P13)
    - **Property 13: Background thread exceptions never reach the main thread**
    - **Validates: Requirements 11.4**
    - Use `hypothesis` with exception subclass strategies on all thread `run()` methods; assert exceptions are caught and logged, not re-raised
    - Tag: `# Feature: jarvis-autonomous-rover, Property 13: Background thread exception isolation`

  - [ ]* 7.6 Write unit tests for RoverVisionApp
    - Test key mapping: W→F, S→B, A→L, D→R, Space→S, key release→S (one assertion per key)
    - Test mode toggle: Manual→Autonomous, Autonomous→Manual
    - Test mode exit side-effects: 'S' command sent, `Pan,90` and `Tilt,90` sent

- [x] 8. Wire RoverVisionApp into main.py
  - Instantiate `RoverConfig` with default values in `config.py`
  - Import and instantiate `RoverVisionApp` in `main.py`; start it in a daemon thread alongside the existing Qt event loop
  - Ensure `RoverVisionApp.stop()` is called in `MainController.stop()` for clean shutdown
  - _Requirements: 1.1, 1.2, 1.3_

- [x] 9. Create tests directory and test files
  - Create `tests/` directory with `__init__.py`
  - Create test file stubs: `test_vision_stream.py`, `test_servo_controller.py`, `test_detection_engine.py`, `test_tracking_controller.py`, `test_rover_vision_app.py`, `test_config.py`
  - Add `test_config.py` smoke test: assert all `RoverConfig` fields are present and values are within valid ranges
  - _Requirements: 10.1–10.8_

- [x] 10. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Each task references specific requirements for traceability
- Property tests use `hypothesis` with `@settings(max_examples=100)`
- All background threads must wrap their `run()` body in a top-level `try/except Exception` — no unhandled exceptions may reach the main thread
- The existing `RoverController`, `EventBus`, and `StateManager` are reused without modification
