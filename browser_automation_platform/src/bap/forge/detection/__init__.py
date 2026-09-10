"""Forge weakening-badge detection (Milestone 3).

Detects on-map weakening pills (centre, bounding box, confidence), classifies
each percentage without OCR, and grades itself against the human-confirmed
grading set. Observe-only — nothing here clicks or drives the game; the Vision
Debugger renders what the detector sees and what a strategy *would* do.
"""
