"""Tests for resolve_device_input() — sounddevice est mocké (pas de PortAudio requis)."""

from __future__ import annotations

import types

import pytest

from bruittrack.capture import resolve_device_input


def _install_fake_sd(devices: list[dict]):
    """Inject a fake sounddevice module returning `devices` from query_devices()."""
    fake = types.ModuleType("sounddevice")
    fake.query_devices = lambda *a, **kw: devices
    return {"sounddevice": fake}


def test_resolve_alsa_index_string_returns_as_is():
    assert resolve_device_input("plughw:2,0") == "plughw:2,0"


def test_resolve_numeric_digit_converts_to_int():
    assert resolve_device_input("4") == 4


def test_resolve_exact_name_match_first_pass(monkeypatch):
    devices = [
        {"name": "/DEFAULT INPUT", "max_input_channels": 0},
        {"name": "Some Other Device", "max_input_channels": 1},
        {"name": "M-Track Plus: USB Audio (hw:2,0)", "max_input_channels": 2},
    ]
    monkeypatch.setitem(__import__("sys").modules, "sounddevice",
                        _install_fake_sd(devices)["sounddevice"])
    assert resolve_device_input("M-Track Plus: USB Audio (hw:2,0)") == 2


def test_resolve_substring_match_second_pass(monkeypatch):
    devices = [
        {"name": "/DEFAULT INPUT", "max_input_channels": 0},
        {"name": "M-Track Plus: USB Audio (hw:2,0)", "max_input_channels": 2},
    ]
    monkeypatch.setitem(__import__("sys").modules, "sounddevice",
                        _install_fake_sd(devices)["sounddevice"])
    assert resolve_device_input("M-Track Plus") == 1


def test_resolve_unknown_name_raises(monkeypatch):
    devices = [{"name": "Other Deck", "max_input_channels": 2}]
    monkeypatch.setitem(__import__("sys").modules, "sounddevice",
                        _install_fake_sd(devices)["sounddevice"])
    with pytest.raises(ValueError):
        resolve_device_input("No Such Device")
