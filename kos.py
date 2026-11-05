import sys
import math
import random
from PySide6.QtCore import (
    Qt, QTimer, QRectF, QPointF, Property, QPropertyAnimation, QEasingCurve, Signal
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QRadialGradient,
    QPainterPath, QFont
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QStackedWidget, QSizePolicy
)


# ==================== تنظیمات رنگ و فونت نئومورفیک تیره ====================
PALETTE = {
    "bg": "#1E222B",           # پس‌زمینه اصلی (خاکستری-سرمه‌ای مات برای دیده شدن هر دو سایه)
    "card_hi": "#252A35",      # سطح روشن کارت برجسته
    "card_lo": "#1B1F27",      # سطح تیره کارت برجسته
    "inset_hi": "#14171E",     # عمق تیره شیار فرورفته
    "inset_lo": "#1C2029",     # عمق روشن شیار فرورفته
    "gold_hi": "#FFD460",      # طلایی روشن
    "gold": "#F5B429",         # طلایی اصلی
    "gold_lo": "#D48806",      # طلایی تیره
    "emerald": "#10B981",      # سبز وضعیت اتصال و سیگنال
    "cyan": "#38BDF8",         # آبی فیروزه‌ای آپلود
    "text_main": "#F1F5F9",    # متن اصلی
    "text_sub": "#94A3B8",     # متن فرعی
    "text_dim": "#64748B",     # متن کم‌رنگ
}


def app_font(size: int, weight=QFont.Weight.Normal, mono: bool = False) -> QFont:
    font = QFont()
    if mono:
        font.setFamilies(["JetBrains Mono", "Cascadia Mono", "Consolas", "Segoe UI"])
    else:
        font.setFamilies(["Vazirmatn", "IRANSansX", "Tahoma", "Segoe UI"])
    font.setPointSize(size)
    font.setWeight(weight)
    return font


# ==================== توابع رندر سایه دوگانه نئومورفیسم ====================
def draw_neu_raised(
    painter: QPainter,
    rect: QRectF,
    radius: float = 18.0,
    depth: int = 6,
    glow_color: QColor | None = None,
):
    """رسم سطح برجسته نئومورفیک با سایه روشن بالا-چپ و سایه تیره پایین-راست"""
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)

    # سایه تیره پایین-راست
    for i in range(depth, 0, -1):
        d = i * 1.15
        sr = rect.adjusted(d * 0.3, d * 0.3, d, d)
        painter.setBrush(QColor(8, 10, 14, 30))
        painter.drawRoundedRect(sr, radius + i * 0.35, radius + i * 0.35)

    # هایلایت نرم بالا-چپ
    for i in range(depth, 0, -1):
        d = i * 1.05
        lr = rect.adjusted(-d, -d, -d * 0.3, -d * 0.3)
        painter.setBrush(QColor(60, 70, 88, 20))
        painter.drawRoundedRect(lr, radius + i * 0.35, radius + i * 0.35)

    # هاله نوری اختیاری در حالت فعال
    if glow_color is not None:
        for i in range(4, 0, -1):
            g = i * 1.8
            gr = rect.adjusted(-g, -g, g, g)
            c = QColor(glow_color)
            c.setAlpha(14)
            painter.setBrush(c)
            painter.drawRoundedRect(gr, radius + g * 0.5, radius + g * 0.5)

    # بدنه اصلی با گرادیان ملایم
    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0.0, QColor(PALETTE["card_hi"]))
    grad.setColorAt(1.0, QColor(PALETTE["card_lo"]))
    painter.setBrush(grad)
    painter.drawRoundedRect(rect, radius, radius)

    # خط لبه ظریف (Bevel) برای حس سه‌بعدی
    bevel = QLinearGradient(rect.topLeft(), rect.bottomRight())
    bevel.setColorAt(0.0, QColor(255, 255, 255, 24))
    bevel.setColorAt(0.5, QColor(255, 255, 255, 4))
    bevel.setColorAt(1.0, QColor(0, 0, 0, 95))
    painter.setPen(QPen(QBrush(bevel), 1.0))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(rect, radius, radius)
    painter.restore()


