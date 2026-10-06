"""Global mobile/PWA branding for P.M. Medical Control Tower.

Loaded automatically by Python when the repository root is on sys.path.
It keeps the existing Streamlit app architecture unchanged while applying
consistent favicon/title metadata and generating touch icons in ./static.
"""
from pathlib import Path

BRAND_NAME = "P.M. Medical Control Tower"
STATIC = Path(__file__).resolve().parent / "static"
STATIC.mkdir(exist_ok=True)


# Reuse the supplied company artwork for legacy Streamlit touch icons.
from shutil import copyfile
for filename, source in (("icon-192.png", "icon-192.png"), ("icon-512.png", "icon-512.png"), ("apple-touch-icon.png", "icon-192.png")):
    icon_source = Path(__file__).resolve().parent / "mobile" / "static" / source
    if icon_source.exists():
        copyfile(icon_source, STATIC / filename)

# Monkey-patch Streamlit page config so every page gets P.M. Medical branding,
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
                  upsertMeta('theme-color', '#004aad');
                  upsertMeta('mobile-web-app-capable', 'yes');
                  upsertMeta('apple-mobile-web-app-capable', 'yes');
                  upsertMeta('apple-mobile-web-app-status-bar-style', 'black-translucent');
                  upsertMeta('apple-mobile-web-app-title', 'P.M. Medical');
                  d.title = 'P.M. Medical Control Tower';
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
