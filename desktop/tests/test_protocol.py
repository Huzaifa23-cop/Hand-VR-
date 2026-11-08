import json
import struct

from desktop.protocol import BONES, ZoneTracker, encode_osc, parse_packet


def payload(hand='Right', code='314159', **updates):
    o = {'v': 1, 'kind': 'hand', 'seq': 1, 'code': code, 'hand': hand,
         'points': [[.25, .5, -.02] for _ in range(21)], 'pinch': .6}
    o.update(updates)
    return json.dumps(o).encode()


def test_valid():
    p = parse_packet(payload(), '314159', now=10)
    assert p.hand == 'Right' and p.seq == 1 and p.pinch == .6 and len(p.points) == 21
    assert p.received_at == 10


def test_invalid_rejected():
    assert parse_packet(payload(code='111111'), '314159') is None
    assert parse_packet(b'garbage', '314159') is None
    assert parse_packet(payload(points=[[.2, .5, 0]]), '314159') is None
    assert parse_packet(payload(pinch=float('nan')), '314159') is None
    assert parse_packet(payload(seq=True), '314159') is None
    assert parse_packet(payload(hand='Other'), '314159') is None
    assert parse_packet(payload(points=[[1.5, .5, 0]]*21), '314159') is None
    assert parse_packet(b'a'*6000, '314159') is None


def test_bones_valid():
    assert all(0 <= a < 21 and 0 <= b < 21 for a, b in BONES)


def test_osc_encoding():
    b = encode_osc('/handlink/test', 12, .5, 'abc')
    assert len(b) % 4 == 0
    assert b.startswith(b'/handlink/test\x00')
    assert b',ifs\x00' in b
    assert struct.pack('>i', 12) in b
    assert struct.pack('>f', .5) in b


def test_zone_entry_exit():
    z = ZoneTracker(dwell_s=.05)
    assert z.update('Right', .23, .48, 0) == []
    assert z.update('Right', .23, .48, .06) == [('Right', 'A', 'enter')]
    assert z.update('Right', .24, .48, .08) == []
    assert z.update('Right', .8, .1, .11) == []
    assert z.update('Right', .8, .1, .18) == [('Right', 'A', 'exit')]


def test_lost_not_exit():
    z = ZoneTracker(dwell_s=0)
    z.update('Left', .23, .48, 0)
    z.update('Left', .23, .48, .001)
    assert z.tracking_lost('Left') == [('Left', 'A', 'tracking-lost')]
    assert z.tracking_lost('Left') == []


def test_compact_hand_datagram_fits_single_lan_packet():
    # Android sends one hand per UDP datagram and rounds coords to four decimals.
    pkt = payload(points=[[.9999, .9999, -.9999] for _ in range(21)])
    assert len(pkt) < 1200
