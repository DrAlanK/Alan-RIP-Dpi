import math
import re
from dataclasses import dataclass
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from .theme import DARK_PALETTE, I18N, ThemePalette, lock_widget_dimensions, strip_emojis


@dataclass(frozen=True)
class CountryVisualSpec:
    code: str
    en_name: str
    fa_name: str
    c1: str
    c2: str
    c3: str

    def localized_name(self, lang: str | None = None) -> str:
        active = lang or I18N.lang
        return self.en_name if active == "en" else self.fa_name


COUNTRY_SPECS: dict[str, CountryVisualSpec] = {
    "": CountryVisualSpec("", "---", "---", "#FFD000", "#38BDF8", "#10B981"),
    "GLOBAL": CountryVisualSpec("GLOBAL", "---", "---", "#FFD000", "#38BDF8", "#10B981"),
    "IR": CountryVisualSpec("IR", "Iran", "ایران", "#169B62", "#FFD000", "#DA291C"),
    "DE": CountryVisualSpec("DE", "Germany", "آلمان", "#FFCE00", "#DD0000", "#F59E0B"),
    "NL": CountryVisualSpec("NL", "Netherlands", "هلند", "#2563EB", "#F8FAFC", "#E11D48"),
    "US": CountryVisualSpec("US", "United States", "آمریکا", "#3B82F6", "#EF4444", "#F8FAFC"),
    "GB": CountryVisualSpec("GB", "United Kingdom", "بریتانیا", "#2563EB", "#EF4444", "#F8FAFC"),
    "FR": CountryVisualSpec("FR", "France", "فرانسه", "#2563EB", "#F8FAFC", "#EF4444"),
    "FI": CountryVisualSpec("FI", "Finland", "فنلاند", "#38BDF8", "#F8FAFC", "#0284C7"),
    "SE": CountryVisualSpec("SE", "Sweden", "سوئد", "#0EA5E9", "#FACC15", "#38BDF8"),
    "TR": CountryVisualSpec("TR", "Turkey", "ترکیه", "#EF4444", "#F8FAFC", "#DC2626"),
    "AE": CountryVisualSpec("AE", "UAE", "امارات", "#10B981", "#EF4444", "#F8FAFC"),
    "CA": CountryVisualSpec("CA", "Canada", "کانادا", "#EF4444", "#FFFFFF", "#F87171"),
    "CH": CountryVisualSpec("CH", "Switzerland", "سوئیس", "#EF4444", "#FFFFFF", "#F87171"),
    "AT": CountryVisualSpec("AT", "Austria", "اتریش", "#EF4444", "#FFFFFF", "#DC2626"),
    "PL": CountryVisualSpec("PL", "Poland", "لهستان", "#F8FAFC", "#DC2626", "#FB7185"),
    "IT": CountryVisualSpec("IT", "Italy", "ایتالیا", "#10B981", "#FFFFFF", "#EF4444"),
    "ES": CountryVisualSpec("ES", "Spain", "اسپانیا", "#FACC15", "#DC2626", "#F59E0B"),
    "SG": CountryVisualSpec("SG", "Singapore", "سنگاپور", "#EF4444", "#FFFFFF", "#FB7185"),
    "JP": CountryVisualSpec("JP", "Japan", "ژاپن", "#F43F5E", "#FFFFFF", "#FDA4AF"),
    "RU": CountryVisualSpec("RU", "Russia", "روسیه", "#3B82F6", "#EF4444", "#FFFFFF"),
    "UA": CountryVisualSpec("UA", "Ukraine", "اوکراین", "#0EA5E9", "#FFD000", "#38BDF8"),
    "RO": CountryVisualSpec("RO", "Romania", "رومانی", "#3B82F6", "#FCD116", "#CE1126"),
    "KR": CountryVisualSpec("KR", "South Korea", "کره جنوبی", "#3B82F6", "#EF4444", "#FFFFFF"),
    "IN": CountryVisualSpec("IN", "India", "هند", "#FB923C", "#10B981", "#FFFFFF"),
}

