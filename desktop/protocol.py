"""Validated, compact UDP hand tracking transport + standalone OSC encoding.

Security model: an ephemeral six-digit pairing code helps avoid accidental input
on a trusted LAN; it is NOT encryption, authentication against eavesdroppers,
or a substitute for network isolation.
"""
from __future__ import annotations

import json
import math
import struct
import time
from dataclasses import dataclass

PORT = 8766
LANDMARK_COUNT = 21
BONES = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (0, 9), (9, 10), (10, 11), (11, 12),
    (0, 13), (13, 14), (14, 15), (15, 16),
    (0, 17), (17, 18), (18, 19), (19, 20),
    (5, 9), (9, 13), (13, 17),
)


@dataclass(frozen=True)
class HandPacket:
    hand: str
    seq: int
    points: tuple[tuple[float, float, float], ...]
    pinch: float
    received_at: float


def parse_packet(raw: bytes, code: str, *, now: float | None = None) -> HandPacket | None:
    """Drop malformed / unauthorized UDP packets safely without exceptions."""
    if len(raw) > 4096 or len(raw) < 30:
        return None
    try:
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            return None
        if obj.get('v') != 1 or obj.get('kind') != 'hand':
            return None
        if obj.get('code') != code:
            return None
        hand = obj.get('hand')
        if hand not in ('Left', 'Right'):
            return None
        seq = obj.get('seq')
        if type(seq) is not int or not 0 <= seq <= 2**31 - 1:
            return None
        data = obj.get('points')
        if not isinstance(data, list) or len(data) != LANDMARK_COUNT:
            return None
        points = []
        for p in data:
            if not isinstance(p, list) or len(p) != 3:
                return None
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in p):
                return None
            x, y, z = map(float, p)
            if not (0 <= x <= 1 and 0 <= y <= 1 and -2 <= z <= 2):
                return None
            points.append((x, y, z))
        pinch = obj.get('pinch')
        if type(pinch) not in (int, float) or not math.isfinite(pinch) or not 0 <= pinch <= 1:
            return None
        return HandPacket(hand, seq, tuple(points), float(pinch), time.monotonic() if now is None else now)
    except (ValueError, TypeError, UnicodeDecodeError, KeyError, OverflowError):
        return None


def _osc_pad(blob: bytes) -> bytes:
    return blob + b'\0' * ((4 - len(blob) % 4) % 4)


def _osc_string(value: str) -> bytes:
    return _osc_pad(value.encode('utf-8') + b'\0')


def encode_osc(address: str, *args: str | int | float) -> bytes:
    """OSC 1.0 datagram encoder; no external dependency."""
    if not address.startswith('/') or '\0' in address:
        raise ValueError('OSC address must start with / and contain no NUL')
    tags = ','
    values = bytearray()
    for v in args:
        if type(v) is str:
            tags += 's'
            values.extend(_osc_string(v))
        elif type(v) is int:
            tags += 'i'
            values.extend(struct.pack('>i', v))
        elif type(v) is float and math.isfinite(v):
            tags += 'f'
            values.extend(struct.pack('>f', v))
        else:
            raise ValueError(f'Unsupported OSC arg: {v!r}')
    return _osc_string(address) + _osc_string(tags) + values


ZONES = {
    'A': (0.23, 0.48, 0.17),
    'B': (0.77, 0.48, 0.17),
    'C': (0.50, 0.74, 0.14),
}


class ZoneTracker:
    """Normalized 2D zones with distinct entry/exit margins and dwell.

    This is not metric 3D XR hand tracking. Tracking loss clears active state
    separately and never fabricates an EXIT event.
    """

    def __init__(self, dwell_s: float = .055, enter_margin: float = .015, exit_margin: float = .025):
        self.dwell_s = dwell_s
        self.enter_margin = enter_margin
        self.exit_margin = exit_margin
        self.state: dict[tuple[str, str], dict] = {}

    def update(self, hand: str, x: float, y: float, now: float) -> list[tuple[str, str, str]]:
        events = []
        for zone, (zx, zy, radius) in ZONES.items():
            key = (hand, zone)
            state = self.state.setdefault(key, {'active': False, 'candidate': None, 'since': now})
            distance = math.hypot(x - zx, y - zy)
            desired = (distance < radius - self.enter_margin) if not state['active'] else not (distance > radius + self.exit_margin)
            if desired == state['active']:
                state['candidate'] = None
                continue
            if state['candidate'] != desired:
                state['candidate'] = desired
                state['since'] = now
            elif now - state['since'] >= self.dwell_s:
                state['active'] = desired
                state['candidate'] = None
                events.append((hand, zone, 'enter' if desired else 'exit'))
        return events

    def tracking_lost(self, hand: str) -> list[tuple[str, str, str]]:
        events = []
        for (h, zone), state in self.state.items():
            if h == hand:
                if state['active']:
                    events.append((hand, zone, 'tracking-lost'))
                state['active'] = False
                state['candidate'] = None
        return events

    def is_active(self, hand: str, zone: str) -> bool:
        return bool(self.state.get((hand, zone), {}).get('active', False))
