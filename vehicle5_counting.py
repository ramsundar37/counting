
import math
import random
import sys

import pygame

# ── dimensions ────────────────────────────────────────────────────────────────
LEFT_W   = 300          # left control panel width
RIGHT_W  = 300          # right stats panel width
SIM_W    = 700          # simulation canvas width
SIM_H    = 530          # simulation canvas height
STATUS_H = 50           # bottom status bar inside sim area
TITLE_H  = 50
BOTTOM_H = 36
WINDOW_W = LEFT_W + SIM_W + RIGHT_W
WINDOW_H = TITLE_H + SIM_H + STATUS_H + BOTTOM_H
CANVAS_Y = TITLE_H
FPS      = 60

# ── simulation globals ─────────────────────────────────────────────────────────
LIGHT_THRESHOLD = 0.35
HEAT_THRESHOLD  = 0.35
MOTOR_SPEED     = 90.0
ROTATION_SCALING = 6.0
WIRING          = "crossed"
WALL_MODE       = "bounce"
WALL_MODES      = ["bounce", "vanish", "wrap"]
LIGHT_COUNT_THRESHOLDS = [1, 2, 2]
HEAT_COUNT_THRESHOLDS  = [1, 2]
PAUSE_DURATION_MS      = 1500

# ── palette ────────────────────────────────────────────────────────────────────
BG        = (10, 14, 20)          # Simulation canvas background
PANEL_BG  = (14, 19, 27)          # Side panels background
CARD_BG   = (20, 28, 40)          # Inner card background
BORDER    = (35, 48, 65)          # Borders and lines
AMBER     = (250, 166, 26)        # Main accent (Yellow/Orange)
AMBER_DIM = (150, 100, 20)
CYAN      = (72, 219, 200)        # Ring / Speed boost
RED       = (242, 92, 84)         # Heat accent
RED_DIM   = (140, 50, 45)
GREY      = (85, 100, 115)        # Generic grey
GREY2     = (35, 45, 60)          # Darker grey for inactive buttons/tracks
PAPER     = (190, 200, 215)       # Primary text
PAPER_DIM = (115, 130, 150)       # Secondary / Dim text
WHITE     = (245, 250, 255)       # Highlight text
BLUE_2    = (35, 48, 65)          # Vehicle body
GRID_COL  = (22, 32, 45)          # Grid lines
LED_ON_L  = AMBER
LED_ON_H  = RED
LED_OFF   = (40, 50, 68)

# ── helpers ────────────────────────────────────────────────────────────────────
def lerp_color(a, b, t):
    return tuple(int(a[i] + (b[i]-a[i])*t) for i in range(3))


def draw_rounded_rect(surf, color, rect, radius, border=0, border_color=None):
    pygame.draw.rect(surf, color, rect, border_radius=radius)
    if border and border_color:
        pygame.draw.rect(surf, border_color, rect, border, border_radius=radius)


def draw_led(surf, x, y, r, color_on, on):
    c = color_on if on else LED_OFF
    pygame.draw.circle(surf, c, (x, y), r)
    # Removing the outer glow so just the dot is visible as requested
    pygame.draw.circle(surf, BORDER, (x, y), r, 1)


# ── simulation classes ─────────────────────────────────────────────────────────
class CountingDevice:
    def __init__(self, threshold):
        self.threshold = threshold
        self.active = False

    def would_fire(self, *inputs):
        return sum(inputs) >= self.threshold


class Source:
    def __init__(self, x, y, kind="light"):
        self.x, self.y, self.kind = x, y, kind
        self.active = True


def sense(px, py, sources, kind):
    total = 0.0
    for s in sources:
        if not s.active or s.kind != kind:
            continue
        d2 = (s.x - px)**2 + (s.y - py)**2
        total += 4000.0 / (d2 + 400.0)
    return min(1.0, total)


def sense_bit(value, threshold):
    return value > threshold