_KEYWORD_MAP: list[tuple[tuple[str, ...], str]] = [
    (("iran", "tehran", "shiraz", "tabriz", "isfahan", "mashhad", "mci", "irancell", "ایران", "تهران"), "IR"),
    (("german", "germany", "frankfurt", "falkenstein", "nuremberg", "hetzner", "berlin", "munich", "آلمان", "فرانکفورت"), "DE"),
    (("netherland", "holland", "amsterdam", "rotterdam", "هلند", "آمستردام"), "NL"),
    (("united states", "america", "usa", "newyork", "new york", "dallas", "los angeles", "ashburn", "آمریکا"), "US"),
    (("united kingdom", "britain", "england", "london", "manchester", "انگلیس", "بریتانیا", "لندن"), "GB"),
    (("finland", "helsinki", "فنلاند", "هلسینکی"), "FI"),
    (("france", "paris", "marseille", "فرانسه", "پاریس"), "FR"),
    (("turkey", "turkiye", "istanbul", "ankara", "ترکیه", "استانبول"), "TR"),
    (("uae", "dubai", "abudhabi", "emirates", "امارات", "دبی"), "AE"),
    (("sweden", "stockholm", "سوئد", "استکهلم"), "SE"),
    (("switzerland", "swiss", "zurich", "geneva", "سوئیس", "زوریخ"), "CH"),
    (("singapore", "سنگاپور"), "SG"),
    (("japan", "tokyo", "osaka", "ژاپن", "توکیو"), "JP"),
    (("canada", "toronto", "montreal", "کانادا"), "CA"),
    (("poland", "warsaw", "لهستان"), "PL"),
    (("austria", "vienna", "اتریش", "وین"), "AT"),
    (("italy", "milan", "rome", "ایتالیا"), "IT"),
    (("spain", "madrid", "اسپانیا"), "ES"),
    (("russia", "moscow", "روسیه", "مسکو"), "RU"),
    (("ukraine", "kyiv", "اوکراین"), "UA"),
    (("romania", "bucharest", "رومانی", "بخارست"), "RO"),
    (("korea", "seoul", "کره"), "KR"),
    (("india", "mumbai", "هند"), "IN"),
]

_FLAG_ICON_CACHE: dict[tuple[str, int, int], QIcon] = {}


class GeoFlagResolver:
    @staticmethod
    def extract_unicode_flag(text: str) -> str:
        if not text:
            return ""
        chars = list(str(text))
        for i in range(len(chars) - 1):
            o1, o2 = ord(chars[i]), ord(chars[i + 1])
            if 0x1F1E6 <= o1 <= 0x1F1FF and 0x1F1E6 <= o2 <= 0x1F1FF:
                code = chr(o1 - 0x1F1E6 + ord("A")) + chr(o2 - 0x1F1E6 + ord("A"))
                return "GB" if code == "UK" else code
        return ""

    @staticmethod
    def clean_display_name(text: str) -> str:
        if not text:
            return ""
        cleaned = strip_emojis(str(text))
        m = re.match(r"^\[?([A-Za-z]{2})\]?\s*[-|:]?\s+(.+)$", cleaned)
        if m:
            cand = "GB" if m.group(1).upper() == "UK" else m.group(1).upper()
            if cand in COUNTRY_SPECS and cand not in ("", "GLOBAL"):
                return m.group(2).strip()
        return cleaned

    @staticmethod
    def resolve_code(*sources) -> str:
        for src in sources:
            if not src:
                continue
            if isinstance(src, dict):
                for explicit_key in ("egress_country_code", "country_code", "cc", "country", "egress_country"):
                    val = str(src.get(explicit_key) or "").strip().upper()
                    if val == "UK":
                        val = "GB"
                    if val in COUNTRY_SPECS and val not in ("", "GLOBAL"):
                        return val
                combined = " ".join(
                    str(src.get(k) or "")
                    for k in ("name", "title", "sni", "host_header", "host", "original_host", "address", "endpoint")
                )
                found = GeoFlagResolver.resolve_code(combined)
                if found not in ("", "GLOBAL"):
                    return found
                continue

            raw = str(src).strip()
            if not raw:
                continue
            upper_exact = raw.upper()
            if upper_exact == "UK":
                return "GB"
            if upper_exact in COUNTRY_SPECS and upper_exact not in ("", "GLOBAL"):
                return upper_exact

            uni = GeoFlagResolver.extract_unicode_flag(raw)
            if uni in COUNTRY_SPECS and uni not in ("", "GLOBAL"):
                return uni

            m_prefix = re.match(r"^\[?([A-Za-z]{2})\]?[\s\-_|/:]+", raw)
            if m_prefix:
                cand = "GB" if m_prefix.group(1).upper() == "UK" else m_prefix.group(1).upper()
                if cand in COUNTRY_SPECS and cand not in ("", "GLOBAL"):
                    return cand

            low = raw.lower()
            if low.endswith(".ir") or ".ir:" in low:
                return "IR"
            for keywords, code in _KEYWORD_MAP:
                for kw in keywords:
                    if kw in low:
                        return code

        return ""

    @staticmethod
    def get_spec(code: str) -> CountryVisualSpec:
        norm = str(code or "").strip().upper()
        if norm == "UK":
            norm = "GB"
        if norm in ("---", "NONE", "UNKNOWN"):
            norm = ""
        return COUNTRY_SPECS.get(norm, COUNTRY_SPECS[""])


