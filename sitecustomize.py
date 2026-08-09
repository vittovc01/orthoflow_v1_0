"""Global mobile/PWA branding for OrthoFlow Control Tower.

Loaded automatically by Python when the repository root is on sys.path.
It keeps the existing Streamlit app architecture unchanged while applying
consistent favicon/title metadata and generating touch icons in ./static.
"""
from pathlib import Path

BRAND_NAME = "OrthoFlow Control Tower"
STATIC = Path(__file__).resolve().parent / "static"
STATIC.mkdir(exist_ok=True)


def _make_icon(path: Path, size: int) -> None:
    try:
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (size, size), "#071923")
        d = ImageDraw.Draw(img)
        pad = int(size * 0.09)
        radius = int(size * 0.22)
        d.rounded_rectangle((pad, pad, size-pad, size-pad), radius=radius, fill="#0B1F2A")
        cx = cy = size // 2
        r = int(size * 0.30)
        green = "#20C982"
        mint = "#E9FFF7"
        width = max(6, int(size * 0.055))
        d.ellipse((cx-r, cy-r, cx+r, cy+r), outline=green, width=width)
        r2 = int(size * 0.145)
        d.ellipse((cx-r2, cy-r2, cx+r2, cy+r2), outline=mint, width=max(5, int(size * 0.04)))
        arm = int(size * 0.39)
        for x1, y1, x2, y2 in [
            (cx, cy-arm, cx, cy-r), (cx, cy+r, cx, cy+arm),
            (cx-arm, cy, cx-r, cy), (cx+r, cy, cx+arm, cy),
        ]:
            d.line((x1, y1, x2, y2), fill=green, width=width)
        # Control-tower pointer / location cue.
        top = (cx, int(size * 0.34))
        left = (int(size * 0.40), int(size * 0.61))
        right = (int(size * 0.60), int(size * 0.61))
        d.polygon((top, right, left), fill=mint)
        d.ellipse((cx-int(size*.035), int(size*.55), cx+int(size*.035), int(size*.62)), fill=green)
        img.save(path, "PNG", optimize=True)
    except Exception:
        pass


for filename, size in (("icon-192.png", 192), ("icon-512.png", 512), ("apple-touch-icon.png", 180)):
    p = STATIC / filename
    if not p.exists():
        _make_icon(p, size)

# Monkey-patch Streamlit page config so every page gets OrthoFlow branding,
# including legacy pages that do not explicitly specify a page_icon.
try:
    import streamlit as st
    from streamlit.components.v1 import html as _html

    _original_set_page_config = st.set_page_config

    def _brand_set_page_config(*args, **kwargs):
        kwargs["page_title"] = BRAND_NAME
        kwargs.setdefault("page_icon", str(STATIC / "apple-touch-icon.png"))
        result = _original_set_page_config(*args, **kwargs)
        # Inject PWA/mobile metadata into the parent document. This is isolated
        # from business logic and safely ignored by browsers that block it.
        try:
            _html(
                """
                <script>
                try {
                  const d = window.parent.document;
                  const upsertLink = (rel, href, extra={}) => {
                    let el = d.querySelector(`link[rel='${rel}']`);
                    if (!el) { el = d.createElement('link'); el.rel = rel; d.head.appendChild(el); }
                    el.href = href;
                    Object.entries(extra).forEach(([k,v]) => el.setAttribute(k,v));
                  };
                  const upsertMeta = (name, content) => {
                    let el = d.querySelector(`meta[name='${name}']`);
                    if (!el) { el = d.createElement('meta'); el.name = name; d.head.appendChild(el); }
                    el.content = content;
                  };
                  upsertLink('manifest', '/app/static/manifest.json');
                  upsertLink('apple-touch-icon', '/app/static/apple-touch-icon.png', {sizes:'180x180'});
                  upsertLink('icon', '/app/static/icon-192.png', {type:'image/png'});
                  upsertMeta('theme-color', '#071923');
                  upsertMeta('mobile-web-app-capable', 'yes');
                  upsertMeta('apple-mobile-web-app-capable', 'yes');
                  upsertMeta('apple-mobile-web-app-status-bar-style', 'black-translucent');
                  upsertMeta('apple-mobile-web-app-title', 'OrthoFlow');
                  d.title = 'OrthoFlow Control Tower';
                } catch(e) {}
                </script>
                """,
                height=0,
                width=0,
            )
        except Exception:
            pass
        return result

    st.set_page_config = _brand_set_page_config
except Exception:
    pass
