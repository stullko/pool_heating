"""Diagnostics for Pool Heating Controller."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.data
    dec = data.decision
    model = data.model
    return {
        "config": dict(entry.data),
        "options": dict(entry.options),
        "mode": data.mode,
        "inputs": {
            "pool_temp": data.pool_temp,
            "outdoor_temp": data.outdoor_temp,
            "target_temp": data.target_temp,
            "switch_is_on": data.switch_is_on,
            "electricity_price": data.electricity_price,
            "power_w": data.power_w,
        },
        "decision": {
            "status": dec.status,
            "action": dec.action,
            "should_heat": dec.should_heat,
            "reason_sk": dec.reason_sk,
            "predicted_ready": dec.predicted_ready.isoformat() if dec.predicted_ready else None,
            "next_window": dec.next_window.isoformat() if dec.next_window else None,
            "required_hours": dec.required_hours,
            "energy_kwh": dec.energy_kwh,
        },
        "model": {
            "k": model.k,
            "r_a": model.r_a,
            "r_b": model.r_b,
            "solar": model.solar,
            "n_off": model.n_off,
            "n_on": model.n_on,
            "r2_k": model.r2_k,
            "confidence": model.confidence,
            "learning": model.learning,
        },
        "forecast": {
            "run_id": data.forecast_run_id,
            "available": data.forecast_available,
            "generated_at": data.forecast_generated_at.isoformat()
            if data.forecast_generated_at else None,
        },
    }