class Vehicle:
    def __init__(self, x, y):
        self.x, self.y = x, y
        self.heading = -math.pi / 2
        self.radius = 15
        self.sensor_angle = 0.55
        self.sensor_dist = 10
        self.active = True
        self.reading = {}
        self.light_counter = [CountingDevice(t) for t in LIGHT_COUNT_THRESHOLDS]
        self.heat_counter  = [CountingDevice(t) for t in HEAT_COUNT_THRESHOLDS]
        self.was_above_light = False
        self.was_above_heat  = False
        self.pause_until_ms  = None
        self.speed_boost_until_ms = None

    def reset_light_counters(self):
        for d in self.light_counter: d.active = False

    def reset_heat_counters(self):
        for d in self.heat_counter: d.active = False

    def sensor_pos(self, side):
        ang = self.heading + side * self.sensor_angle
        return (self.x + math.cos(ang)*self.sensor_dist,
                self.y + math.sin(ang)*self.sensor_dist)

    def step(self, dt, sources, current_time_ms):
        if not self.active:
            return

        lx, ly = self.sensor_pos(-1)
        rx, ry = self.sensor_pos(1)
        light_l = sense(lx, ly, sources, "light")
        light_r = sense(rx, ry, sources, "light")
        heat_l  = sense(lx, ly, sources, "heat")
        heat_r  = sense(rx, ry, sources, "heat")
        sensor_l = min(1.0, light_l + heat_l)
        sensor_r = min(1.0, light_r + heat_r)
        total_sensor_output = max(light_l, light_r, heat_l, heat_r)
        above_light = sense_bit(max(light_l, light_r), LIGHT_THRESHOLD)
        above_heat  = sense_bit(max(heat_l,  heat_r),  HEAT_THRESHOLD)

        if self.pause_until_ms is not None:
            if current_time_ms < self.pause_until_ms:
                speed, rotation = 0.0, 0.0
            else:
                self.pause_until_ms = None
                speed, rotation = None, None
        else:
            speed, rotation = None, None

        if speed is None:
            pulse_light = above_light and not self.was_above_light
            self.was_above_light = above_light
            pulse_heat  = above_heat  and not self.was_above_heat
            self.was_above_heat = above_heat

            if pulse_light:
                prev = [d.active for d in self.light_counter]
                for i, device in enumerate(self.light_counter):
                    inputs = [1] if i == 0 else [1, 1 if prev[i-1] else 0]
                    device.active = prev[i] or device.would_fire(*inputs)
                if self.light_counter[-1].active and not prev[-1]:
                    self.pause_until_ms = current_time_ms + PAUSE_DURATION_MS
                    self.reset_light_counters()

            if pulse_heat:
                prev = [d.active for d in self.heat_counter]
                for i, device in enumerate(self.heat_counter):
                    inputs = [1] if i == 0 else [1, 1 if prev[i-1] else 0]
                    device.active = prev[i] or device.would_fire(*inputs)
                if self.heat_counter[-1].active and not prev[-1]:
                    self.speed_boost_until_ms = current_time_ms + PAUSE_DURATION_MS
                    self.reset_heat_counters()

            if self.pause_until_ms is not None:
                speed, rotation = 0.0, 0.0
            else:
                tso = (sensor_l + sensor_r) / 2.0
                speed = max(0.0, 1.0 - tso)
                wiring_sign = 1.0 if WIRING == "uncrossed" else -1.0
                rotation = (sensor_r - sensor_l) * ROTATION_SCALING * wiring_sign
                if self.speed_boost_until_ms is not None:
                    if current_time_ms < self.speed_boost_until_ms:
                        speed *= 2.5
                    else:
                        self.speed_boost_until_ms = None

        self.heading += rotation * dt
        v = speed * MOTOR_SPEED
        self.x += math.cos(self.heading) * v * dt
        self.y += math.sin(self.heading) * v * dt

        pad = 20
        if WALL_MODE == "bounce":
            if self.x < pad:  self.x = pad;         self.heading = math.pi - self.heading
            if self.x > SIM_W - pad: self.x = SIM_W - pad; self.heading = math.pi - self.heading
            if self.y < pad:  self.y = pad;         self.heading = -self.heading
            if self.y > SIM_H - pad: self.y = SIM_H - pad; self.heading = -self.heading
        elif WALL_MODE == "wrap":
            if self.x < 0:      self.x += SIM_W
            elif self.x > SIM_W: self.x -= SIM_W
            if self.y < 0:      self.y += SIM_H
            elif self.y > SIM_H: self.y -= SIM_H

        self.reading = dict(
            light_l=light_l, light_r=light_r, heat_l=heat_l, heat_r=heat_r,
            motor_l=sense_bit(light_l, LIGHT_THRESHOLD) or sense_bit(heat_l, HEAT_THRESHOLD),
            motor_r=sense_bit(light_r, LIGHT_THRESHOLD) or sense_bit(heat_r, HEAT_THRESHOLD),
            light_counter_states=[d.active for d in self.light_counter],
            heat_counter_states=[d.active for d in self.heat_counter],
            light_sources_seen=sum(1 for d in self.light_counter if d.active),
            heat_sources_seen=sum(1 for d in self.heat_counter  if d.active),
            paused=self.pause_until_ms is not None,
            speed_boost=self.speed_boost_until_ms is not None,
            total_sensor_output=total_sensor_output,
            speed=speed,
            rotation=rotation,
        )