def draw_neu_inset(
    painter: QPainter,
    rect: QRectF,
    radius: float = 14.0,
    depth: int = 5,
):
    """رسم سطح فرورفته (حکاکی‌شده) نئومورفیک با سایه داخلی واقعی"""
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)

    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0.0, QColor(PALETTE["inset_hi"]))
    grad.setColorAt(1.0, QColor(PALETTE["inset_lo"]))
    painter.setBrush(grad)
    painter.drawRoundedRect(rect, radius, radius)

    # کلیپ کردن مسیر برای رسم سایه‌های درونی
    clip = QPainterPath()
    clip.addRoundedRect(rect, radius, radius)
    painter.setClipPath(clip)

    outer = QPainterPath()
    outer.addRect(rect.adjusted(-40, -40, 40, 40))

    # سایه تیره داخلی از بالا-چپ
    for i in range(1, depth + 1):
        s = i * 1.15
        hole = QPainterPath()
        hole.addRoundedRect(rect.adjusted(s, s, s * 0.25, s * 0.25), radius, radius)
        painter.fillPath(outer.subtracted(hole), QColor(5, 7, 11, 38))

    # بازتاب روشن داخلی از پایین-راست
    for i in range(1, depth + 1):
        s = i * 1.0
        hole = QPainterPath()
        hole.addRoundedRect(rect.adjusted(-s * 0.25, -s * 0.25, -s, -s), radius, radius)
        painter.fillPath(outer.subtracted(hole), QColor(66, 78, 98, 18))

    painter.restore()

    # لبه ظریف دور شیار
    painter.save()
    rim = QLinearGradient(rect.topLeft(), rect.bottomRight())
    rim.setColorAt(0.0, QColor(0, 0, 0, 115))
    rim.setColorAt(1.0, QColor(255, 255, 255, 18))
    painter.setPen(QPen(QBrush(rim), 1.0))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(rect, radius, radius)
    painter.restore()


# ==================== ویجت‌های پایه نئومورفیک ====================
class NeuCard(QWidget):
    def __init__(self, mode="raised", radius=18.0, margin=7, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.radius = radius
        self.margin = margin

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(
            self.margin, self.margin, -self.margin, -self.margin
        )
        if self.mode == "inset":
            draw_neu_inset(p, r, self.radius, depth=5)
        else:
            draw_neu_raised(p, r, self.radius, depth=5)


class NeuButton(QWidget):
    clicked = Signal()

    def __init__(self, text="", accent=False, radius=12.0, fixed_size=None, parent=None):
        super().__init__(parent)
        self.text = text
        self.accent = accent
        self.radius = radius
        self._pressed = False
        self._hovered = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if fixed_size:
            self.setFixedSize(*fixed_size)
        else:
            self.setMinimumHeight(36)

    def enterEvent(self, event):
        self._hovered = True
        self.update()

    def leaveEvent(self, event):
        self._hovered = False
        self._pressed = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()
            event.accept()

    def mouseReleaseEvent(self, event):
        if self._pressed and event.button() == Qt.MouseButton.LeftButton:
            self._pressed = False
            self.update()
            if self.rect().contains(event.position().toPoint()):
                self.clicked.emit()
            event.accept()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
        )
        r = QRectF(self.rect()).adjusted(4, 4, -4, -4)

        if self._pressed:
            draw_neu_inset(p, r, self.radius, depth=4)
        else:
            glow = QColor(PALETTE["gold"]) if (self.accent and self._hovered) else None
            draw_neu_raised(p, r, self.radius, depth=4, glow_color=glow)

        if self.accent and not self._pressed:
            # روکش طلایی ملایم برای دکمه‌های تاکیدی
            g = QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0.0, QColor(245, 180, 41, 42))
            g.setColorAt(1.0, QColor(212, 136, 6, 20))
            p.setPen(QPen(QColor(245, 180, 41, 90), 1.0))
            p.setBrush(g)
            p.drawRoundedRect(r, self.radius, self.radius)

        p.setFont(app_font(9, QFont.Weight.DemiBold))
        color = QColor(PALETTE["gold_hi"]) if self.accent else QColor(PALETTE["text_main"])
        if self._hovered and not self.accent:
            color = QColor(PALETTE["gold"])
        p.setPen(color)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.text)


class NeuSwitch(QWidget):
    toggled = Signal(bool)

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setFixedSize(50, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._checked = checked
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knobPos", self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def get_knob_pos(self) -> float:
        return self._pos

    def set_knob_pos(self, val: float):
        self._pos = float(val)
        self.update()

    knobPos = Property(float, get_knob_pos, set_knob_pos)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, state: bool):
        if self._checked != state:
            self._checked = state
            self._anim.stop()
            self._anim.setStartValue(self._pos)
            self._anim.setEndValue(1.0 if state else 0.0)
            self._anim.start()
            self.toggled.emit(state)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
            event.accept()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing)
        track = QRectF(2, 3, self.width() - 4, self.height() - 6)
        draw_neu_inset(p, track, track.height() / 2.0, depth=4)

        # نور ملایم داخل ریل هنگام روشن بودن
        if self._pos > 0.05:
            p.setPen(Qt.PenStyle.NoPen)
            glow = QColor(PALETTE["gold"])
            glow.setAlpha(int(55 * self._pos))
            p.setBrush(glow)
            p.drawRoundedRect(track.adjusted(2, 2, -2, -2), 8, 8)

        # دستگیره برجسته دایره‌ای
        travel = track.width() - track.height()
        kx = track.left() + 2 + self._pos * travel
        ky = track.top() + 2
        knob_size = track.height() - 4
        knob_rect = QRectF(kx, ky, knob_size, knob_size)

        if self._pos > 0.5:
            g = QLinearGradient(knob_rect.topLeft(), knob_rect.bottomRight())
            g.setColorAt(0.0, QColor(PALETTE["gold_hi"]))
            g.setColorAt(1.0, QColor(PALETTE["gold_lo"]))
            p.setPen(QPen(QColor(255, 255, 255, 60), 0.8))
            p.setBrush(g)
            p.drawEllipse(knob_rect)
        else:
            draw_neu_raised(p, knob_rect, knob_size / 2.0, depth=2)


