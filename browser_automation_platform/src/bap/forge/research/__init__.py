"""Experimental classifier research (Milestone 5C) — OBSERVE-ONLY.

Nothing in this subpackage is wired into the production scan / decision path. It
imports the production v1 percentage classifier read-only as the benchmark
baseline and never mutates it, never clicks, never moves the cursor, and touches
no detector-threshold, geometry, weakening, or UI code. It exists solely to
compare candidate percentage classifiers under a leakage-free grouped evaluation.
"""