# ── drawing helpers ────────────────────────────────────────────────────────────
def draw_grid(surf, ox, oy, w, h):
    surf.fill(BG)
    # sim area
    pygame.draw.rect(surf, (10, 16, 26), (ox, oy, w, h))
    for x in range(ox, ox + w, 28):
        pygame.draw.line(surf, GRID_COL, (x, oy), (x, oy + h))
    for y in range(oy, oy + h, 28):
        pygame.draw.line(surf, GRID_COL, (ox, y), (ox + w, y))


def draw_source(surf, source, selected, ox, oy):
    x, y = int(source.x) + ox, int(source.y) + oy
    if not source.active:
        color = GREY
    elif source.kind == "light":
        color = AMBER
    else:
        color = RED

    if source.kind == "light":
        pygame.draw.circle(surf, color, (x, y), 4)
        for ang in (0, math.pi/2, math.pi, 3*math.pi/2):
            x1 = x + math.cos(ang)*6; y1 = y + math.sin(ang)*6
            x2 = x + math.cos(ang)*9; y2 = y + math.sin(ang)*9
            pygame.draw.line(surf, color, (int(x1), int(y1)), (int(x2), int(y2)), 2)
    else:
        pygame.draw.circle(surf, color, (x, y), 4)
        pygame.draw.circle(surf, color, (x, y), 7, 1)
        pygame.draw.circle(surf, color, (x, y), 10, 1)

    pygame.draw.circle(surf, BG, (x, y), 4, 1)
    if selected:
        pygame.draw.circle(surf, AMBER, (x, y), 14, 1)


def draw_vehicle(surf, v, selected, ox, oy):
    cx, cy = int(v.x) + ox, int(v.y) + oy
    body_color = BLUE_2 if v.active else GREY
    ring_color = CYAN  if v.active else GREY
    pygame.draw.circle(surf, body_color, (cx, cy), v.radius)
    pygame.draw.circle(surf, ring_color, (cx, cy), v.radius, 2)
    if selected:
        pygame.draw.circle(surf, AMBER, (cx, cy), v.radius + 5, 1)
    hx = cx + math.cos(v.heading)*(v.radius + 8)
    hy = cy + math.sin(v.heading)*(v.radius + 8)
    pygame.draw.line(surf, AMBER if v.active else GREY, (cx, cy), (int(hx), int(hy)), 3)
    for side, on in ((-1, v.reading.get("motor_l")), (1, v.reading.get("motor_r"))):
        sx, sy = v.sensor_pos(side)
        color = AMBER if (v.active and on) else GREY
        pygame.draw.circle(surf, color, (int(sx)+ox, int(sy)+oy), 5)


def draw_slider(surf, font_b, font_s, x, y, w, label, sub, value, color):
    """Draw a labelled horizontal slider bar."""
    # label row – bold for label, small for subtitle
    lbl = font_b.render(label, True, WHITE)
    surf.blit(lbl, (x, y))
    sub_lbl = font_s.render(sub, True, GREY)
    surf.blit(sub_lbl, (x + lbl.get_width() + 4, y + 3))
    val_txt = font_b.render(f"{value:.2f}", True, color)
    surf.blit(val_txt, (x + w - val_txt.get_width(), y))

    # track
    track_y = y + 24
    pygame.draw.rect(surf, GREY2, (x, track_y, w, 6), border_radius=3)
    fill_w = int(w * value)
    pygame.draw.rect(surf, color, (x, track_y, fill_w, 6), border_radius=3)