# ==================== گوی مرکزی اتصال و طیف سیگنال ====================
class NeuPowerOrb(QWidget):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(166, 166)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.state = "idle"  # idle | connecting | connected
        self._pressed = False
        self._phase = 0.0
        self._levels = [0.25] * 32

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(45)

    def _tick(self):
        self._phase = (self._phase + 0.14) % (math.pi * 2)
        if self.state == "connected":
            self._levels = [
                0.45 + 0.55 * abs(math.sin(self._phase + i * 0.35)) * random.uniform(0.75, 1.0)
                for i in range(32)
            ]
        elif self.state == "connecting":
            self._levels = [
                0.25 + 0.75 * max(0.0, math.cos(self._phase * 2.2 - i * 0.25))
                for i in range(32)
            ]
        else:
            self._levels = [
                0.22 + 0.12 * math.sin(self._phase * 0.7 + i * 0.28)
                for i in range(32)
            ]
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            center = QPointF(self.width() / 2, self.height() / 2)
            if math.hypot(event.position().x() - center.x(), event.position().y() - center.y()) <= 68:
                self._pressed = True
                self.update()
                event.accept()

    def mouseReleaseEvent(self, event):
        if self._pressed and event.button() == Qt.MouseButton.LeftButton:
            self._pressed = False
            self.update()
            self.clicked.emit()
            event.accept()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
        )
        cx, cy = self.width() / 2.0, self.height() / 2.0

        # ۱. شیار دایره‌ای فرورفته بیرونی
        outer_r = 76.0
        outer_rect = QRectF(cx - outer_r, cy - outer_r, outer_r * 2, outer_r * 2)
        draw_neu_inset(p, outer_rect, outer_r, depth=6)

        # ۲. طیف زنده سیگنال تونل به شکل پرتوهای دایره‌ای
        for i, lvl in enumerate(self._levels):
            angle = (i / 32.0) * 2.0 * math.pi - math.pi / 2.0
            r_in = 54.0
            r_out = r_in + 8.0 + lvl * 9.5
            x1 = cx + math.cos(angle) * r_in
            y1 = cy + math.sin(angle) * r_in
            x2 = cx + math.cos(angle) * r_out
            y2 = cy + math.sin(angle) * r_out

            if self.state == "connected":
                # گرادیان تدریجی طلایی به سبز زمردی مشابه طیف سیگنال
                t = i / 31.0
                col = QColor(
                    int(245 * (1 - t) + 16 * t),
                    int(180 * (1 - t) + 185 * t),
                    int(41 * (1 - t) + 129 * t),
                    220,
                )
            elif self.state == "connecting":
                col = QColor(245, 180, 41, int(70 + 180 * lvl))
            else:
                col = QColor(148, 163, 184, int(55 + 75 * lvl))

            pen = QPen(col, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # ۳. دکمه برجسته مرکزی (با فرورفتگی واقعی هنگام کلیک)
        btn_r = 46.0
        btn_rect = QRectF(cx - btn_r, cy - btn_r, btn_r * 2, btn_r * 2)
        if self._pressed:
            draw_neu_inset(p, btn_rect, btn_r, depth=5)
        else:
            glow = None
            if self.state == "connected":
                glow = QColor(PALETTE["emerald"])
            elif self.state == "connecting":
                glow = QColor(PALETTE["gold"])
            draw_neu_raised(p, btn_rect, btn_r, depth=5, glow_color=glow)

        # حلقه ظریف دور هسته مرکزی
        ring_col = (
            QColor(PALETTE["emerald"])
            if self.state == "connected"
            else QColor(PALETTE["gold"])
        )
        ring_col.setAlpha(150 if self.state != "idle" else 85)
        p.setPen(QPen(ring_col, 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(btn_rect.adjusted(5, 5, -5, -5))

        # ۴. آیکون قفل/پاور برداری و برچسب وضعیت
        icon_col = (
            QColor(PALETTE["emerald"])
            if self.state == "connected"
            else QColor(PALETTE["gold_hi"])
        )
        p.setPen(QPen(icon_col, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        arc_rect = QRectF(cx - 11, cy - 19, 22, 22)
        p.drawArc(arc_rect, 130 * 16, 280 * 16)
        p.drawLine(QPointF(cx, cy - 22), QPointF(cx, cy - 9))

        p.setFont(app_font(8, QFont.Weight.Bold))
        caption = (
            "قطع اتصال"
            if self.state == "connected"
            else ("در حال اتصال" if self.state == "connecting" else "اتصال هوشمند")
        )
        p.setPen(QColor(PALETTE["text_main"]))
        p.drawText(
            QRectF(cx - 40, cy + 7, 80, 20),
            Qt.AlignmentFlag.AlignCenter,
            caption,
        )


# ==================== ویجت‌های تخصصی داشبورد ====================
class StatusPill(QWidget):
    """کپسول فرورفته برای تایمر و وضعیت"""
    def __init__(self, text="00:00:00", mono=True, gold_text=False, parent=None):
        super().__init__(parent)
        self.text = text
        self.mono = mono
        self.gold_text = gold_text
        self.setFixedHeight(28)
        self.setMinimumWidth(86)

    def setText(self, val: str):
        self.text = val
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
        )
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        draw_neu_inset(p, r, r.height() / 2.0, depth=4)
        p.setFont(app_font(9, QFont.Weight.Bold, mono=self.mono))
        p.setPen(
            QColor(PALETTE["gold_hi"]) if self.gold_text else QColor(PALETTE["text_main"])
        )
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.text)


class MetricCard(NeuCard):
    """کارت جمع‌وجور آمار شبکه با شیار نمایشگر فرورفته"""
    def __init__(self, title: str, symbol: str, accent_hex: str, initial: str = "---", parent=None):
        super().__init__(mode="raised", radius=16.0, margin=5, parent=parent)
        self.setFixedHeight(74)
        self.accent_hex = accent_hex

        lay = QVBoxLayout(self)
        lay.setContentsMargins(13, 10, 13, 10)
        lay.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(6)
        lbl_icon = QLabel(symbol)
        lbl_icon.setFont(app_font(9, QFont.Weight.Bold))
        lbl_icon.setStyleSheet(f"color: {accent_hex}; background: transparent;")

        lbl_title = QLabel(title)
        lbl_title.setFont(app_font(8, QFont.Weight.Medium))
        lbl_title.setStyleSheet(f"color: {PALETTE['text_sub']}; background: transparent;")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        top.addWidget(lbl_icon)
        top.addStretch()
        top.addWidget(lbl_title)

        self.val_pill = StatusPill(initial, mono=True)
        self.val_pill.setFixedHeight(26)

        lay.addLayout(top)
        lay.addWidget(self.val_pill)

    def set_value(self, text: str):
        self.val_pill.setText(text)


class TogglePod(NeuCard):
    """پاد سوییچ جمع‌وجور نئومورفیک"""
    def __init__(self, label: str, checked: bool = False, parent=None):
        super().__init__(mode="raised", radius=15.0, margin=4, parent=parent)
        self.setFixedHeight(68)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)

        lbl = QLabel(label)
        lbl.setFont(app_font(8, QFont.Weight.DemiBold))
        lbl.setStyleSheet(f"color: {PALETTE['text_main']}; background: transparent;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        sw_row = QHBoxLayout()
        sw_row.addStretch()
        self.switch = NeuSwitch(checked=checked)
        sw_row.addWidget(self.switch)
        sw_row.addStretch()

        lay.addWidget(lbl)
        lay.addLayout(sw_row)


class NeuBottomNav(QWidget):
    """داک پایینی نئومورفیک با ۵ تب اصلی و نشان تعداد کانفیگ"""
    tabChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(58)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.current_index = 0
        # چیدمان راست‌به‌چپ برای طبیعی بودن در زبان فارسی
        self.items = [
            ("گزارش زنده", "▣", 0),
            ("تنظیمات", "⚙", 0),
            ("آزمایشگاه", "⚗", 0),
            ("کانفیگ‌ها", "⚡", 4),
            ("خانه", "⌂", 0),
        ]
        self.current_index = 4  # پیش‌فرض روی «خانه»

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            w = (self.width() - 16) / len(self.items)
            idx = int((event.position().x() - 8) // w)
            idx = max(0, min(len(self.items) - 1, idx))
            if idx != self.current_index:
                self.current_index = idx
                self.update()
                # نگاشت ایندکس به صفحه متناظر (خانه = 0، کانفیگ‌ها = 1، ...)
                page_map = {4: 0, 3: 1, 2: 2, 1: 3, 0: 4}
                self.tabChanged.emit(page_map[idx])
            event.accept()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
        )
        outer = QRectF(self.rect()).adjusted(4, 3, -4, -3)
        draw_neu_inset(p, outer, 18.0, depth=5)

        count = len(self.items)
        slot_w = (outer.width() - 10) / count

        for i, (title, icon, badge) in enumerate(self.items):
            sr = QRectF(
                outer.left() + 5 + i * slot_w + 2,
                outer.top() + 4,
                slot_w - 4,
                outer.height() - 8,
            )
            active = i == self.current_index
            if active:
                draw_neu_raised(p, sr, 13.0, depth=3, glow_color=QColor(PALETTE["gold"]))

            p.setFont(app_font(11, QFont.Weight.Bold))
            p.setPen(
                QColor(PALETTE["gold_hi"]) if active else QColor(PALETTE["text_sub"])
            )
            p.drawText(
                QRectF(sr.left(), sr.top() + 3, sr.width(), 20),
                Qt.AlignmentFlag.AlignCenter,
                icon,
            )

            p.setFont(app_font(7, QFont.Weight.DemiBold if active else QFont.Weight.Normal))
            p.setPen(
                QColor(PALETTE["text_main"]) if active else QColor(PALETTE["text_dim"])
            )
            p.drawText(
                QRectF(sr.left(), sr.top() + 22, sr.width(), 18),
                Qt.AlignmentFlag.AlignCenter,
                title,
            )

            if badge > 0:
                br = QRectF(sr.center().x() + 6, sr.top() + 3, 15, 14)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(PALETTE["gold"]))
                p.drawRoundedRect(br, 7, 7)
                p.setFont(app_font(7, QFont.Weight.Bold, mono=True))
                p.setPen(QColor("#111318"))
                p.drawText(br, Qt.AlignmentFlag.AlignCenter, str(badge))


# ==================== پنجره اصلی کلاینت VPN نئومورفیک ====================
class AlanNeuVPNWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Alan-RIP-Dpi v1.1.0")
        self.setFixedSize(436, 748)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._drag_offset = None
        self._seconds = 0
        self._active_profile_idx = 0
        self.profiles = [
            ("Trojan · nightline-free", "TROJAN | VEC-23 | 2053", "GLOBAL", 38),
            ("VLESS · Reality-Frankfurt", "VLESS | REALITY | 443", "DE-FRA", 46),
            ("SplitHTTP · Edge-Worker", "SPLIT-HTTP | TLS | 8443", "NL-AMS", 54),
            ("XHTTP · Direct-Istanbul", "XHTTP | ANTI-DPI | 2083", "TR-IST", 29),
        ]

        self._build_ui()

        # تایمر زنده برای شمارنده زمان و شبیه‌ساز ترافیک تونل
        self._session_timer = QTimer(self)
        self._session_timer.timeout.connect(self._update_live_session)
        self._session_timer.start(1000)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(8)

        # ۱. نوار عنوان سفارشی
        header = QHBoxLayout()
        header.setContentsMargins(6, 2, 6, 2)
        header.setSpacing(8)

        btn_close = NeuButton("✕", radius=10, fixed_size=(34, 34))
        btn_close.clicked.connect(self.close)
        btn_min = NeuButton("—", radius=10, fixed_size=(34, 34))
        btn_min.clicked.connect(self.showMinimized)

        origin_pill = StatusPill("🇮🇷 مبدأ: ایران", mono=False)
        origin_pill.setFixedWidth(104)

        ver_badge = StatusPill("v1.1.0", mono=True, gold_text=True)
        ver_badge.setFixedWidth(60)

        brand_lbl = QLabel("Alan-RIP-Dpi")
        brand_lbl.setFont(app_font(11, QFont.Weight.Bold))
        brand_lbl.setStyleSheet(f"color: {PALETTE['text_main']}; background: transparent;")

        header.addWidget(btn_close)
        header.addWidget(btn_min)
        header.addWidget(origin_pill)
        header.addStretch()
        header.addWidget(ver_badge)
        header.addWidget(brand_lbl)
        root.addLayout(header)

        # ۲. صفحات قابل جابجایی
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_home_page())
        self.stack.addWidget(self._build_configs_page())
        self.stack.addWidget(self._build_simple_panel(
            "آزمایشگاه ضد-DPI",
            [
                ("قطعهقطعهسازی بسته‌های TCP (Fragment)", True),
                ("شکستن نام دامنه در دست‌تکان (SNI Split)", True),
                ("ارسال نامنظم پکت‌ها (Out-of-Order)", False),
                ("تزریق نویز محافظ ترافیک (Active Chaffing)", False),
            ],
        ))
        self.stack.addWidget(self._build_simple_panel(
            "تنظیمات هسته و مسیریابی",
            [
                ("عبور مستقیم ترافیک داخلی ایران (Bypass IR)", True),
                ("محافظت DNS از طریق تونل رمزنگاری‌شده", True),
                ("مسدودسازی نشت WebRTC و IPv6", True),
                ("اجرای خودکار همراه با بالا آمدن ویندوز", False),
            ],
        ))
        self.stack.addWidget(self._build_log_page())
        root.addWidget(self.stack, 1)

        # ۳. داک پایینی نئومورفیک
        self.nav = NeuBottomNav()
        self.nav.tabChanged.connect(self.stack.setCurrentIndex)
        root.addWidget(self.nav)

    def _build_home_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        # --- بخش قهرمان (Hero Card) ---
        hero = NeuCard(mode="raised", radius=22.0, margin=6)
        h_lay = QVBoxLayout(hero)
        h_lay.setContentsMargins(16, 12, 16, 12)
        h_lay.setSpacing(6)

        # ردیف وضعیت و تایمر
        top_status = QHBoxLayout()
        self.timer_pill = StatusPill("00:00:00", mono=True)
        self.auto_badge = StatusPill("AUTO", mono=True, gold_text=True)
        self.auto_badge.setFixedWidth(56)

        self.lbl_state = QLabel("آماده اتصال")
        self.lbl_state.setFont(app_font(12, QFont.Weight.Bold))
        self.lbl_state.setStyleSheet(f"color: {PALETTE['text_main']}; background: transparent;")

        top_status.addWidget(self.timer_pill)
        top_status.addStretch()
        top_status.addWidget(self.auto_badge)
        top_status.addWidget(self.lbl_state)
        h_lay.addLayout(top_status)

        # گوی مرکزی سه‌بعدی
        orb_row = QHBoxLayout()
        orb_row.addStretch()
        self.orb = NeuPowerOrb()
        self.orb.clicked.connect(self._toggle_connection)
        orb_row.addWidget(self.orb)
        orb_row.addStretch()
        h_lay.addLayout(orb_row)

        # زیرنویس موتور و مسیر فشرده مبدأ به مقصد
        self.lbl_sub = QLabel("موتور هوشمند آماده برقراری تونل امن است")
        self.lbl_sub.setFont(app_font(8, QFont.Weight.Normal))
        self.lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_sub.setStyleSheet(f"color: {PALETTE['text_sub']}; background: transparent;")
        h_lay.addWidget(self.lbl_sub)

        self.route_pill = StatusPill("مبدأ: ایران   ⟵   [ READY ]   ⟶   مقصد: GLOBAL", mono=False)
        h_lay.addWidget(self.route_pill)
        lay.addWidget(hero)

        # --- کارت نود خروجی و دکمه پینگ ---
        node_card = NeuCard(mode="raised", radius=16.0, margin=5)
        node_card.setFixedHeight(72)
        n_lay = QHBoxLayout(node_card)
        n_lay.setContentsMargins(12, 10, 14, 10)
        n_lay.setSpacing(8)

        self.btn_ping = NeuButton("⚡ پینگ", accent=True, radius=11, fixed_size=(76, 40))
        self.btn_ping.clicked.connect(self._run_ping_check)

        info_col = QVBoxLayout()
        info_col.setSpacing(2)
        self.lbl_node_name = QLabel("Trojan · nightline-free")
        self.lbl_node_name.setFont(app_font(9, QFont.Weight.Bold, mono=True))
        self.lbl_node_name.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.lbl_node_name.setStyleSheet(f"color: {PALETTE['text_main']}; background: transparent;")

        self.lbl_node_meta = QLabel("TROJAN | VEC-23 | 2053  •  نود مقصد")
        self.lbl_node_meta.setFont(app_font(8))
        self.lbl_node_meta.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.lbl_node_meta.setStyleSheet(f"color: {PALETTE['gold']}; background: transparent;")

        info_col.addWidget(self.lbl_node_name)
        info_col.addWidget(self.lbl_node_meta)

        n_lay.addWidget(self.btn_ping)
        n_lay.addStretch()
        n_lay.addLayout(info_col)
        lay.addWidget(node_card)

        # --- شبکه ۲×۲ آمار زنده ---
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)

        self.card_up = MetricCard("سرعت آپلود", "↑", PALETTE["cyan"], "0 B/s")
        self.card_dl = MetricCard("سرعت دانلود", "↓", PALETTE["gold"], "0 B/s")
        self.card_ping = MetricCard("پینگ واقعی", "◈", PALETTE["emerald"], "---")
        self.card_ip = MetricCard("آدرس IP خروجی", "🌐", PALETTE["gold_hi"], "---")

        grid.addWidget(self.card_up, 0, 0)
        grid.addWidget(self.card_dl, 0, 1)
        grid.addWidget(self.card_ping, 1, 0)
        grid.addWidget(self.card_ip, 1, 1)
        lay.addLayout(grid)

        # --- ردیف ۳ سوییچ کنترلی ---
        toggles_row = QHBoxLayout()
        toggles_row.setSpacing(6)
        self.pod_auto = TogglePod("اتصال خودکار", checked=False)
        self.pod_tun = TogglePod("حالت TUN", checked=False)
        self.pod_proxy = TogglePod("پروکسی سیستم", checked=True)

        toggles_row.addWidget(self.pod_auto)
        toggles_row.addWidget(self.pod_tun)
        toggles_row.addWidget(self.pod_proxy)
        lay.addLayout(toggles_row)

        return page

    def _build_configs_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(2, 4, 2, 4)
        lay.setSpacing(8)

        title = QLabel("لیست کانفیگ‌ها و خروجی‌های فعال (۴ مورد)")
        title.setFont(app_font(10, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignRight)
        title.setStyleSheet(f"color: {PALETTE['gold_hi']}; padding: 4px;")
        lay.addWidget(title)

        for idx, (name, proto, reg, ms) in enumerate(self.profiles):
            card = NeuCard(mode="raised", radius=15.0, margin=5)
            card.setFixedHeight(74)
            row = QHBoxLayout(card)
            row.setContentsMargins(12, 10, 14, 10)

            btn_sel = NeuButton("انتخاب", accent=(idx == 0), radius=10, fixed_size=(68, 36))
            btn_sel.clicked.connect(lambda checked=False, i=idx: self._select_profile(i))

            ping_pill = StatusPill(f"{ms} ms", mono=True, gold_text=True)
            ping_pill.setFixedWidth(64)

            col = QVBoxLayout()
            t1 = QLabel(name)
            t1.setFont(app_font(9, QFont.Weight.Bold, mono=True))
            t1.setAlignment(Qt.AlignmentFlag.AlignRight)
            t1.setStyleSheet(f"color: {PALETTE['text_main']};")

            t2 = QLabel(f"{proto}  •  {reg}")
            t2.setFont(app_font(8))
            t2.setAlignment(Qt.AlignmentFlag.AlignRight)
            t2.setStyleSheet(f"color: {PALETTE['text_sub']};")

            col.addWidget(t1)
            col.addWidget(t2)

            row.addWidget(btn_sel)
            row.addWidget(ping_pill)
            row.addStretch()
            row.addLayout(col)
            lay.addWidget(card)

        lay.addStretch()
        return page

    def _build_simple_panel(self, heading: str, options: list[tuple[str, bool]]) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(2, 4, 2, 4)
        lay.setSpacing(8)

        title = QLabel(heading)
        title.setFont(app_font(10, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignRight)
        title.setStyleSheet(f"color: {PALETTE['gold_hi']}; padding: 4px;")
        lay.addWidget(title)

        for text, default_on in options:
            card = NeuCard(mode="raised", radius=15.0, margin=5)
            card.setFixedHeight(64)
            row = QHBoxLayout(card)
            row.setContentsMargins(14, 8, 14, 8)
            sw = NeuSwitch(checked=default_on)
            lbl = QLabel(text)
            lbl.setFont(app_font(8, QFont.Weight.Medium))
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lbl.setStyleSheet(f"color: {PALETTE['text_main']};")
            row.addWidget(sw)
            row.addStretch()
            row.addWidget(lbl)
            lay.addWidget(card)

        lay.addStretch()
        return page

    def _build_log_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(2, 4, 2, 4)
        lay.setSpacing(8)

        top = QHBoxLayout()
        btn_clear = NeuButton("پاک‌سازی", radius=10, fixed_size=(80, 34))
        lbl = QLabel("گزارش زنده هسته تونل")
        lbl.setFont(app_font(10, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {PALETTE['gold_hi']};")
        top.addWidget(btn_clear)
        top.addStretch()
        top.addWidget(lbl)
        lay.addLayout(top)

        well = NeuCard(mode="inset", radius=16.0, margin=4)
        well.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        w_lay = QVBoxLayout(well)
        w_lay.setContentsMargins(14, 14, 14, 14)

        self.lbl_logs = QLabel(
            "[INFO] Alan-RIP-Dpi v1.1.0 initialized.\n"
            "[CORE] Anti-DPI engine ready (TCP Fragment + SNI Split).\n"
            "[OUTBOUND] Loaded 4 active profiles.\n"
            "[PROXY] System proxy listener standby on 127.0.0.1:10809."
        )
        self.lbl_logs.setFont(app_font(8, mono=True))
        self.lbl_logs.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.lbl_logs.setWordWrap(True)
        self.lbl_logs.setStyleSheet(f"color: {PALETTE['emerald']}; background: transparent;")
        btn_clear.clicked.connect(lambda: self.lbl_logs.setText("[LOG] Cleared."))
        w_lay.addWidget(self.lbl_logs)
        lay.addWidget(well, 1)
        return page

    # ==================== منطق تعاملی اتصال و شبیه‌ساز زنده ====================
    def _select_profile(self, idx: int):
        self._active_profile_idx = idx
        name, proto, reg, ms = self.profiles[idx]
        self.lbl_node_name.setText(name)
        self.lbl_node_meta.setText(f"{proto}  •  نود مقصد")
        if self.orb.state == "connected":
            self.card_ping.set_value(f"{ms} ms")
            self.route_pill.setText(f"مبدأ: ایران   ⟵   [ TUNNEL ]   ⟶   مقصد: {reg}")
        else:
            self.route_pill.setText(f"مبدأ: ایران   ⟵   [ READY ]   ⟶   مقصد: {reg}")
        self.nav.current_index = 4
        self.nav.update()
        self.stack.setCurrentIndex(0)

    def _toggle_connection(self):
        if self.orb.state in ("idle", "connecting"):
            if self.orb.state == "connecting":
                return
            self.orb.state = "connecting"
            self.lbl_state.setText("در حال اتصال...")
            self.lbl_state.setStyleSheet(f"color: {PALETTE['gold_hi']}; background: transparent;")
            self.lbl_sub.setText("در حال مذاکره TLS و عبور از فیلترینگ DPI...")
            QTimer.singleShot(950, self._finalize_connect)
        else:
            self.orb.state = "idle"
            self._seconds = 0
            self.timer_pill.setText("00:00:00")
            self.lbl_state.setText("آماده اتصال")
            self.lbl_state.setStyleSheet(f"color: {PALETTE['text_main']}; background: transparent;")
            self.lbl_sub.setText("موتور هوشمند آماده برقراری تونل امن است")
            _, _, reg, _ = self.profiles[self._active_profile_idx]
            self.route_pill.setText(f"مبدأ: ایران   ⟵   [ READY ]   ⟶   مقصد: {reg}")
            self.card_dl.set_value("0 B/s")
            self.card_up.set_value("0 B/s")
            self.card_ping.set_value("---")
            self.card_ip.set_value("---")

    def _finalize_connect(self):
        self.orb.state = "connected"
        _, _, reg, ms = self.profiles[self._active_profile_idx]
        self.lbl_state.setText("تونل فعال و ایمن")
        self.lbl_state.setStyleSheet(f"color: {PALETTE['emerald']}; background: transparent;")
        self.lbl_sub.setText("ترافیک سیستم با محافظت ضد-DPI رمزنگاری شد")
        self.route_pill.setText(f"مبدأ: ایران   ⟵   [ SECURED ]   ⟶   مقصد: {reg}")
        self.card_ping.set_value(f"{ms} ms")
        self.card_ip.set_value("104.21.48.209")

    def _run_ping_check(self):
        _, _, _, base_ms = self.profiles[self._active_profile_idx]
        jitter = random.randint(-4, 6)
        self.card_ping.set_value(f"{max(18, base_ms + jitter)} ms")

    def _update_live_session(self):
        if self.orb.state == "connected":
            self._seconds += 1
            h = self._seconds // 3600
            m = (self._seconds % 3600) // 60
            s = self._seconds % 60
            self.timer_pill.setText(f"{h:02d}:{m:02d}:{s:02d}")

            dl = random.uniform(1.8, 9.4)
            up = random.uniform(0.35, 2.1)
            self.card_dl.set_value(f"{dl:.1f} MB/s")
            self.card_up.set_value(f"{up:.2f} MB/s")

    # ==================== جابجایی پنجره بدون فریم با ماوس ====================
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() <= 58:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_offset = None

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing)
        shell = QRectF(self.rect()).adjusted(6, 6, -6, -6)

        # سایه بیرونی نرم پنجره
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(5, 0, -1):
            p.setBrush(QColor(0, 0, 0, 26))
            p.drawRoundedRect(shell.adjusted(-i, -i, i, i), 28 + i * 0.5, 28 + i * 0.5)

        # پوسته اصلی مات نئومورفیک
        p.setBrush(QColor(PALETTE["bg"]))
        p.setPen(QPen(QColor(255, 255, 255, 20), 1.0))
        p.drawRoundedRect(shell, 26.0, 26.0)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AlanNeuVPNWindow()
    window.show()
    sys.exit(app.exec())