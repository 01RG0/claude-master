"""
desktop/icons.py — Dynamic system tray status icons for claude-master.

Colors:
- Green (#22c55e): Normal / Healthy (Brain + Gateway running)
- Yellow (#eab308): Degraded (Partial components or warning states)
- Red (#ef4444): Stopped / Down / Error (Services offline)
- Orange (#f97316): Emergency Bypass active
"""

from __future__ import annotations
import io
from PIL import Image, ImageDraw

# Status color definitions (RGB)
STATUS_COLORS = {
    "green": (34, 197, 94),      # #22c55e: Normal
    "yellow": (234, 179, 8),     # #eab308: Degraded
    "red": (239, 68, 68),        # #ef4444: Stopped / Down
    "orange": (249, 115, 22),    # #f97316: Emergency Bypass
}

STATUS_NAMES = {
    "green": "Normal",
    "yellow": "Degraded",
    "red": "Stopped",
    "orange": "Emergency Bypass",
}


def create_tray_icon_image(status: str = "green", size: int = 64) -> Image.Image:
    """Generate a crisp, native-styled 64x64 tray icon with background glyph and status dot."""
    color = STATUS_COLORS.get(status.lower(), STATUS_COLORS["red"])
    
    # Base transparent canvas
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Dark rounded background shield / emblem
    pad = int(size * 0.08)
    draw.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=int(size * 0.22),
        fill=(24, 24, 27, 245),       # Dark slate (#18181b)
        outline=(63, 63, 70, 220),    # Border (#3f3f46)
        width=int(size * 0.04),
    )

    # Claude "C" synaptic logo glyph in center
    cx, cy = size // 2, size // 2
    inner_r = int(size * 0.22)
    draw.arc(
        [cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r],
        start=45,
        end=315,
        fill=(228, 228, 231, 230),   # Light glyph
        width=int(size * 0.08),
    )

    # Status indicator badge on bottom-right
    badge_r = int(size * 0.22)
    bx = size - pad - int(badge_r * 0.7)
    by = size - pad - int(badge_r * 0.7)

    # Status halo / border
    draw.ellipse(
        [bx - badge_r, by - badge_r, bx + badge_r, by + badge_r],
        fill=(15, 23, 42, 255),  # Background border for badge
    )
    # Status inner colored dot
    inner_badge_r = int(badge_r * 0.75)
    draw.ellipse(
        [bx - inner_badge_r, by - inner_badge_r, bx + inner_badge_r, by + inner_badge_r],
        fill=color + (255,),
    )

    return img


def get_icon_bytes(status: str = "green", format: str = "ICO") -> bytes:
    """Export icon as raw ICO or PNG bytes."""
    img = create_tray_icon_image(status)
    buf = io.BytesIO()
    img.save(buf, format=format)
    return buf.getvalue()
