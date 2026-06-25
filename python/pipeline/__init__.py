"""Torch Monkey Python pipeline package.

High-level pose-estimation stages:

* :mod:`pipeline.pose_estimator_2d` -- MediaPipe PoseLandmarker (BlazePose 33).
* :mod:`pipeline.pose_estimator_3d`  -- MotionBERT 3D lifter -> SMPL_24 meters.

Modules are importable even when ``mediapipe`` / ``torch`` are absent.
"""
