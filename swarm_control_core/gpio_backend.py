#!/usr/bin/env python3
"""GPIO backend selection for Raspberry Pi motor control.

The motor layer uses a small RPi.GPIO-shaped API. This module provides that API
through multiple backends so Pi 5 can use gpiochip-based GPIO while older Pi
setups can continue to use the classic RPi.GPIO path.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable


class GpioBackendUnavailable(RuntimeError):
    """Raised when a requested GPIO backend cannot be initialized."""


class _BaseBackend:
    BCM = "BCM"
    OUT = "OUT"
    HIGH = 1
    LOW = 0

    name = "unknown"

    def setmode(self, mode: Any) -> None:
        return None

    def setwarnings(self, enabled: bool) -> None:
        return None


class _RpiGpioBackend(_BaseBackend):
    def __init__(self) -> None:
        import RPi.GPIO as gpio  # type: ignore

        self._gpio = gpio
        self.BCM = gpio.BCM
        self.OUT = gpio.OUT
        self.HIGH = gpio.HIGH
        self.LOW = gpio.LOW
        module_path = str(getattr(gpio, "__file__", "") or "").lower()
        self.name = "rpi-lgpio" if "rpi_lgpio" in module_path or "rpi-lgpio" in module_path else "RPi.GPIO"

    def setmode(self, mode: Any) -> None:
        self._gpio.setmode(mode)

    def setwarnings(self, enabled: bool) -> None:
        self._gpio.setwarnings(enabled)

    def setup(self, pin: int, mode: Any) -> None:
        self._gpio.setup(pin, mode)

    def output(self, pin: int, value: int) -> None:
        self._gpio.output(pin, value)

    def PWM(self, pin: int, hz: int) -> Any:
        return self._gpio.PWM(pin, hz)

    def cleanup(self) -> None:
        self._gpio.cleanup()


class _LgpioPwm:
    def __init__(self, lgpio: Any, handle: int, pin: int, hz: int) -> None:
        self._lgpio = lgpio
        self._handle = handle
        self._pin = int(pin)
        self._hz = int(hz)

    def start(self, duty: float) -> None:
        self.ChangeDutyCycle(duty)

    def ChangeDutyCycle(self, duty: float) -> None:
        clamped = max(0.0, min(100.0, float(duty)))
        self._lgpio.tx_pwm(self._handle, self._pin, self._hz, clamped)

    def stop(self) -> None:
        self._lgpio.tx_pwm(self._handle, self._pin, 0, 0)


class _LgpioBackend(_BaseBackend):
    name = "lgpio"

    def __init__(self) -> None:
        import lgpio  # type: ignore

        self._lgpio = lgpio
        self._handle = self._open_gpiochip()
        self._claimed: set[int] = set()

    def _open_gpiochip(self) -> int:
        errors: list[str] = []
        for chip in _candidate_gpiochips():
            try:
                return self._lgpio.gpiochip_open(chip)
            except Exception as exc:
                errors.append(f"gpiochip{chip}: {exc}")
        raise GpioBackendUnavailable("; ".join(errors) or "no gpiochip candidates")

    def setup(self, pin: int, mode: Any) -> None:
        if mode != self.OUT:
            raise ValueError(f"Unsupported lgpio mode: {mode!r}")
        pin = int(pin)
        if pin in self._claimed:
            return
        try:
            self._lgpio.gpio_claim_output(self._handle, pin, 0)
        except Exception:
            try:
                self._lgpio.gpio_free(self._handle, pin)
            except Exception:
                pass
            self._lgpio.gpio_claim_output(self._handle, pin, 0)
        self._claimed.add(pin)

    def output(self, pin: int, value: int) -> None:
        pin = int(pin)
        if pin not in self._claimed:
            self.setup(pin, self.OUT)
        self._lgpio.gpio_write(self._handle, pin, 1 if value else 0)

    def PWM(self, pin: int, hz: int) -> _LgpioPwm:
        pin = int(pin)
        if pin not in self._claimed:
            self.setup(pin, self.OUT)
        return _LgpioPwm(self._lgpio, self._handle, pin, hz)

    def cleanup(self) -> None:
        for pin in list(self._claimed):
            try:
                self._lgpio.gpio_free(self._handle, pin)
            except Exception:
                pass
        self._claimed.clear()
        try:
            self._lgpio.gpiochip_close(self._handle)
        except Exception:
            pass


class _GpiozeroPwm:
    def __init__(self, device: Any) -> None:
        self._device = device

    def start(self, duty: float) -> None:
        self.ChangeDutyCycle(duty)

    def ChangeDutyCycle(self, duty: float) -> None:
        self._device.value = max(0.0, min(100.0, float(duty))) / 100.0

    def stop(self) -> None:
        self._device.off()


class _GpiozeroBackend(_BaseBackend):
    name = "gpiozero"

    def __init__(self) -> None:
        from gpiozero import DigitalOutputDevice, PWMOutputDevice  # type: ignore
        from gpiozero.pins.lgpio import LGPIOFactory  # type: ignore

        self._DigitalOutputDevice = DigitalOutputDevice
        self._PWMOutputDevice = PWMOutputDevice
        self._pin_factory = self._make_pin_factory(LGPIOFactory)
        self._outputs: dict[int, Any] = {}
        self._pwms: dict[int, Any] = {}

    def _make_pin_factory(self, factory_cls: Any) -> Any:
        for chip in _candidate_gpiochips():
            try:
                return factory_cls(chip=chip)
            except Exception:
                continue
        return factory_cls()

    def setup(self, pin: int, mode: Any) -> None:
        if mode != self.OUT:
            raise ValueError(f"Unsupported gpiozero mode: {mode!r}")
        pin = int(pin)
        if pin not in self._outputs and pin not in self._pwms:
            self._outputs[pin] = self._DigitalOutputDevice(pin, initial_value=False, pin_factory=self._pin_factory)

    def output(self, pin: int, value: int) -> None:
        pin = int(pin)
        self.setup(pin, self.OUT)
        self._outputs[pin].value = 1 if value else 0

    def PWM(self, pin: int, hz: int) -> _GpiozeroPwm:
        pin = int(pin)
        old_output = self._outputs.pop(pin, None)
        if old_output is not None:
            old_output.close()
        device = self._PWMOutputDevice(pin, frequency=int(hz), initial_value=0, pin_factory=self._pin_factory)
        self._pwms[pin] = device
        return _GpiozeroPwm(device)

    def cleanup(self) -> None:
        for device in list(self._outputs.values()) + list(self._pwms.values()):
            try:
                device.close()
            except Exception:
                pass
        self._outputs.clear()
        self._pwms.clear()
        try:
            self._pin_factory.close()
        except Exception:
            pass


def _model_text() -> str:
    for path in (Path("/proc/device-tree/model"), Path("/sys/firmware/devicetree/base/model")):
        try:
            return path.read_text(encoding="utf-8", errors="ignore").replace("\x00", "").strip()
        except OSError:
            continue
    return ""


def _candidate_gpiochips() -> Iterable[int]:
    requested = os.environ.get("SWARM_GPIOCHIP", "").strip()
    candidates: list[int] = []
    if requested:
        candidates.append(int(requested))
    model = _model_text().lower()
    if "raspberry pi 5" in model:
        candidates.extend([4, 0])
    else:
        candidates.extend([0, 4])
    seen: set[int] = set()
    for chip in candidates:
        if chip not in seen:
            seen.add(chip)
            yield chip


def _backend_order() -> list[str]:
    requested = os.environ.get("SWARM_GPIO_BACKEND", "auto").strip().lower()
    if requested and requested != "auto":
        return [requested]
    return ["lgpio", "gpiozero", "rpi_gpio"]


def select_gpio_backend() -> tuple[Any | None, str, list[str]]:
    errors: list[str] = []
    for backend_name in _backend_order():
        try:
            if backend_name in {"lgpio", "direct_lgpio"}:
                backend = _LgpioBackend()
            elif backend_name in {"gpiozero", "gpio_zero"}:
                backend = _GpiozeroBackend()
            elif backend_name in {"rpi_gpio", "rpi.gpio", "rpi-lgpio", "rpi_lgpio"}:
                backend = _RpiGpioBackend()
            else:
                errors.append(f"{backend_name}: unknown backend")
                continue
            return backend, backend.name, errors
        except Exception as exc:
            errors.append(f"{backend_name}: {exc}")
    return None, "mock", errors

