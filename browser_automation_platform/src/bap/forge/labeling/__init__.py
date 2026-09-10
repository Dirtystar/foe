"""Assisted labelling for the Forge weakening-badge grading set.

A small tool to build the ~15-20 frame ground-truth set the badge detector will
be graded against (Milestone 2). It is deliberately *not* the detector: it only
records where the badges are and what percentage each shows, so accuracy can
later be measured against human-confirmed truth.

Design mirrors the rest of the app: the state and file format live in Qt-free,
fully tested logic (`model`, `session`), the optional CV pre-suggester lives in
`suggest` (degrades gracefully when OpenCV is absent), and the PySide6 window in
`app` is a thin view over the session.
"""