def draw_toggle_row(surf, font_b, font_s, x, y, w, label, value, key_hint):
    """Draw a label + bold value + key badge row."""
    lbl = font_s.render(label, True, PAPER_DIM)
    surf.blit(lbl, (x, y + 2))
    val_txt = font_b.render(value, True, WHITE)
    # position value after label with generous gap
    vx = x + 80
    surf.blit(val_txt, (vx, y))
    # key badge
    kw, kh = 26, 22
    kx = x + w - kw - 2
    draw_rounded_rect(surf, GREY2, (kx, y - 1, kw, kh), 5, 1, BORDER)
    kt = font_s.render(key_hint, True, PAPER)  
    surf.blit(kt, (kx + (kw - kt.get_width()) // 2, y + (kh - kt.get_height()) // 2 - 1))


# ── left panel ─────────────────────────────────────────────────────────────────
def draw_left_panel(surf, fonts, vehicles, selected_i, sources):
    fn, fs = fonts
    x0, pad = 0, 16
    w = LEFT_W
    ipad = 12  # inner card padding

    # background
    pygame.draw.rect(surf, PANEL_BG, (0, 0, w, WINDOW_H))
    pygame.draw.line(surf, BORDER, (w - 1, 0), (w - 1, WINDOW_H), 1)

    y = TITLE_H + 12

    # section header
    hdr = fs.render("Vehicle control", True, PAPER)
    surf.blit(hdr, (x0 + pad, y))
    y += 26

    # light slider
    draw_slider(surf, fn, fs, x0 + pad, y, w - pad * 2,
                "Light th", "(up/down)", LIGHT_THRESHOLD, AMBER)
    y += 40

    # heat slider
    draw_slider(surf, fn, fs, x0 + pad, y, w - pad * 2,
                "Heat th", "(left/right)", HEAT_THRESHOLD, RED)
    y += 44

    # wiring / walls card
    cw = w - pad * 2
    draw_rounded_rect(surf, CARD_BG, (x0 + pad, y, cw, 72), 8, 1, BORDER)
    draw_toggle_row(surf, fn, fs, x0 + pad + ipad, y + 14, cw - ipad * 2, "Wiring", WIRING, "W")
    pygame.draw.line(surf, BORDER, (x0 + pad + ipad, y + 36), (x0 + w - pad - ipad, y + 36), 1)
    draw_toggle_row(surf, fn, fs, x0 + pad + ipad, y + 46, cw - ipad * 2, "Walls", WALL_MODE, "F")
    y += 86

    # speed cap card
    draw_rounded_rect(surf, CARD_BG, (x0 + pad, y, cw, 58), 8, 1, BORDER)
    sc_lbl = fs.render("Speed cap", True, PAPER_DIM)
    surf.blit(sc_lbl, (x0 + pad + ipad, y + 10))
    sc_val = fn.render(f"{MOTOR_SPEED:.0f}", True, WHITE)
    surf.blit(sc_val, (x0 + pad + ipad, y + 30))
    sc_sub = fs.render("(1/2)", True, GREY)
    surf.blit(sc_sub, (x0 + pad + ipad + sc_val.get_width() + 6, y + 34))
    y += 72

    # vehicles / sources combined card
    draw_rounded_rect(surf, CARD_BG, (x0 + pad, y, cw, 120), 8, 1, BORDER)
    # vehicles row
    v_lbl = fn.render("Vehicles", True, WHITE)
    surf.blit(v_lbl, (x0 + pad + ipad, y + 10))
    v_cnt = fn.render(str(len(vehicles)), True, WHITE)
    surf.blit(v_cnt, (x0 + w - pad - ipad - v_cnt.get_width(), y + 10))
    hints = fs.render("N add · Tab sel · A act · Del rem", True, PAPER_DIM)
    surf.blit(hints, (x0 + pad + ipad, y + 32))
    # divider
    pygame.draw.line(surf, BORDER, (x0 + pad + ipad, y + 54), (x0 + w - pad - ipad, y + 54), 1)
    # sources row
    s_lbl = fn.render("Sources", True, WHITE)
    surf.blit(s_lbl, (x0 + pad + ipad, y + 64))
    s_cnt = fn.render(str(len(sources)), True, WHITE)
    surf.blit(s_cnt, (x0 + w - pad - ipad - s_cnt.get_width(), y + 64))
    shints = fs.render("click add · S sel · X act · Bksp rem", True, PAPER_DIM)
    surf.blit(shints, (x0 + pad + ipad, y + 86))


# ── right panel ────────────────────────────────────────────────────────────────
def draw_right_panel(surf, fonts, right_fonts, vehicles, selected_i, sources, selected_source_i):
    fn, fs = fonts
    f_title, f_label, f_value, f_small_bold, f_sel = right_fonts
    x0 = LEFT_W + SIM_W
    pad = 16
    w = RIGHT_W
    ipad = 12
    cw = w - pad * 2

    pygame.draw.rect(surf, PANEL_BG, (x0, 0, w, WINDOW_H))
    pygame.draw.line(surf, BORDER, (x0, 0), (x0, WINDOW_H), 1)

    sel = vehicles[selected_i] if vehicles else None
    r = sel.reading if (sel and sel.reading) else {}

    lx = x0 + pad + ipad
    rx = x0 + w - pad - ipad

    # ── equal-spacing layout ────────────────────────────────────────────────
    # Available vertical area between title bar and bottom card
    HDR_H   = 34          # "Vehicle stats" header
    CARD1_H = 112         # Total output / Speed / Rotation
    CARD2_H = 168         # Light thresh + Heat thresh
    CARD3_H = 72          # Light seen / Heat seen
    CARD4_H = 82          # Vehicle / Source
    total_cards = CARD1_H + CARD2_H + CARD3_H + CARD4_H
    avail = WINDOW_H - TITLE_H - BOTTOM_H - HDR_H
    gap = max(8, (avail - total_cards) // 5)  # 5 gaps: top + 3 between + bottom

    # ── "Vehicle stats" header ──────────────────────────────────────────────
    hdr_y = TITLE_H + gap
    hdr = f_title.render("Vehicle stats", True, WHITE)
    surf.blit(hdr, (x0 + pad, hdr_y))

    y = hdr_y + HDR_H + gap

    # ── helpers ─────────────────────────────────────────────────────────────
    def stat_row(label, val_str, yy):
        lt = f_label.render(label, True, WHITE)
        surf.blit(lt, (lx, yy))
        vt = f_value.render(val_str, True, WHITE)
        surf.blit(vt, (rx - vt.get_width(), yy))

    # ── Card 1: Total output / Speed / Rotation ─────────────────────────────
    draw_rounded_rect(surf, CARD_BG, (x0 + pad, y, cw, CARD1_H), 8, 1, BORDER)
    row_gap = (CARD1_H - 3 * 22) // 4   # evenly space 3 rows
    stat_row("Total output", f"{r.get('total_sensor_output', 0):.2f}", y + row_gap)
    stat_row("Speed",        f"{r.get('speed', 0):.2f}",              y + row_gap * 2 + 22)
    stat_row("Rotation",     f"{r.get('rotation', 0):.2f}",           y + row_gap * 3 + 44)
    y += CARD1_H + gap

    # ── Card 2: Light thresh + Heat thresh ──────────────────────────────────
    draw_rounded_rect(surf, CARD_BG, (x0 + pad, y, cw, CARD2_H), 8, 1, BORDER)
    led_spacing = 60

    # light section
    lbl_lt = f_label.render("Light thresh", True, WHITE)
    surf.blit(lbl_lt, (lx, y + 10))
    l_states = r.get("light_counter_states", [False] * 3)
    led_x = lx
    for state in l_states:
        cx_led = led_x + 14
        draw_led(surf, cx_led, y + 48, 9, LED_ON_L, state)
        lbl = f_small_bold.render("ON" if state else "OFF", True, AMBER if state else GREY)
        surf.blit(lbl, (cx_led - lbl.get_width() // 2, y + 63))
        led_x += led_spacing

    # heat section
    div_y = y + 92
    lbl_ht = f_label.render("Heat thresh", True, WHITE)
    surf.blit(lbl_ht, (lx, div_y))
    h_states = r.get("heat_counter_states", [False] * 2)
    led_x = lx
    for state in h_states:
        cx_led = led_x + 14
        draw_led(surf, cx_led, div_y + 38, 9, LED_ON_H, state)
        lbl = f_small_bold.render("ON" if state else "OFF", True, RED if state else GREY)
        surf.blit(lbl, (cx_led - lbl.get_width() // 2, div_y + 53))
        led_x += led_spacing
    y += CARD2_H + gap

    # ── Card 3: Light seen / Heat seen ──────────────────────────────────────
    draw_rounded_rect(surf, CARD_BG, (x0 + pad, y, cw, CARD3_H), 8, 1, BORDER)
    inner_gap = (CARD3_H - 2 * 22) // 3
    stat_row("Light seen", str(r.get("light_sources_seen", 0)), y + inner_gap)
    stat_row("Heat seen",  str(r.get("heat_sources_seen",  0)), y + inner_gap * 2 + 22)
    y += CARD3_H + gap

    # ── Card 4: Vehicle / Source – pinned above help bar ────────────────────
    card_y = WINDOW_H - BOTTOM_H - pad - CARD4_H
    draw_rounded_rect(surf, CARD_BG, (x0 + pad, card_y, cw, CARD4_H), 8, 1, BORDER)
    if sel:
        state = "active" if sel.active else "INACTIVE"
        sv_txt = f_sel.render(f"Vehicle #{selected_i}", True, WHITE)
        surf.blit(sv_txt, (lx, card_y + 10))
        badge_txt_v = f_small_bold.render(state, True, WHITE if sel.active else GREY)
        bw_v = badge_txt_v.get_width() + 16
        bh_v = badge_txt_v.get_height() + 6
        bbx_v = rx - bw_v
        bby_v = card_y + 8
        draw_rounded_rect(surf, GREY2, (bbx_v, bby_v, bw_v, bh_v), 5, 1, BORDER)
        surf.blit(badge_txt_v, (bbx_v + 8, bby_v + 3))

    if sources:
        sel_s = sources[selected_source_i]
        ss_state = "active" if sel_s.active else "INACTIVE"
        ss_txt = f_sel.render(f"Source #{selected_source_i} ({sel_s.kind})", True, WHITE)
        surf.blit(ss_txt, (lx, card_y + 46))
        badge_txt = f_small_bold.render(ss_state, True, WHITE if sel_s.active else GREY)
        bw = badge_txt.get_width() + 16
        bh = badge_txt.get_height() + 6
        bbx = rx - bw
        bby = card_y + 44
        draw_rounded_rect(surf, GREY2, (bbx, bby, bw, bh), 5, 1, BORDER)
        surf.blit(badge_txt, (bbx + 8, bby + 3))


# ── title bar ──────────────────────────────────────────────────────────────────
def draw_title(surf, font, font_title):
    pygame.draw.rect(surf, PANEL_BG, (0, 0, WINDOW_W, TITLE_H))
    pygame.draw.line(surf, BORDER, (0, TITLE_H - 1), (WINDOW_W, TITLE_H - 1), 1)
    # title text in left panel zone (italic amber)
    t = font_title.render("Vehicle 5 — counting", True, AMBER)
    surf.blit(t, (18, TITLE_H // 2 - t.get_height() // 2))
    # centre label above sim area
    cl = font.render("Vehicle", True, PAPER)
    cx = LEFT_W + SIM_W // 2 - cl.get_width() // 2
    surf.blit(cl, (cx, TITLE_H // 2 - cl.get_height() // 2))
    # right panel header
    rh = font.render("Vehicle stats", True, PAPER)
    surf.blit(rh, (LEFT_W + SIM_W + 16, TITLE_H // 2 - rh.get_height() // 2))


# ── status bar (inside centre bottom) ─────────────────────────────────────────
def draw_status_bar(surf, fonts, vehicles, selected_i, paused):
    fn, fs = fonts
    sx = LEFT_W
    sy = TITLE_H + SIM_H
    sw = SIM_W
    sh = STATUS_H
    bar_h = sh - 12
    bar_y = sy + 6
    mid_y = bar_y + bar_h // 2

    draw_rounded_rect(surf, CARD_BG, (sx + 10, bar_y, sw - 20, bar_h), 8, 1, AMBER)

    sel = vehicles[selected_i] if vehicles else None
    r = sel.reading if (sel and sel.reading) else {}

    is_paused = paused or (sel and r.get("paused"))
    is_speed  = sel and r.get("speed_boost")

    if is_paused:
        action_txt = "pause"
        action_col = RED
    elif is_speed:
        action_txt = "speed +"
        action_col = CYAN
    else:
        action_txt = "moving"
        action_col = AMBER

    # play icon triangle
    tri_h = 14
    ico_x = sx + 28
    ico_y = mid_y - tri_h // 2
    tri = [(ico_x, ico_y), (ico_x, ico_y + tri_h), (ico_x + 10, ico_y + tri_h // 2)]
    pygame.draw.polygon(surf, action_col, tri)

    at = fn.render(action_txt, True, action_col)
    surf.blit(at, (sx + 48, mid_y - at.get_height() // 2))

    # pause button
    btn_h = 28
    btn_y = mid_y - btn_h // 2
    pbx = sx + sw - 170
    bg_p = PANEL_BG if is_paused else GREY2
    draw_rounded_rect(surf, bg_p, (pbx, btn_y, 72, btn_h), 6, 1, BORDER)
    pt = fs.render("pause", True, WHITE if is_paused else PAPER)
    surf.blit(pt, (pbx + 36 - pt.get_width() // 2, mid_y - pt.get_height() // 2))

    # speed+ button
    sbx = pbx + 82
    bg_s = PANEL_BG if is_speed else GREY2
    draw_rounded_rect(surf, bg_s, (sbx, btn_y, 72, btn_h), 6, 1, BORDER)
    st2 = fs.render("speed+", True, WHITE if is_speed else PAPER)
    surf.blit(st2, (sbx + 36 - st2.get_width() // 2, mid_y - st2.get_height() // 2))


# ── bottom help bar ────────────────────────────────────────────────────────────
def draw_help_bar(surf, fs, fn):
    y = TITLE_H + SIM_H + STATUS_H
    pygame.draw.rect(surf, PANEL_BG, (0, y, WINDOW_W, BOTTOM_H))
    pygame.draw.line(surf, BORDER, (0, y), (WINDOW_W, y), 1)

    # Items: (key_label, description, use_badge)
    # use_badge=True → rounded rect pill around the key
    items = [
        ("L-click", "light",         False),
        ("R-click", "heat",          False),
        ("C",        "clear sources", False),
        ("R",        "reset",         False),
        ("Space",    "pause",         True),
    ]

    gap   = 22   # gap between each key-desc pair
    bx    = 20
    ty    = y + BOTTOM_H // 2  # vertical centre

    for key, desc, use_badge in items:
        # --- key label ---
        kt = fn.render(key, True, WHITE)
        kw = kt.get_width()
        kh = kt.get_height()

        if use_badge:
            # pill badge (like Space key)
            pad_x, pad_y = 10, 4
            badge_w = kw + pad_x * 2
            badge_h = kh + pad_y * 2
            bx_badge = bx
            by_badge = ty - badge_h // 2
            draw_rounded_rect(surf, CARD_BG, (bx_badge, by_badge, badge_w, badge_h), 6, 1, BORDER)
            surf.blit(kt, (bx_badge + pad_x, by_badge + pad_y))
            bx += badge_w
        else:
            surf.blit(kt, (bx, ty - kh // 2))
            bx += kw

        bx += 6  # small gap between key and description

        # --- description ---
        dt = fs.render(desc, True, PAPER_DIM)
        surf.blit(dt, (bx, ty - dt.get_height() // 2))
        bx += dt.get_width() + gap


# ── main ───────────────────────────────────────────────────────────────────────
def main():
    global LIGHT_THRESHOLD, HEAT_THRESHOLD, MOTOR_SPEED, WALL_MODE, WIRING

    pygame.init()
    screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
    pygame.display.set_caption("Vehicle 5 – Counting")
    clock = pygame.time.Clock()

    fn = pygame.font.SysFont("segoeui, arial", 15, bold=True)
    fs = pygame.font.SysFont("segoeui, arial", 13)
    ft = pygame.font.SysFont("segoeui, arial", 20, bold=True)  # title font
    fonts = (fn, fs)

    # ── right-panel Inter font hierarchy ────────────────────────────────────
    _fp = "inter, segoeui, arial"
    f_title      = pygame.font.SysFont(_fp, 22, bold=True)   # Vehicle stats heading
    f_label      = pygame.font.SysFont(_fp, 18)              # row labels (Regular)
    f_value      = pygame.font.SysFont(_fp, 18, bold=True)   # row values (SemiBold)
    f_small_bold = pygame.font.SysFont(_fp, 14, bold=True)   # ON/OFF, badges
    f_sel        = pygame.font.SysFont(_fp, 17)              # Vehicle/Source line
    right_fonts  = (f_title, f_label, f_value, f_small_bold, f_sel)

    vehicles = [Vehicle(SIM_W/2, SIM_H/2)]
    selected_i = 0
    sources = [
        Source(SIM_W*0.78, SIM_H*0.28, "light"),
        Source(SIM_W*0.24, SIM_H*0.72, "heat"),
    ]
    selected_source_i = 0
    paused = False

    sim_ox = LEFT_W      # canvas x offset
    sim_oy = TITLE_H     # canvas y offset

    while True:
        dt = clock.tick(FPS) / 1000.0
        current_time_ms = pygame.time.get_ticks()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()

            elif event.type == pygame.MOUSEBUTTONDOWN:
                mx, my = event.pos
                # only add source if click is within sim canvas
                cx, cy = mx - sim_ox, my - sim_oy
                if 0 <= cx <= SIM_W and 0 <= cy <= SIM_H:
                    if event.button == 1:
                        sources.append(Source(cx, cy, "light"))
                        selected_source_i = len(sources) - 1
                    elif event.button == 3:
                        sources.append(Source(cx, cy, "heat"))
                        selected_source_i = len(sources) - 1

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    pygame.quit(); sys.exit()
                elif event.key == pygame.K_c:
                    sources.clear(); selected_source_i = 0
                elif event.key == pygame.K_r:
                    vehicles = [Vehicle(SIM_W/2, SIM_H/2)]; selected_i = 0
                elif event.key == pygame.K_SPACE:
                    paused = not paused
                elif event.key == pygame.K_w:
                    WIRING = "crossed" if WIRING == "uncrossed" else "uncrossed"
                elif event.key == pygame.K_f:
                    WALL_MODE = WALL_MODES[(WALL_MODES.index(WALL_MODE)+1) % len(WALL_MODES)]
                elif event.key == pygame.K_UP:
                    LIGHT_THRESHOLD = min(1.0, LIGHT_THRESHOLD + 0.02)
                elif event.key == pygame.K_DOWN:
                    LIGHT_THRESHOLD = max(0.05, LIGHT_THRESHOLD - 0.02)
                elif event.key == pygame.K_RIGHT:
                    HEAT_THRESHOLD = min(1.0, HEAT_THRESHOLD + 0.02)
                elif event.key == pygame.K_LEFT:
                    HEAT_THRESHOLD = max(0.05, HEAT_THRESHOLD - 0.02)
                elif event.key == pygame.K_1:
                    MOTOR_SPEED = max(20, MOTOR_SPEED - 5)
                elif event.key == pygame.K_2:
                    MOTOR_SPEED = min(140, MOTOR_SPEED + 5)
                elif event.key == pygame.K_n:
                    x = random.uniform(100, SIM_W-100)
                    y = random.uniform(100, SIM_H-100)
                    vehicles.append(Vehicle(x, y))
                    selected_i = len(vehicles) - 1
                elif event.key == pygame.K_TAB:
                    if vehicles: selected_i = (selected_i+1) % len(vehicles)
                elif event.key == pygame.K_a:
                    if vehicles: vehicles[selected_i].active = not vehicles[selected_i].active
                elif event.key == pygame.K_DELETE:
                    if vehicles:
                        vehicles.pop(selected_i)
                        selected_i = max(0, selected_i-1)
                elif event.key == pygame.K_s:
                    if sources: selected_source_i = (selected_source_i+1) % len(sources)
                elif event.key == pygame.K_x:
                    if sources: sources[selected_source_i].active = not sources[selected_source_i].active
                elif event.key == pygame.K_BACKSPACE:
                    if sources:
                        sources.pop(selected_source_i)
                        selected_source_i = max(0, selected_source_i-1)

        if not paused:
            for v in vehicles:
                v.step(dt, sources, current_time_ms)
            if WALL_MODE == "vanish":
                before = len(vehicles)
                vehicles = [v for v in vehicles
                            if -v.radius < v.x < SIM_W + v.radius
                            and -v.radius < v.y < SIM_H + v.radius]
                if len(vehicles) != before:
                    selected_i = min(selected_i, len(vehicles)-1) if vehicles else 0

        # ── render ─────────────────────────────────────────────────────────────
        draw_grid(screen, sim_ox, sim_oy, SIM_W, SIM_H)

        selected_source_i = min(selected_source_i, len(sources)-1) if sources else 0
        for i, s in enumerate(sources):
            draw_source(screen, s, i == selected_source_i, sim_ox, sim_oy)
        for i, v in enumerate(vehicles):
            draw_vehicle(screen, v, i == selected_i, sim_ox, sim_oy)

        draw_title(screen, fn, ft)
        draw_left_panel(screen, fonts, vehicles, selected_i, sources)
        draw_right_panel(screen, fonts, right_fonts, vehicles, selected_i, sources, selected_source_i)
        draw_status_bar(screen, fonts, vehicles, selected_i, paused)
        draw_help_bar(screen, fs, fn)

        pygame.display.flip()


if __name__ == "__main__":
    random.seed()
    main()
