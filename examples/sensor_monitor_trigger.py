"""Example TriggerEnvironment: Sensor Monitor.

Demonstrates how to create a TriggerEnvironment subclass and
pre-register triggers for third-party developers.

This example simulates a sensor monitoring environment with:
- Observation space: temperature, humidity, battery_level
- Action space: set_alarm, adjust_threshold, send_notification
- A pre-built TemperatureAlertTrigger that fires when temp > threshold

Usage
-----
from examples.sensor_monitor_trigger import SensorMonitorEnv, TemperatureAlertTrigger

# Register with the trigger registry
registry.register(SensorMonitorEnv)

# Instantiate for a session
session = registry.instantiate("sensor_monitor", session_key="cli:direct")
session.add_trigger(TemperatureAlertTrigger())
session.start()
"""

from __future__ import annotations

import random
from datetime import datetime
from typing import Any

from PhyAgentOS.triggers.base import TriggerEnvironment
from PhyAgentOS.triggers.trigger import BaseTrigger, TriggerContext, TriggerState


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

class SensorMonitorEnv(TriggerEnvironment):
    """Simulated sensor monitoring environment.

    Provides temperature, humidity, and battery_level observations.
    Supports set_alarm, adjust_threshold, and send_notification actions.
    """

    name = "sensor_monitor"
    description = "Simulated sensor monitoring station with temperature, humidity, and battery readings."
    tick_interval = 5.0  # 5-second observation update cycle

    def __init__(self, **kwargs: Any) -> None:
        self._temperature: float = 22.0
        self._humidity: float = 45.0
        self._battery: float = 100.0
        self._alarm_threshold: float = 35.0
        self._alarm_active: bool = False
        self._running = False

    # -- Spaces---------------------------------------------------------------

    def get_observation_space(self) -> dict[str, Any]:
        return {
            "temperature": {"type": "float", "unit": "celsius", "range": [-40, 80]},
            "humidity": {"type": "float", "unit": "percent", "range": [0, 100]},
            "battery_level": {"type": "float", "unit": "percent", "range": [0, 100]},
        }

    def get_action_space(self) -> dict[str, Any]:
        return {
            "set_alarm": {
                "description": "Activate or deactivate the temperature alarm.",
                "params": {"active": "bool"},
            },
            "adjust_threshold": {
                "description": "Set the temperature alarm threshold.",
                "params": {"threshold": "float"},
            },
            "send_notification": {
                "description": "Send an alert notification.",
                "params": {"message": "string"},
            },
        }

    def get_global_observation(self) -> dict[str, Any]:
        return {
            "station_id": "sensor_station_001",
            "location": "Lab Room B",
            "sensor_model": "DHT22",
            "alarm_threshold": self._alarm_threshold,
        }

    def get_current_observation(self) -> dict[str, Any]:
        return {
            "timestamp": datetime.now().isoformat(),
            "stale": False,
            "source": "sensor_station_001",
            "payload": {
                "temperature": round(self._temperature, 1),
                "humidity": round(self._humidity, 1),
                "battery_level": round(self._battery, 1),
            },
        }

    # -- Lifecycle ------------------------------------------------------------

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    # -- Action execution -----------------------------------------------------

    def execute_action(self, action_type: str, params: dict[str, Any]) -> dict[str, Any]:
        # Developer note: Actions are executed synchronously on the environment
        # side.  For long-running actions (e.g. robot motion), consider starting
        # a background task here and returning immediately with status="queued",
        # then updating the observation with the result when the action completes.
        if action_type == "set_alarm":
            self._alarm_active = params.get("active", True)
            return {"status": "succeeded", "result_text": f"Alarm {'activated' if self._alarm_active else 'deactivated'}"}

        if action_type == "adjust_threshold":
            self._alarm_threshold = float(params.get("threshold", 35.0))
            return {"status": "succeeded", "result_text": f"Threshold set to {self._alarm_threshold}°C"}

        if action_type == "send_notification":
            msg = params.get("message", "Alert!")
            return {"status": "succeeded", "result_text": f"Notification sent: {msg}"}

        return {"status": "failed", "error_code": "INVALID_PARAMS", "result_text": f"Unknown action: {action_type}"}

    # -- Simulation (called externally to advance state) ----------------------

    def simulate_tick(self) -> None:
        """Simulate one tick of sensor readings (for testing)."""
        self._temperature += random.uniform(-1.5, 2.0)
        self._temperature = max(-40, min(80, self._temperature))
        self._humidity += random.uniform(-2, 2)
        self._humidity = max(0, min(100, self._humidity))
        self._battery = max(0, self._battery - random.uniform(0, 0.05))


# ---------------------------------------------------------------------------
# Pre-built Trigger
# ---------------------------------------------------------------------------

class TemperatureAlertTrigger(BaseTrigger):
    """Fires when temperature exceeds the environment's alarm threshold.

    Demonstrates:
    - Reading filtered observations (only'temperature' key)
    - Emitting messages to the agent
    - Firing actions on the environment
    - Using muted vs. visible messages
    """

    name = "temp_alert"
    description = "Alerts when temperature exceeds alarm threshold."
    watched_observations = ["temperature"]
    allowed_actions = ["set_alarm", "send_notification"]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._last_alert_temp: float | None = None

    async def on_tick(self, ctx: TriggerContext) -> None:
        obs = ctx.get_current_observation()
        temp = obs.get("payload", {}).get("temperature")
        if temp is None:
            return

        global_obs = ctx.get_global_observation()
        threshold = global_obs.get("alarm_threshold", 35.0)

        if temp > threshold:
            # Only alert once per crossing (avoid repeat alerts)
            if self._last_alert_temp is None or self._last_alert_temp <= threshold:
                await ctx.emit_message(
                    f"🔥 Temperature alert: {temp:.1f}°C exceeds threshold {threshold}°C!",
                    priority="high",
                )
                ctx.enqueue_action("send_notification", {
                    "message": f"ALERT: Temperature {temp:.1f}°C > {threshold}°C",
                })
        else:
            # Temperature back to normal — muted log message
            if self._last_alert_temp is not None and self._last_alert_temp > threshold:
                await ctx.emit_message(
                    f"✅ Temperature normalized: {temp:.1f}°C (threshold: {threshold}°C)",
                    muted=True,  # Don't wake the agent, but log it
                )
        self._last_alert_temp = temp

    async def on_start(self, ctx: TriggerContext) -> None:
        await ctx.emit_message(
            f"🌡️ Temperature monitoring started (threshold: "
            f"{ctx.get_global_observation().get('alarm_threshold', '?')}°C)",
)