class VectorFlagRenderer:
    @staticmethod
    def draw_flag(
        painter: QPainter,
        code: str,
        rect: QRectF,
        radius: float = 4.5,
        opacity: float = 1.0,
        with_border: bool = True,
    ) -> None:
        if rect.width() < 4.0 or rect.height() < 4.0:
            return
        norm = str(code or "").strip().upper()
        if norm == "UK":
            norm = "GB"

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setOpacity(opacity)

        clip = QPainterPath()
        clip.addRoundedRect(rect, radius, radius)
        painter.setClipPath(clip)

        if norm == "IR":
            VectorFlagRenderer._draw_iran_lion_and_sun(painter, rect)
        elif norm == "DE":
            VectorFlagRenderer._draw_h3(painter, rect, "#141414", "#DD0000", "#FFCE00")
        elif norm == "NL":
            VectorFlagRenderer._draw_h3(painter, rect, "#AE1C28", "#FFFFFF", "#21468B")
        elif norm == "RU":
            VectorFlagRenderer._draw_h3(painter, rect, "#FFFFFF", "#0039A6", "#D52B1E")
        elif norm == "AT":
            VectorFlagRenderer._draw_h3(painter, rect, "#ED2939", "#FFFFFF", "#ED2939")
        elif norm == "FR":
            VectorFlagRenderer._draw_v3(painter, rect, "#002395", "#FFFFFF", "#ED2939")
        elif norm == "IT":
            VectorFlagRenderer._draw_v3(painter, rect, "#009246", "#FFFFFF", "#CE2B37")
        elif norm == "RO":
            VectorFlagRenderer._draw_v3(painter, rect, "#002B7F", "#FCD116", "#CE1126")
        elif norm == "PL":
            VectorFlagRenderer._draw_h2(painter, rect, "#FFFFFF", "#DC143C")
        elif norm == "UA":
            VectorFlagRenderer._draw_h2(painter, rect, "#0057B7", "#FFD700")
        elif norm == "FI":
            VectorFlagRenderer._draw_nordic(painter, rect, "#FFFFFF", "#003580")
        elif norm == "SE":
            VectorFlagRenderer._draw_nordic(painter, rect, "#006AA7", "#FECC02")
        elif norm == "CH":
            VectorFlagRenderer._draw_swiss(painter, rect)
        elif norm == "TR":
            VectorFlagRenderer._draw_turkey(painter, rect)
        elif norm == "AE":
            VectorFlagRenderer._draw_uae(painter, rect)
        elif norm == "JP":
            VectorFlagRenderer._draw_japan(painter, rect)
        elif norm == "US":
            VectorFlagRenderer._draw_usa(painter, rect)
        elif norm == "GB":
            VectorFlagRenderer._draw_uk(painter, rect)
        elif norm == "SG":
            VectorFlagRenderer._draw_singapore(painter, rect)
        elif norm == "CA":
            VectorFlagRenderer._draw_canada(painter, rect)
        elif norm == "ES":
            VectorFlagRenderer._draw_spain(painter, rect)
        elif norm == "IN":
            VectorFlagRenderer._draw_india(painter, rect)
        elif norm == "KR":
            VectorFlagRenderer._draw_korea(painter, rect)
        else:
            VectorFlagRenderer._draw_globe_icon(painter, rect)

        gloss = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gloss.setColorAt(0.0, QColor(255, 255, 255, 48))
        gloss.setColorAt(0.45, QColor(255, 255, 255, 0))
        gloss.setColorAt(1.0, QColor(0, 0, 0, 34))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gloss)
        painter.drawRect(rect)

        painter.setClipping(False)
        if with_border:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(255, 255, 255, 68), 1.0))
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

        painter.restore()

    @staticmethod
    def _draw_h3(p: QPainter, r: QRectF, c1: str, c2: str, c3: str) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        sh = r.height() / 3.0
        p.setBrush(QColor(c1))
        p.drawRect(QRectF(r.x(), r.y(), r.width(), sh + 0.5))
        p.setBrush(QColor(c2))
        p.drawRect(QRectF(r.x(), r.y() + sh, r.width(), sh + 0.5))
        p.setBrush(QColor(c3))
        p.drawRect(QRectF(r.x(), r.y() + 2.0 * sh, r.width(), r.height() - 2.0 * sh))

    @staticmethod
    def _draw_v3(p: QPainter, r: QRectF, c1: str, c2: str, c3: str) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        sw = r.width() / 3.0
        p.setBrush(QColor(c1))
        p.drawRect(QRectF(r.x(), r.y(), sw + 0.5, r.height()))
        p.setBrush(QColor(c2))
        p.drawRect(QRectF(r.x() + sw, r.y(), sw + 0.5, r.height()))
        p.setBrush(QColor(c3))
        p.drawRect(QRectF(r.x() + 2.0 * sw, r.y(), r.width() - 2.0 * sw, r.height()))

    @staticmethod
    def _draw_h2(p: QPainter, r: QRectF, c1: str, c2: str) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        sh = r.height() / 2.0
        p.setBrush(QColor(c1))
        p.drawRect(QRectF(r.x(), r.y(), r.width(), sh + 0.5))
        p.setBrush(QColor(c2))
        p.drawRect(QRectF(r.x(), r.y() + sh, r.width(), sh))

    @staticmethod
    def _draw_star_polygon(p: QPainter, cx: float, cy: float, outer_r: float, color: QColor) -> None:
        star = QPainterPath()
        inner_r = outer_r * 0.40
        for i in range(10):
            ang = math.radians(-90.0 + i * 36.0)
            rad = outer_r if (i % 2 == 0) else inner_r
            pt = QPointF(cx + math.cos(ang) * rad, cy + math.sin(ang) * rad)
            if i == 0:
                star.moveTo(pt)
            else:
                star.lineTo(pt)
        star.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawPath(star)

    @staticmethod
    def _draw_iran_lion_and_sun(p: QPainter, r: QRectF) -> None:
        VectorFlagRenderer._draw_h3(p, r, "#169B62", "#FFFFFF", "#DA291C")

        cx = r.center().x()
        cy = r.center().y()
        u = r.height() * 0.31

        sun_cx = cx + u * 0.08
        sun_cy = cy - u * 0.03
        sun_r = u * 0.28

        rays = QPainterPath()
        num_rays = 17
        for i in range(num_rays):
            ang_deg = -175.0 + i * (170.0 / (num_rays - 1))
            ang = math.radians(ang_deg)
            spread = math.radians(4.4)
            tip_len = sun_r * (1.62 if i % 2 == 0 else 1.35)
            b1 = QPointF(sun_cx + math.cos(ang - spread) * (sun_r * 0.80), sun_cy + math.sin(ang - spread) * (sun_r * 0.80))
            tip = QPointF(sun_cx + math.cos(ang) * tip_len, sun_cy + math.sin(ang) * tip_len)
            b2 = QPointF(sun_cx + math.cos(ang + spread) * (sun_r * 0.80), sun_cy + math.sin(ang + spread) * (sun_r * 0.80))
            rays.moveTo(b1)
            rays.lineTo(tip)
            rays.lineTo(b2)
            rays.closeSubpath()

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#F59E0B"))
        p.drawPath(rays)

        sun_grad = QRadialGradient(QPointF(sun_cx, sun_cy - sun_r * 0.18), sun_r * 1.15)
        sun_grad.setColorAt(0.0, QColor("#FFF9C4"))
        sun_grad.setColorAt(0.60, QColor("#FFD000"))
        sun_grad.setColorAt(1.0, QColor("#D97706"))
        p.setBrush(sun_grad)
        p.drawEllipse(QPointF(sun_cx, sun_cy), sun_r, sun_r)

        def pt(nx: float, ny: float) -> QPointF:
            return QPointF(cx + nx * u, cy + ny * u)

        gold_grad = QLinearGradient(pt(-0.48, -0.45), pt(0.45, 0.46))
        gold_grad.setColorAt(0.0, QColor("#FFE45E"))
        gold_grad.setColorAt(0.55, QColor("#EAB308"))
        gold_grad.setColorAt(1.0, QColor("#B45309"))

        lion = QPainterPath()
        lion.moveTo(pt(-0.24, 0.43))
        lion.lineTo(pt(-0.26, 0.14))
        lion.cubicTo(pt(-0.38, 0.07), pt(-0.40, -0.11), pt(-0.31, -0.22))
        lion.lineTo(pt(-0.41, -0.24))
        lion.lineTo(pt(-0.40, -0.32))
        lion.lineTo(pt(-0.28, -0.37))
        lion.cubicTo(pt(-0.19, -0.41), pt(-0.12, -0.29), pt(-0.10, -0.14))
        lion.cubicTo(pt(0.04, -0.10), pt(0.20, -0.13), pt(0.33, -0.05))
        lion.cubicTo(pt(0.41, 0.07), pt(0.39, 0.25), pt(0.34, 0.43))
        lion.lineTo(pt(0.24, 0.43))
        lion.lineTo(pt(0.21, 0.16))
        lion.cubicTo(pt(0.08, 0.11), pt(-0.06, 0.14), pt(-0.15, 0.19))
        lion.lineTo(pt(-0.15, 0.43))
        lion.closeSubpath()

        sword = QPainterPath()
        sword.moveTo(pt(-0.27, -0.02))
        sword.lineTo(pt(-0.45, -0.08))
        sword.lineTo(pt(-0.43, -0.15))
        sword.lineTo(pt(-0.25, -0.09))
        sword.closeSubpath()

        sword.moveTo(pt(-0.47, -0.05))
        sword.cubicTo(pt(-0.55, -0.28), pt(-0.36, -0.48), pt(-0.08, -0.51))
        sword.cubicTo(pt(-0.31, -0.44), pt(-0.46, -0.24), pt(-0.41, -0.06))
        sword.closeSubpath()

        outline = (
            QPen(QColor("#78350F"), max(0.55, u * 0.036), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            if r.height() >= 22.0
            else Qt.PenStyle.NoPen
        )
        p.setPen(outline)
        p.setBrush(gold_grad)
        p.drawPath(lion)
        p.drawPath(sword)

        tail = QPainterPath()
        tail.moveTo(pt(0.33, -0.03))
        tail.cubicTo(pt(0.52, -0.12), pt(0.49, -0.38), pt(0.28, -0.40))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#D97706"), max(0.95, u * 0.075), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(tail)

        p.setPen(QPen(QColor("#B45309"), max(0.9, u * 0.065), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(pt(-0.50, 0.45), pt(0.48, 0.45))

    @staticmethod
    def _draw_nordic(p: QPainter, r: QRectF, bg: str, cross: str) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(bg))
        p.drawRect(r)
        p.setBrush(QColor(cross))
        thick = r.height() * 0.22
        cx = r.x() + r.width() * 0.36
        p.drawRect(QRectF(cx - thick / 2.0, r.y(), thick, r.height()))
        p.drawRect(QRectF(r.x(), r.center().y() - thick / 2.0, r.width(), thick))

    @staticmethod
    def _draw_swiss(p: QPainter, r: QRectF) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#DA291C"))
        p.drawRect(r)
        p.setBrush(QColor("#FFFFFF"))
        arm_l = min(r.width(), r.height()) * 0.60
        arm_t = arm_l * 0.32
        cx, cy = r.center().x(), r.center().y()
        p.drawRect(QRectF(cx - arm_t / 2.0, cy - arm_l / 2.0, arm_t, arm_l))
        p.drawRect(QRectF(cx - arm_l / 2.0, cy - arm_t / 2.0, arm_l, arm_t))

    @staticmethod
    def _draw_turkey(p: QPainter, r: QRectF) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#E30A17"))
        p.drawRect(r)
        cx, cy = r.x() + r.width() * 0.40, r.center().y()
        cr = r.height() * 0.26
        cres = QPainterPath()
        cres.addEllipse(QPointF(cx, cy), cr, cr)
        cut = QPainterPath()
        cut.addEllipse(QPointF(cx + cr * 0.28, cy), cr * 0.80, cr * 0.80)
        p.setBrush(QColor("#FFFFFF"))
        p.drawPath(cres.subtracted(cut))
        VectorFlagRenderer._draw_star_polygon(p, cx + cr * 1.05, cy, cr * 0.36, QColor("#FFFFFF"))

    @staticmethod
    def _draw_uae(p: QPainter, r: QRectF) -> None:
        VectorFlagRenderer._draw_h3(p, r, "#00732F", "#FFFFFF", "#111111")
        p.setBrush(QColor("#FF0000"))
        p.drawRect(QRectF(r.x(), r.y(), r.width() * 0.26, r.height()))

    @staticmethod
    def _draw_japan(p: QPainter, r: QRectF) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawRect(r)
        p.setBrush(QColor("#BC002D"))
        rad = min(r.width(), r.height()) * 0.29
        p.drawEllipse(r.center(), rad, rad)

    @staticmethod
    def _draw_usa(p: QPainter, r: QRectF) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawRect(r)
        sh = r.height() / 7.0
        p.setBrush(QColor("#B22234"))
        for i in range(0, 7, 2):
            p.drawRect(QRectF(r.x(), r.y() + i * sh, r.width(), sh))
        cw, ch = r.width() * 0.45, sh * 4.0
        p.setBrush(QColor("#3C3B6E"))
        p.drawRect(QRectF(r.x(), r.y(), cw, ch))
        p.setBrush(QColor("#FFFFFF"))
        dot_r = max(0.65, r.height() * 0.026)
        for row_i in range(3):
            for col_i in range(4):
                px = r.x() + cw * (0.18 + col_i * 0.21)
                py = r.y() + ch * (0.22 + row_i * 0.28)
                p.drawEllipse(QPointF(px, py), dot_r, dot_r)

    @staticmethod
    def _draw_uk(p: QPainter, r: QRectF) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#012169"))
        p.drawRect(r)
        h = r.height()
        p.setPen(QPen(QColor("#FFFFFF"), h * 0.18))
        p.drawLine(r.topLeft(), r.bottomRight())
        p.drawLine(r.bottomLeft(), r.topRight())
        p.setPen(QPen(QColor("#C8102E"), h * 0.08))
        p.drawLine(r.topLeft(), r.bottomRight())
        p.drawLine(r.bottomLeft(), r.topRight())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawRect(QRectF(r.center().x() - h * 0.16, r.y(), h * 0.32, h))
        p.drawRect(QRectF(r.x(), r.center().y() - h * 0.16, r.width(), h * 0.32))
        p.setBrush(QColor("#C8102E"))
        p.drawRect(QRectF(r.center().x() - h * 0.09, r.y(), h * 0.18, h))
        p.drawRect(QRectF(r.x(), r.center().y() - h * 0.09, r.width(), h * 0.18))

    @staticmethod
    def _draw_singapore(p: QPainter, r: QRectF) -> None:
        VectorFlagRenderer._draw_h2(p, r, "#EF3340", "#FFFFFF")
        cx, cy = r.x() + r.width() * 0.24, r.y() + r.height() * 0.25
        cr = r.height() * 0.16
        cres = QPainterPath()
        cres.addEllipse(QPointF(cx, cy), cr, cr)
        cut = QPainterPath()
        cut.addEllipse(QPointF(cx + cr * 0.35, cy), cr * 0.85, cr * 0.85)
        p.setBrush(QColor("#FFFFFF"))
        p.drawPath(cres.subtracted(cut))
        ring_cx = cx + cr * 0.55
        ring_r = cr * 0.48
        dot_r = max(0.6, r.height() * 0.024)
        for i in range(5):
            ang = math.radians(-90.0 + i * 72.0)
            p.drawEllipse(
                QPointF(ring_cx + math.cos(ang) * ring_r, cy + math.sin(ang) * ring_r),
                dot_r,
                dot_r,
            )

    @staticmethod
    def _draw_canada(p: QPainter, r: QRectF) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawRect(r)
        p.setBrush(QColor("#FF0000"))
        bw = r.width() * 0.25
        p.drawRect(QRectF(r.x(), r.y(), bw, r.height()))
        p.drawRect(QRectF(r.right() - bw, r.y(), bw, r.height()))
        cx, cy = r.center().x(), r.center().y()
        s = r.height() * 0.27
        leaf = QPainterPath()
        leaf.moveTo(cx, cy - s)
        leaf.lineTo(cx + s * 0.34, cy - s * 0.26)
        leaf.lineTo(cx + s * 0.84, cy - s * 0.20)
        leaf.lineTo(cx + s * 0.42, cy + s * 0.24)
        leaf.lineTo(cx + s * 0.11, cy + s * 0.24)
        leaf.lineTo(cx + s * 0.11, cy + s * 0.84)
        leaf.lineTo(cx - s * 0.11, cy + s * 0.84)
        leaf.lineTo(cx - s * 0.11, cy + s * 0.24)
        leaf.lineTo(cx - s * 0.42, cy + s * 0.24)
        leaf.lineTo(cx - s * 0.84, cy - s * 0.20)
        leaf.lineTo(cx - s * 0.34, cy - s * 0.26)
        leaf.closeSubpath()
        p.drawPath(leaf)

    @staticmethod
    def _draw_spain(p: QPainter, r: QRectF) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#AA151B"))
        p.drawRect(r)
        p.setBrush(QColor("#F1BF00"))
        p.drawRect(QRectF(r.x(), r.y() + r.height() * 0.25, r.width(), r.height() * 0.50))
        crest_rect = QRectF(
            r.x() + r.width() * 0.26,
            r.center().y() - r.height() * 0.13,
            r.height() * 0.20,
            r.height() * 0.26,
        )
        p.setBrush(QColor("#AA151B"))
        p.drawRoundedRect(crest_rect, 1.5, 1.5)

    @staticmethod
    def _draw_india(p: QPainter, r: QRectF) -> None:
        VectorFlagRenderer._draw_h3(p, r, "#FF9933", "#FFFFFF", "#138808")
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#000080"), max(1.0, r.height() * 0.05)))
        rad = r.height() * 0.12
        p.drawEllipse(r.center(), rad, rad)

    @staticmethod
    def _draw_korea(p: QPainter, r: QRectF) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawRect(r)
        rad = min(r.width(), r.height()) * 0.25
        p.setBrush(QColor("#CD2E3A"))
        p.drawEllipse(r.center(), rad, rad)

    @staticmethod
    def _draw_globe_icon(p: QPainter, r: QRectF) -> None:
        grad = QLinearGradient(r.topLeft(), r.bottomRight())
        grad.setColorAt(0.0, QColor("#141B27"))
        grad.setColorAt(1.0, QColor("#212D40"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawRect(r)

        rad = min(r.width(), r.height()) * 0.36
        cx, cy = r.center().x(), r.center().y()
        stroke_w = max(1.1, r.height() * 0.065)

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#38BDF8"), stroke_w * 0.85))
        p.drawLine(QPointF(cx - rad * 0.86, cy - rad * 0.45), QPointF(cx + rad * 0.86, cy - rad * 0.45))
        p.drawLine(QPointF(cx - rad * 0.86, cy + rad * 0.45), QPointF(cx + rad * 0.86, cy + rad * 0.45))
        p.drawLine(QPointF(cx, cy - rad), QPointF(cx, cy + rad))

        p.setPen(QPen(QColor("#FFD000"), stroke_w))
        p.drawEllipse(QPointF(cx, cy), rad, rad)
        p.drawEllipse(QPointF(cx, cy), rad * 0.48, rad)
        p.drawLine(QPointF(cx - rad, cy), QPointF(cx + rad, cy))


def make_flag_qicon(code: str, width: int = 26, height: int = 18) -> QIcon:
    norm = str(code or "").strip().upper()
    if norm == "UK":
        norm = "GB"
    key = (norm, width, height)
    if key in _FLAG_ICON_CACHE:
        return _FLAG_ICON_CACHE[key]

    dpr = 2.0
    pix = QPixmap(int(width * dpr), int(height * dpr))
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pix)
    VectorFlagRenderer.draw_flag(
        painter,
        norm,
        QRectF(0.5, 0.5, width - 1.0, height - 1.0),
        radius=3.5,
        with_border=True,
    )
    painter.end()

    icon = QIcon(pix)
    _FLAG_ICON_CACHE[key] = icon
    return icon


class FlagBadgeWidget(QWidget):
    def __init__(self, code: str = "", width: int = 30, height: int = 20, parent=None):
        super().__init__(parent)
        self._code: str | None = None
        self._palette: ThemePalette = DARK_PALETTE
        lock_widget_dimensions(self, width, height)
        self.set_country_code(code)

    def sizeHint(self) -> QSize:
        return QSize(self.width(), self.height())

    def set_palette_theme(self, palette: ThemePalette) -> None:
        self._palette = palette
        self.update()

    def set_country_code(self, code: str) -> None:
        norm = str(code or "").strip().upper()
        if norm == "UK":
            norm = "GB"
        if norm in ("GLOBAL", "---", "NONE", "UNKNOWN"):
            norm = ""
        if norm == self._code:
            return
        self._code = norm
        if not norm:
            self.setToolTip("---")
        else:
            spec = GeoFlagResolver.get_spec(norm)
            self.setToolTip(f"{spec.localized_name()} ({spec.code})")
        self.update()

    def country_code(self) -> str:
        return self._code or ""

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        outer = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        bezel_grad = QLinearGradient(outer.topLeft(), outer.bottomRight())
        bezel_grad.setColorAt(0.0, QColor(self._palette.neu_shadow_dark))
        bezel_grad.setColorAt(1.0, QColor(self._palette.neu_shadow_light))
        painter.setBrush(QColor(self._palette.input_bg))
        painter.setPen(QPen(bezel_grad, 1.0))
        painter.drawRoundedRect(outer, 5.0, 5.0)

        VectorFlagRenderer.draw_flag(
            painter,
            self._code or "",
            outer.adjusted(1.5, 1.5, -1.5, -1.5),
            radius=3.8,
            with_border=False,
        )