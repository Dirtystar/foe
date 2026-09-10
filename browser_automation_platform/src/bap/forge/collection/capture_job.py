"""Async-ready Capture-All pipeline core (Milestone 5D P0) — OBSERVE-ONLY, Qt-free.

The GUI must never run capture / detection / classification / dataset writes on its
event-loop thread (that froze the window for ~24 s over 8 Worlds). This module owns
the whole batch as a **thread-agnostic** job: it processes Worlds **sequentially**
(bounded concurrency — browser capture 1, CPU analysis 1 by default), reports every
stage transition through a callback, catches per-World failures without aborting the
batch, supports cooperative cancellation, and persists batch progress after each
World so a crash/close can resume only the unfinished Worlds.

Why a single worker thread is the right boundary (not multiprocessing): OpenCV
releases the GIL during its heavy native ops (template matching / colour / resize),
so running this loop on ONE background thread lets the Qt event loop keep ticking —
measured GUI-tick max gap ~10 ms while a worker ran 4× ``build_scan``. Multiprocessing
was rejected: it would force pickling full-frame images and cannot hold a browser
``Page``/CDP context across a process boundary. The detector/classifier/dataset code
is imported and called unchanged — outputs are byte/semantically identical.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum


class Stage(str, Enum):
    WAITING = "waiting"
    CAPTURING = "capturing"
    ANALYSING = "analysing"
    SAVING = "saving"
    COMPLETED = "completed"
    SKIPPED = "skipped"       # duplicate — nothing new added
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL = {Stage.COMPLETED, Stage.SKIPPED, Stage.FAILED, Stage.CANCELLED}


@dataclass
class WorldProgress:
    alias: str
    position: int              # 1-based within the batch
    total: int
    stage: Stage
    duration_ms: float | None = None
    frame: str | None = None
    detected: int = 0
    classified: int = 0
    unknown: int = 0
    warnings: list = field(default_factory=list)   # capture-quality notes
    error: dict | None = None  # {stage, type, reason, fix}

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["stage"] = self.stage.value
        return d


@dataclass
class JobSummary:
    total: int
    completed: int
    skipped: int
    failed: int
    cancelled: int
    duration_ms: float
    was_cancelled: bool
    results: list = field(default_factory=list)

    def message(self) -> str:
        if self.was_cancelled:
            preserved = self.completed + self.skipped
            return (f"Cancelled after {self.completed + self.skipped + self.failed} / "
                    f"{self.total} Worlds — {preserved} result(s) preserved.")
        return (f"Done: {self.completed} new · {self.skipped} duplicate(s) · "
                f"{self.failed} failed of {self.total} Worlds.")


class CaptureJob:
    """One Capture-All batch. ``worlds`` is a list of ``(alias, world_obj)``.
    ``capture_fn(world) -> (image_or_None, error_or_None)`` performs the read-only
    screenshot (an I/O worker step; may block, and should carry its own timeout).
    ``analyze_fn(image, world, session) -> result`` runs the existing
    detector/classifier + atomic dataset write (defaults to
    :func:`bap.forge.collection.capture.capture_frame`)."""

    def __init__(self, worlds, *, capture_fn, analyze_fn=None, session=None,
                 dataset_dir=None, cv2_threads: int | None = 1,
                 quality_fn=None):
        self._worlds = list(worlds)
        self._capture_fn = capture_fn
        self._analyze_fn = analyze_fn
        self._session = session
        self._dataset_dir = dataset_dir
        self._cv2_threads = cv2_threads
        self._quality_fn = quality_fn
        self._cancel = threading.Event()

    def cancel(self) -> None:
        """Cooperative cancel: stop scheduling new Worlds. The in-flight World's
        atomic write is allowed to finish so no partial data is left behind."""
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def _analyze(self):
        if self._analyze_fn is not None:
            return self._analyze_fn
        # Build the detector + classifier ONCE per batch and reuse them for every
        # World (the default capture_frame would otherwise rebuild the classifier
        # bank per call). Same objects → byte/semantically identical outputs.
        from bap.forge.collection.capture import capture_frame, default_classifier
        from bap.forge.detection.detector import BadgeDetector
        detector = BadgeDetector()
        classifier = default_classifier()

        def analyze(image, *, world=None, session=None, dataset_dir=None):
            return capture_frame(image, world=world, session=session,
                                 dataset_dir=dataset_dir, detector=detector,
                                 classifier=classifier)
        return analyze

    def run(self, on_progress=None) -> JobSummary:
        """Process every World sequentially, emitting ``WorldProgress`` for each
        stage. Runs on the caller's thread — the GUI calls this from a worker
        thread. Never raises for a per-World failure; the batch continues."""
        emit = on_progress or (lambda p: None)
        # Bound OpenCV's internal threads so (workers × cv2-threads) can't saturate
        # an already-busy machine. 1 analysis worker × a small cv2 cap stays smooth.
        if self._cv2_threads is not None:
            try:
                import cv2
                cv2.setNumThreads(int(self._cv2_threads))
            except Exception:
                pass

        analyze = self._analyze()
        total = len(self._worlds)
        results: list[WorldProgress] = []
        completed = skipped = failed = cancelled = 0
        t0 = time.perf_counter()
        if self._session is not None:
            self._session.start_batch([a for a, _ in self._worlds])

        for i, (alias, world) in enumerate(self._worlds, start=1):
            if self._cancel.is_set():
                p = WorldProgress(alias, i, total, Stage.CANCELLED)
                results.append(p)
                cancelled += 1
                emit(p)
                continue

            w_t0 = time.perf_counter()
            emit(WorldProgress(alias, i, total, Stage.CAPTURING))
            image, error = self._safe_capture(world)
            if error or image is None:
                p = WorldProgress(alias, i, total, Stage.FAILED,
                                  duration_ms=(time.perf_counter() - w_t0) * 1000,
                                  error=_err("capture", error or "no image",
                                             "Re-attach the World and confirm the tab is open."))
                results.append(p)
                failed += 1
                if self._session is not None:
                    self._session.mark_batch(alias, ok=False)
                emit(p)
                continue

            warnings = self._safe_quality(image, world)
            emit(WorldProgress(alias, i, total, Stage.ANALYSING, warnings=warnings))
            try:
                res = analyze(image, world=world, session=self._session,
                              dataset_dir=self._dataset_dir)
            except Exception as exc:   # analysis/write failure — contained
                p = WorldProgress(alias, i, total, Stage.FAILED,
                                  duration_ms=(time.perf_counter() - w_t0) * 1000,
                                  warnings=warnings,
                                  error=_err("analyze", f"{type(exc).__name__}: {exc}",
                                             "Check the frame/calibration; the other Worlds continue."))
                results.append(p)
                failed += 1
                if self._session is not None:
                    self._session.mark_batch(alias, ok=False)
                emit(p)
                continue

            stage = Stage.COMPLETED if res.is_new else Stage.SKIPPED
            p = WorldProgress(alias, i, total, stage,
                              duration_ms=(time.perf_counter() - w_t0) * 1000,
                              frame=res.frame, detected=res.detected,
                              classified=res.classified, unknown=res.unknown,
                              warnings=warnings)
            results.append(p)
            if stage is Stage.COMPLETED:
                completed += 1
            else:
                skipped += 1
            if self._session is not None:
                self._session.mark_batch(alias, ok=True)
            emit(p)

        if self._session is not None:
            self._session.end_batch(cancelled=self._cancel.is_set())
        return JobSummary(total=total, completed=completed, skipped=skipped,
                          failed=failed, cancelled=cancelled,
                          duration_ms=(time.perf_counter() - t0) * 1000,
                          was_cancelled=self._cancel.is_set(), results=results)

    def _safe_capture(self, world):
        try:
            image, error = self._capture_fn(world)
            return image, error
        except Exception as exc:   # timeouts / detached browser surface here
            return None, f"{type(exc).__name__}: {exc}"

    def _safe_quality(self, image, world):
        if self._quality_fn is None:
            return []
        try:
            return [w.message if hasattr(w, "message") else str(w)
                    for w in self._quality_fn(image, world)]
        except Exception:
            return []


def _err(stage: str, reason: str, fix: str) -> dict:
    etype = "timeout" if "timeout" in reason.lower() else "error"
    return {"stage": stage, "type": etype, "reason": reason, "fix": fix}


__all__ = ["CaptureJob", "WorldProgress", "JobSummary", "Stage", "TERMINAL"]
