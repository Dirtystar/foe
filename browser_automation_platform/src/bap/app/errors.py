from __future__ import annotations


class CompositionError(Exception):
    """Raised when validated configuration cannot be assembled into runtime
    objects — e.g. it references an action type or analyzer type no registry
    provides, or a comparison operator the rule layer does not implement.

    This is distinct from ConfigError (malformed input): the config is
    well-formed, but the runtime cannot honour it.
    """


__all__ = ["CompositionError"]
