"""HandLink Studio: local LAN receiver, hand-stage visualizer and OSC bridge.

Launch: python desktop/main.py
Package on Windows: pyinstaller --noconfirm --onefile --windowed --name HandLink-Studio desktop/main.py
"""
from __future__ import annotations

import json
import math
import os
import queue
import secrets
import socket
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from collections import deque

try:
    from desktop.protocol import BONES, HandPacket, PORT, ZONES, ZoneTracker, encode_osc, parse_packet
except ModuleNotFoundError:
    from protocol import BONES, HandPacket, PORT, ZONES, ZoneTracker, encode_osc, parse_packet

BG = '#080D13'
PANEL = '#101923'
CARD = '#17222E'
EDGE = '#293946'
WHITE = '#EEF7F4'
MUTED = '#95A8B5'
MINT = '#8CF7CB'
BLUE = '#75BFFF'
AMBER = '#FFC881'


def lan_ip():
    """Gets likely Wi-Fi IP without sending packets to the Internet."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(('192.0.2.1', 80))
        ip = sock.getsockname()[0]
        if ip and not ip.startswith('127.'):
            return ip
    except OSError:
        pass
    finally:
        sock.close()
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return 'Check ipconfig'


class HandLinkApp:
    def __init__(self, root):
        self.root = root
        self.root.title('HandLink Studio · Spatial Hands over Wi-Fi')
        self.root.geometry('1240x780')
        self.root.minsize(920, 650)
        self.root.configure(bg=BG)
        self.code = self.new_code()
        self.inbox: queue.Queue = queue.Queue(maxsize=120)
        self.stop_event = threading.Event()
        self.listener = None
        self.socket = None
        self.osc_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.osc_enabled = False
        self.osc_target = ('127.0.0.1', 9000)
        self.osc_full = False
        self.latest: dict[str, HandPacket] = {}
        self.last_seq: dict[str, int] = {}
        self.zone = ZoneTracker()
        self.logs = deque(maxlen=12)
        self.packet_times = deque(maxlen=120)
        self.active_phone = None
        self.last_seen = 0.
        self.last_motion = 0.
        self.hand_lost_sent = set()
        self.stale_sent = False
        self.last_ack = 0.
        self.record_file = None
        self.demo = False
        self.demo_seq = 0
        self.last_demo = 0.
        self.build()
        self.start_listener()
        self.root.after(16, self.tick)
        self.root.protocol('WM_DELETE_WINDOW', self.close)

    @staticmethod
    def new_code():
        return f'{secrets.randbelow(900000) + 100000}'

    def label(self, parent, text, size=11, color=WHITE, bold=False, **kwargs):
        return tk.Label(parent, text=text, bg=kwargs.get('bg', PANEL), fg=color,
                        font=('Segoe UI', size, 'bold' if bold else 'normal'),
                        anchor=kwargs.get('anchor', 'w'), justify=kwargs.get('justify', 'left'),
                        wraplength=kwargs.get('wraplength', 0))

    def button(self, parent, text, command, primary=False, width=None):
        return tk.Button(parent, text=text, command=command, bd=0, relief='flat',
                         bg=MINT if primary else CARD, fg='#0B1720' if primary else WHITE,
                         activebackground='#B6FFE1' if primary else EDGE,
                         activeforeground='#0B1720' if primary else WHITE,
                         cursor='hand2', padx=13, pady=9,
                         font=('Segoe UI', 10, 'bold'), width=width)

    def entry(self, parent, value, width=None):
        var = tk.StringVar(value=value)
        e = tk.Entry(parent, textvariable=var, bg=BG, fg=WHITE, bd=0,
                     insertbackground=MINT, highlightbackground=EDGE,
                     highlightcolor=MINT, highlightthickness=1,
                     font=('Consolas', 13), width=width or 16)
        return var, e

    def card(self, parent, title):
        f = tk.Frame(parent, bg=PANEL, highlightbackground=EDGE, highlightthickness=1)
        self.label(f, title.upper(), 9, MUTED, True).pack(fill='x', padx=17, pady=(15, 12))
        return f

    def build(self):
        top = tk.Frame(self.root, bg=BG)
        top.pack(fill='x', padx=24, pady=(20, 14))
        tk.Label(top, text='◉', bg=BG, fg=MINT, font=('Segoe UI', 27, 'bold')).pack(side='left', padx=(0, 12))
        names = tk.Frame(top, bg=BG)
        names.pack(side='left')
        self.label(names, 'HANDLINK  /  STUDIO', 21, WHITE, True, bg=BG).pack(anchor='w')
        self.label(names, 'SPATIAL HAND TRACKING  ·  LIVE LAN OSC BRIDGE', 9, MUTED, bg=BG).pack(anchor='w')
        self.status_label = self.label(top, '●  WAITING FOR PHONE', 11, AMBER, True, bg=BG)
        self.status_label.pack(side='right', pady=15)

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill='both', expand=True, padx=24, pady=(0, 20))
        left = tk.Frame(body, bg=PANEL, highlightbackground=EDGE, highlightthickness=1)
        left.pack(side='left', fill='both', expand=True)
        sidebar = tk.Frame(body, bg=BG, width=355)
        sidebar.pack(side='right', fill='y', padx=(16, 0))
        sidebar.pack_propagate(False)
        sidebar_canvas = tk.Canvas(sidebar, bg=BG, highlightthickness=0, bd=0)
        sidebar_scroll = tk.Scrollbar(sidebar, orient='vertical', command=sidebar_canvas.yview)
        sidebar_scroll.pack(side='right', fill='y')
        sidebar_canvas.pack(side='left', fill='both', expand=True)
        sidebar_canvas.configure(yscrollcommand=sidebar_scroll.set)
        right = tk.Frame(sidebar_canvas, bg=BG)
        sidebar_window = sidebar_canvas.create_window((0, 0), anchor='nw', window=right)
        right.bind('<Configure>', lambda event: sidebar_canvas.configure(scrollregion=sidebar_canvas.bbox('all')))
        sidebar_canvas.bind('<Configure>', lambda event: sidebar_canvas.itemconfigure(sidebar_window, width=event.width))
        def on_scroll(event):
            if event.delta:
                sidebar_canvas.yview_scroll(-int(event.delta/120), 'units')
        sidebar_canvas.bind('<Enter>', lambda event: sidebar_canvas.bind_all('<MouseWheel>', on_scroll))
        sidebar_canvas.bind('<Leave>', lambda event: sidebar_canvas.unbind_all('<MouseWheel>'))

        stagehead = tk.Frame(left, bg=PANEL)
        stagehead.pack(fill='x', padx=18, pady=(13, 10))
        self.label(stagehead, 'LIVE GESTURE STAGE', 11, WHITE, True).pack(side='left')
        self.fps_label = self.label(stagehead, '—  FPS', 10, MINT, True)
        self.fps_label.pack(side='right')
        self.canvas = tk.Canvas(left, bg='#050B11', highlightthickness=0, bd=0)
        self.canvas.pack(fill='both', expand=True, padx=12)
        bottom = tk.Frame(left, bg=PANEL)
        bottom.pack(fill='x', padx=18, pady=13)
        self.label(bottom, '21 landmarks / hand  ·  index fingertip drives spatial zones', 9, MUTED).pack(side='left')
        self.button(bottom, 'DEMO  ○', self.toggle_demo).pack(side='right')

        pairing = self.card(right, '01  ·  Pair phone')
        pairing.pack(fill='x', pady=(0, 12))
        self.label(pairing, 'Your PC local IP address', 10, MUTED).pack(anchor='w', padx=17)
        addrrow = tk.Frame(pairing, bg=PANEL)
        addrrow.pack(fill='x', padx=17, pady=(3, 10))
        self.ip_label = self.label(addrrow, lan_ip(), 21, WHITE, True)
        self.ip_label.pack(side='left', fill='x', expand=True)
        self.button(addrrow, 'COPY IP', lambda: self.copy(self.ip_label.cget('text'))).pack(side='right')
        self.label(pairing, '6-digit pair code (enter in Android app)', 10, MUTED).pack(anchor='w', padx=17)
        coderow = tk.Frame(pairing, bg=PANEL)
        coderow.pack(fill='x', padx=17, pady=(3, 9))
        self.code_label = self.label(coderow, self.code, 25, MINT, True)
        self.code_label.pack(side='left', fill='x', expand=True)
        self.button(coderow, 'NEW CODE', self.refresh_code).pack(side='right')
        self.label(pairing, f'UDP port {PORT}   ·   same Wi-Fi / hotspot required', 9, MUTED).pack(anchor='w', padx=17, pady=(0, 14))

        osc = self.card(right, '02  ·  OSC output')
        osc.pack(fill='x', pady=(0, 12))
        hostrow = tk.Frame(osc, bg=PANEL)
        hostrow.pack(fill='x', padx=17)
        hleft = tk.Frame(hostrow, bg=PANEL)
        hleft.pack(side='left', fill='x', expand=True)
        hright = tk.Frame(hostrow, bg=PANEL)
        hright.pack(side='right')
        self.label(hleft, 'Destination IP', 9, MUTED).pack(anchor='w', pady=(0, 4))
        self.host_var, host = self.entry(hleft, '127.0.0.1', 19)
        host.pack(fill='x', ipady=7)
        self.label(hright, 'Port', 9, MUTED).pack(anchor='w', pady=(0, 4))
        self.port_var, port = self.entry(hright, '9000', 7)
        port.pack(ipady=7)
        row = tk.Frame(osc, bg=PANEL)
        row.pack(fill='x', padx=17, pady=12)
        self.osc_button = self.button(row, 'ENABLE OSC', self.toggle_osc, primary=True)
        self.osc_button.pack(side='left', fill='x', expand=True)
        self.full_var = tk.BooleanVar(value=False)
        toggle = tk.Checkbutton(osc, text='Also send all 21 joints (high traffic)',
                                variable=self.full_var, bg=PANEL, fg=MUTED,
                                selectcolor=BG, activebackground=PANEL,
                                activeforeground=WHITE, font=('Segoe UI', 9))
        toggle.pack(anchor='w', padx=12, pady=(0, 12))

        info = self.card(right, '03  ·  Telemetry')
        info.pack(fill='x', pady=(0, 12))
        self.info_label = self.label(info, 'PHONE   Not connected\nHANDS   —\nPINCH   —\nPACKETS   0',
                                     11, WHITE, bg=PANEL)
        self.info_label.pack(fill='x', padx=17, pady=(0, 15))

        events = self.card(right, '04  ·  Events')
        events.pack(fill='both', expand=True)
        self.events_text = tk.Text(events, height=7, bg=PANEL, fg=MUTED,
                                   font=('Consolas', 9), relief='flat', bd=0,
                                   highlightthickness=0, state='disabled', wrap='word')
        self.events_text.pack(fill='both', expand=True, padx=17, pady=(0, 9))
        row = tk.Frame(events, bg=PANEL)
        row.pack(fill='x', padx=12, pady=(0, 12))
        self.record_button = self.button(row, '● RECORD JSONL', self.toggle_record)
        self.record_button.pack(side='left', fill='x', expand=True, padx=3)
        self.button(row, 'PANIC / STOP OSC', self.panic).pack(side='left', fill='x', expand=True, padx=3)
        self.log('Ready. Open the Android app, enter IP + code, tap CONNECT.')

    def copy(self, content):
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        self.log('Copied to clipboard.')

    def refresh_code(self):
        self.code = self.new_code()
        self.code_label.config(text=self.code)
        self.latest.clear()
        self.zone = ZoneTracker()
        self.last_seq.clear()
        self.active_phone = None
        self.last_seen = 0
        self.last_motion = 0
        self.hand_lost_sent.clear()
        self.log('New pairing code. Reconnect from the phone.')

    def log(self, msg):
        self.logs.append(f'{time.strftime("%H:%M:%S")}  {msg}')
        self.events_text.configure(state='normal')
        self.events_text.delete('1.0', 'end')
        self.events_text.insert('end', '\n'.join(self.logs))
        self.events_text.see('end')
        self.events_text.configure(state='disabled')

    def start_listener(self):
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.bind(('0.0.0.0', PORT))
            self.socket.settimeout(.2)
        except OSError as exc:
            self.log(f'UDP port {PORT} unavailable: {exc}')
            self.status_label.config(text='●  UDP PORT ERROR', fg='#FF8888')
            if self.socket:
                self.socket.close()
            self.socket = None
            return
        self.listener = threading.Thread(target=self.receive_loop, daemon=True)
        self.listener.start()

    def receive_loop(self):
        while not self.stop_event.is_set():
            try:
                data, addr = self.socket.recvfrom(8192)
            except socket.timeout:
                continue
            except OSError:
                break
            packet = parse_packet(data, self.code)
            is_hello = False
            if packet is None and len(data) < 160:
                try:
                    hello = json.loads(data)
                    is_hello = (type(hello) is dict and hello.get('v') == 1 and
                                hello.get('kind') == 'hello' and hello.get('code') == self.code)
                except (ValueError, UnicodeDecodeError):
                    pass
            if packet is None and not is_hello:
                continue
            received_at = packet.received_at if packet else time.monotonic()
            if self.active_phone is not None and addr[0] != self.active_phone and received_at - self.last_seen < 2:
                continue  # One sender per session; prevents unintentional clashes.
            if received_at - self.last_ack > 1.0:
                self.last_ack = received_at
                try:
                    self.socket.sendto(json.dumps({'v': 1, 'kind': 'ack', 'code': self.code}).encode(), addr)
                except OSError:
                    pass
            try:
                self.inbox.put_nowait((packet, addr[0]))
            except queue.Full:
                try:
                    self.inbox.get_nowait()
                    self.inbox.put_nowait((packet, addr[0]))
                except queue.Empty:
                    pass

    def toggle_osc(self):
        if self.osc_enabled:
            self.panic()
            return
        try:
            host = socket.gethostbyname(self.host_var.get().strip())
            port = int(self.port_var.get().strip())
            if not 1 <= port <= 65535:
                raise ValueError('Port outside range 1–65535')
            self.osc_target = (host, port)
        except (OSError, ValueError) as exc:
            messagebox.showerror('OSC target', f'Invalid OSC destination: {exc}')
            return
        self.osc_enabled = True
        self.osc_button.config(text='OSC LIVE  ●', bg=AMBER)
        self.log(f'OSC enabled → {host}:{port}')
        self.send_osc('/handlink/system/connected', 1)

    def send_osc(self, address, *values):
        if not self.osc_enabled:
            return
        try:
            self.osc_socket.sendto(encode_osc(address, *values), self.osc_target)
        except (OSError, ValueError) as exc:
            self.log(f'OSC send failed: {exc}')
            self.osc_enabled = False
            self.osc_button.config(text='ENABLE OSC', bg=MINT)

    def panic(self):
        if self.osc_enabled:
            self.send_osc('/handlink/system/soft-panic', 1)
            self.send_osc('/handlink/system/connected', 0)
        self.osc_enabled = False
        self.osc_button.config(text='ENABLE OSC', bg=MINT)
        self.log('OSC stopped (software only, not a physical emergency mute).')

    def toggle_record(self):
        if self.record_file:
            self.record_file.close()
            self.record_file = None
            self.record_button.config(text='● RECORD JSONL')
            self.log('Recording saved.')
            return
        path = filedialog.asksaveasfilename(title='Save tracking data',
            defaultextension='.jsonl', filetypes=[('JSON Lines', '*.jsonl')],
            initialfile='handlink-session.jsonl')
        if path:
            try:
                self.record_file = open(path, 'w', encoding='utf-8')
            except OSError as exc:
                messagebox.showerror('Recording', str(exc))
                return
            self.record_button.config(text='■ STOP RECORD')
            self.log('Recording landmarks locally; raw video never leaves phone.')

    def toggle_demo(self):
        self.demo = not self.demo
        self.log('Demo mode ON (synthetic points)' if self.demo else 'Demo mode OFF')
        if not self.demo:
            self.latest.clear()
            self.zone = ZoneTracker()

    def make_demo(self, t):
        # Synthetic hand in camera-coordinate frame, not a live camera reading.
        cx = .5 + .31 * math.sin(t*.75)
        cy = .48 + .19 * math.sin(t*.43)
        base = ((0, .19), (-.10, .12), (-.17, .02), (-.22, -.04), (-.26, -.09),
                (-.08, .04), (-.09, -.05), (-.10, -.15), (-.11, -.25),
                (0, .02), (0, -.08), (0, -.18), (0, -.28),
                (.08, .04), (.09, -.05), (.10, -.15), (.11, -.24),
                (.15, .08), (.19, 0), (.21, -.08), (.22, -.16))
        pts = tuple((min(1, max(0, cx+x*.75)), min(1, max(0, cy+y*.75)), 0.0) for x,y in base)
        self.demo_seq += 1
        return HandPacket('Right', self.demo_seq, pts, .5 + .5*math.sin(t*2), time.monotonic())

    def on_hello(self, ip, now=None):
        now = now or time.monotonic()
        if ip != self.active_phone:
            self.active_phone = ip
            self.log(f'Paired with {ip}' if ip != 'DEMO' else 'Synthetic tracking enabled.')
            self.send_osc('/handlink/system/connected', 1)
        self.last_seen = now

    def on_packet(self, packet: HandPacket, ip):
        now = packet.received_at
        prev = self.latest.get(packet.hand)
        # Ignore reordered datagrams, but accept a freshly restarted sender after downtime.
        if prev and now-prev.received_at < 2 and packet.seq <= self.last_seq.get(packet.hand, -1):
            return
        self.last_seq[packet.hand] = packet.seq
        self.latest[packet.hand] = packet
        self.on_hello(ip, now)
        self.last_motion = now
        self.hand_lost_sent.discard(packet.hand)
        self.stale_sent = False
        self.packet_times.append(now)
        x, y, z = packet.points[8]  # Index fingertip, normalized screen coords.
        side = packet.hand.lower()
        self.send_osc(f'/handlink/hand/{side}/index-tip', float(x), float(y), float(z))
        self.send_osc(f'/handlink/hand/{side}/pinch', float(packet.pinch))
        self.send_osc(f'/handlink/hand/{side}/tracked', 1)
        if self.full_var.get():
            for i, (px, py, pz) in enumerate(packet.points):
                self.send_osc(f'/handlink/hand/{side}/joint/{i}', float(px), float(py), float(pz))
        for h, zone, evt in self.zone.update(packet.hand, x, y, now):
            self.log(f'{h.upper()}  ·  ZONE {zone}  ·  {evt.upper()}')
            self.send_osc(f'/handlink/zone/{zone}/{evt}', h.lower())
        if self.record_file:
            try:
                self.record_file.write(json.dumps({'time': time.time(), 'hand': packet.hand,
                    'points': packet.points, 'pinch': packet.pinch, 'zones': {
                    z: self.zone.is_active(packet.hand,z) for z in ZONES}}, separators=(',', ':')) + '\n')
                self.record_file.flush()
            except OSError as exc:
                self.log(f'Recording error: {exc}')
                self.toggle_record()

    def tick(self):
        if self.stop_event.is_set():
            return
        try:
            # Consume at most one frame per hand from the latest backlog, not every old frame.
            collected = {}
            for _ in range(120):
                try:
                    p, ip = self.inbox.get_nowait()
                    if p is None:
                        self.on_hello(ip)
                    else:
                        collected[p.hand] = (p, ip)
                except queue.Empty:
                    break
            for p, ip in collected.values():
                self.on_packet(p, ip)
        except Exception as exc:
            self.log(f'Frame error: {exc}')
        now = time.monotonic()
        if self.demo and now - self.last_demo > .033:
            self.last_demo = now
            self.on_packet(self.make_demo(now), 'DEMO')
        for hand, packet in self.latest.items():
            if now-packet.received_at > .55 and hand not in self.hand_lost_sent:
                self.hand_lost_sent.add(hand)
                self.send_osc(f'/handlink/hand/{hand.lower()}/tracked', 0)
                for h, zone, event in self.zone.tracking_lost(hand):
                    self.send_osc(f'/handlink/zone/{zone}/{event}', h.lower())
                self.log(f'{hand}: tracking lost (no fabricated EXIT).')
        if self.last_motion and now-self.last_motion > .55 and not self.stale_sent:
            self.stale_sent = True
            self.send_osc('/handlink/system/stale', 1)
        if self.last_seen and now-self.last_seen > 2 and not self.demo:
            self.active_phone = None
            self.latest.clear()
            self.last_seq.clear()
        self.update_ui(now)
        self.draw(now)
        self.root.after(16, self.tick)

    def update_ui(self, now):
        connected = bool(self.active_phone and now-self.last_seen < .55)
        self.status_label.config(text=('●  LIVE  /  ' + ('SIMULATION' if self.demo else 'CONNECTED'))
                                  if connected else '●  WAITING FOR PHONE',
                                  fg=MINT if connected else AMBER)
        live = [p for p in self.latest.values() if now-p.received_at < .55]
        samples = [t for t in self.packet_times if now-t <= 1]
        self.fps_label.config(text=f'{len(samples)} PKT/S')
        pinch = ', '.join(f'{p.hand[0]} {p.pinch:.2f}' for p in live) or '—'
        hands = ' + '.join(p.hand for p in live) or '—'
        self.info_label.config(text=f'PHONE      {self.active_phone or "Not connected"}\n'
                                f'HANDS      {hands}\n'
                                f'PINCH      {pinch}\n'
                                f'UDP PKT/S  {len(samples)}\n'
                                f'OSC        {"ACTIVE" if self.osc_enabled else "OFF"}')

    def draw(self, now):
        c = self.canvas
        w, h = c.winfo_width(), c.winfo_height()
        if w < 4 or h < 4:
            return
        c.delete('all')
        # Restrained sci-fi grid.
        for gx in range(0, 11):
            xx = gx*w/10
            c.create_line(xx, 0, xx, h, fill='#12222C', width=1)
        for gy in range(0, 9):
            yy = gy*h/8
            c.create_line(0, yy, w, yy, fill='#12222C', width=1)
        c.create_text(20, 22, anchor='w', text='CAMERA SPACE · NORMALIZED XY',
                      fill=MUTED, font=('Consolas', 9))
        c.create_text(w-20, 22, anchor='e', text='LIVE LANDMARK DATA / NO VIDEO STREAM',
                      fill=MUTED, font=('Consolas', 9))
        for name, (x, y, r) in ZONES.items():
            active = any(self.zone.is_active(side, name) and side in self.latest and
                         now-self.latest[side].received_at < .55 for side in ('Left','Right'))
            # Radius is normalized to min(w,h) to preserve circles visually.
            cx, cy, rad = x*w, y*h, r*min(w, h)
            stroke = MINT if active else '#3B5D66'
            c.create_oval(cx-rad, cy-rad, cx+rad, cy+rad, outline=stroke, width=3 if active else 2,
                          fill='#12291F' if active else '#0C1920')
            c.create_oval(cx-4, cy-4, cx+4, cy+4, fill=stroke, outline='')
            c.create_text(cx, cy-23, text=name, fill=WHITE if active else MUTED,
                          font=('Consolas', 21, 'bold'))
            c.create_text(cx, cy+19, text=('TRIGGERED' if active else 'SPATIAL ZONE'),
                          fill=MINT if active else '#5E7881', font=('Consolas', 9))
        activehands = 0
        for side, color in [('Left', BLUE), ('Right', MINT)]:
            p = self.latest.get(side)
            if not p or now-p.received_at > .55:
                continue
            activehands += 1
            point = lambda i: (p.points[i][0]*w, p.points[i][1]*h)
            for a,b in BONES:
                ax, ay = point(a)
                bx, by = point(b)
                c.create_line(ax, ay, bx, by, fill='#164451' if side == 'Left' else '#215241', width=8,
                              capstyle='round')
                c.create_line(ax, ay, bx, by, fill=color, width=2, capstyle='round')
            for i in range(21):
                x, y = point(i)
                rr = 5.5 if i in (4, 8, 12, 16, 20) else 3
                c.create_oval(x-rr, y-rr, x+rr, y+rr, fill=color, outline='#071519')
            tx, ty = point(8)
            c.create_oval(tx-14,ty-14,tx+14,ty+14,outline=color,width=2)
            wx, wy = point(0)
            c.create_text(wx+16, wy+14, anchor='w', text=f'{side.upper()} · PINCH {p.pinch:.2f}',
                          fill=color, font=('Consolas', 10, 'bold'))
        if not activehands:
            c.create_text(w/2,h*.87, text='NO TRACKED HANDS  ·  CONNECT PHONE OR ENABLE DEMO',
                          fill='#6B8290', font=('Consolas', 11))
        c.create_text(20, h-20, anchor='w', text='A  ·  LEFT     B  ·  RIGHT     C  ·  CENTER',
                      fill='#688591', font=('Consolas', 9))

    def close(self):
        self.stop_event.set()
        if self.record_file:
            self.record_file.close()
        if self.osc_enabled:
            self.panic()
        if self.socket:
            self.socket.close()
        self.osc_socket.close()
        self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    HandLinkApp(root)
    root.mainloop()
