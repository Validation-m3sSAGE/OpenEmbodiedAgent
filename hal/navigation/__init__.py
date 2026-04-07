"""Navigation backends for HAL drivers."""

from __future__ import annotations

__all__ = ["NavigationEngine", "TargetNavigationBackend"]


def __getattr__(name: str):
    if name == "NavigationEngine":
        from hal.navigation.target_navigation_engine import NavigationEngine

        return NavigationEngine
    if name == "TargetNavigationBackend":
        from hal.navigation.target_navigation_backend import TargetNavigationBackend

        return TargetNavigationBackend
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
