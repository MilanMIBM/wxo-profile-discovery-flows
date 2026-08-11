"""A 3D carousel / gallery view for arbitrary marimo outputs.

This is a "cover-flow" style gallery: each item you pass in becomes a card,
the cards are laid out on a horizontal track and tilted in 3D so they recede
toward the sides (like the inspiration cover-flow / Apple cover-flow effect),
and the user can drag, scroll, or click a card to bring it to the centre.

What can go in a card:
    Any object marimo can render -- ``mo.md(...)``, a ``pandas`` DataFrame,
    an image, a plot, a ``mo.ui.*`` element, or one of this project's own
    anywidget-based widgets. Each card shows that object rendered as HTML.

Interactivity -- the live centre vs. static sides:
    A marimo anywidget renders into its *own* DOM and cannot re-hydrate other
    marimo UI elements nested inside it, so cards on the track are *static*
    previews (great for markdown, tables, images, plots). To keep the focused
    item *fully interactive* (live sliders, editable dataframes, nested
    anywidgets, ...) the centred object is also exposed on ``.centered`` so you
    can render it live in a downstream cell through marimo's normal output
    pipeline:

        gallery = floating_card_view([df, mo.ui.slider(1, 10), my_widget])
        gallery                      # the 3D carousel (static card previews)

        # In a *separate* cell -- re-runs whenever you scroll/click, so the
        # centred object is rendered live and stays interactive:
        gallery.centered

Selection:
    Cards are selectable (click the checkmark, or enable ``select_on_center``
    to select whatever is centred). ``.value`` is the list of the *original*
    Python objects you passed in for the selected cards -- mirroring the
    convention of :func:`nosql_doc_browser` in
    :mod:`src.helpers.marimo_nosql_docviewer`.

The card size is set at construction (``card_width`` / ``card_height``) and
accepts either a number (interpreted as pixels) or any CSS length string
(``"45vmin"``, ``"30rem"``, ...).
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence, Union

import marimo as mo
import anywidget
import traitlets

from marimo._output.formatting import as_html


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _css_length(value: Union[int, float, str], *, default: str) -> str:
    """Normalize a size argument to a CSS length string.

    A bare number is treated as pixels (``320`` -> ``"320px"``); a string is
    passed through verbatim so any CSS unit works (``"45vmin"``, ``"30rem"``).
    ``None`` falls back to *default*.
    """
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return f"{value}px"
    return str(value)


def _render_card_html(obj: Any) -> str:
    """Render *obj* to an HTML string for a (static) card preview.

    Uses marimo's own formatter so anything marimo can display works: markdown,
    DataFrames, images, plots, ``mo.ui`` elements, custom anywidgets, etc. The
    markup is slotted into the card by the frontend as innerHTML; nested UI
    elements show their rendered form but are not re-hydrated (see module docs).
    """
    try:
        return as_html(obj).text
    except Exception as exc:  # pragma: no cover - defensive
        return f"<div class='fcv-render-error'>Could not render item: {exc}</div>"


# ---------------------------------------------------------------------------
# anywidget: the 3D card track
# ---------------------------------------------------------------------------


_ESM = r"""
function render({ model, el }) {
  el.classList.add("floating-card-view");

  // ----- behaviour read from Python traits -----
  const maxTilt = model.get("max_tilt");          // deg of Y-rotation at the edge
  const spread = model.get("spread");             // horizontal spacing multiplier
  const selectable = model.get("selectable");
  const selectOnCenter = model.get("select_on_center");
  const aspectRatio = model.get("aspect_ratio");  // stage height = width * ratio
  // Optional explicit card sizes; when blank, cards size from the stage so they
  // always fit (never spill below) and scale with the cell / window.
  const cardWOverride = model.get("card_width");
  const cardHOverride = model.get("card_height");
  // Fraction of the stage a centred card occupies, used when no override.
  const cardHeightFrac = model.get("card_height_frac");
  const cardAspect = model.get("card_aspect");    // card width / card height

  // Geometry recomputed from the measured stage on every layout / resize, so
  // the whole carousel scales reactively and the 3D-tilted cards stay inside
  // the stage box (no clipping below the cell).
  let geom = {
    stageW: 0, stageH: 0, cardW: 300, cardH: 380, depth: 220, captionH: 28,
  };

  function measure() {
    const rect = stage.getBoundingClientRect();
    const stageW = rect.width || el.clientWidth || 600;
    const stageH = rect.height || stageW * aspectRatio;

    // Bottom strip reserved for the caption; cards live in the area above it.
    const captionH = 28;
    const avail = Math.max(60, stageH - captionH);

    // Card height: explicit override, else a fraction of the *available* height
    // (stage minus caption). Cap it so tilted neighbours and the title bar fit.
    let cardH = cardHOverride
      ? resolveLen(cardHOverride, stageH)
      : avail * cardHeightFrac;
    cardH = Math.max(80, Math.min(cardH, avail * 0.96));

    // Card width: explicit override, else derived from height and aspect, but
    // never so wide that a centred card overflows the stage horizontally.
    let cardW = cardWOverride
      ? resolveLen(cardWOverride, stageW)
      : cardH * cardAspect;
    cardW = Math.max(80, Math.min(cardW, stageW * 0.9));

    geom = {
      stageW,
      stageH,
      cardW,
      cardH,
      captionH,
      // Depth scales with card size so the 3D recession reads consistently at
      // any zoom level.
      depth: cardW * 0.7,
    };
  }

  // Resolve a CSS-ish length the Python side may pass for an override: a number
  // (px), a "<n>px" / "<n>%" string (percent is relative to the stage extent),
  // or any other string we fall back to parsing as px.
  function resolveLen(value, extent) {
    if (typeof value === "number") return value;
    const s = String(value).trim();
    if (s.endsWith("%")) return (parseFloat(s) / 100) * extent;
    const px = parseFloat(s);
    return isNaN(px) ? extent * 0.6 : px;
  }

  // Persistent scroll position (0 .. n-1, fractional while dragging/animating).
  // Kept on the closure so re-renders of the chrome don't reset the view.
  let n = (model.get("items") || []).length;

  function clampPos(p) {
    return Math.max(0, Math.min(n - 1, p));
  }

  // Restore a sensible starting position from the centered index.
  let pos = clampPos(model.get("centered_index"));

  // ----- DOM scaffold -----
  el.replaceChildren();

  const stage = document.createElement("div");
  stage.className = "fcv-stage";
  // Width-driven height: the stage fills the cell width and takes a fraction of
  // it as height (default 60%). aspect-ratio keeps it reactive to the cell.
  stage.style.aspectRatio = `1 / ${aspectRatio}`;

  const track = document.createElement("div");
  track.className = "fcv-track";
  stage.appendChild(track);

  // Navigation arrows.
  const leftBtn = document.createElement("button");
  leftBtn.className = "fcv-arrow fcv-arrow-left";
  leftBtn.type = "button";
  leftBtn.setAttribute("aria-label", "Previous card");
  leftBtn.innerHTML =
    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none">' +
    '<path d="M15 5l-7 7 7 7" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round" stroke-linejoin="round"/></svg>';

  const rightBtn = document.createElement("button");
  rightBtn.className = "fcv-arrow fcv-arrow-right";
  rightBtn.type = "button";
  rightBtn.setAttribute("aria-label", "Next card");
  rightBtn.innerHTML =
    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none">' +
    '<path d="M9 5l7 7-7 7" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round" stroke-linejoin="round"/></svg>';

  el.appendChild(leftBtn);
  el.appendChild(stage);
  el.appendChild(rightBtn);

  const caption = document.createElement("div");
  caption.className = "fcv-caption";
  el.appendChild(caption);

  // ----- build the cards (static previews) -----
  let cards = [];

  function selectedSet() {
    return new Set(model.get("selected_indices") || []);
  }

  function buildCards() {
    track.replaceChildren();
    cards = [];
    const items = model.get("items") || [];
    n = items.length;
    pos = clampPos(pos);

    items.forEach((item, index) => {
      const card = document.createElement("div");
      card.className = "fcv-card";
      // Concrete px size is applied in layout() from the measured geometry.
      card.dataset.index = String(index);
      card.tabIndex = 0;
      card.setAttribute("role", "option");

      if (selectable) {
        const check = document.createElement("div");
        check.className = "fcv-check";
        check.innerHTML =
          '<svg width="14" height="14" viewBox="0 0 14 14" fill="none">' +
          '<path d="M3 7.5l3 3 5-6" stroke="currentColor" stroke-width="2" ' +
          'stroke-linecap="round" stroke-linejoin="round"/></svg>';
        // Toggling selection should not also re-centre the card.
        check.addEventListener("click", (e) => {
          e.stopPropagation();
          toggleSelect(index);
        });
        card.appendChild(check);
      }

      const title = document.createElement("div");
      title.className = "fcv-card-title";
      title.textContent = (model.get("titles") || [])[index] || `Item ${index + 1}`;
      card.appendChild(title);

      const body = document.createElement("div");
      body.className = "fcv-card-body";
      // Static preview: the object's rendered HTML, slotted as-is.
      body.innerHTML = item.html || "";
      card.appendChild(body);

      // Veil: a solid-background overlay whose opacity rises with distance from
      // the centre, so receding cards visually dissolve into the stage
      // background bit by bit -- while the card itself stays opaque, never
      // letting the cards behind it show through.
      const veil = document.createElement("div");
      veil.className = "fcv-veil";
      card.appendChild(veil);

      // Click a side card to bring it to centre; click the centred card to
      // select it (when selectable) so a single gesture both focuses and picks.
      card.addEventListener("click", () => {
        if (Math.round(pos) === index) {
          if (selectable && !selectOnCenter) toggleSelect(index);
        } else {
          animateTo(index);
        }
      });
      card.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          if (Math.round(pos) === index && selectable) toggleSelect(index);
          else animateTo(index);
        } else if (e.key === "ArrowLeft") {
          e.preventDefault();
          animateTo(index - 1);
        } else if (e.key === "ArrowRight") {
          e.preventDefault();
          animateTo(index + 1);
        }
      });

      track.appendChild(card);
      cards.push(card);
    });
    layout();
  }

  // ----- 3D layout: place each card relative to the current position -----
  function layout() {
    measure();                               // refresh geometry from the stage
    const { cardW, cardH, depth } = geom;
    const sel = selectedSet();
    const centeredIndex = Math.round(pos);
    cards.forEach((card, index) => {
      // Apply the reactive px size every pass so cards track cell/window size.
      card.style.width = cardW + "px";
      card.style.height = cardH + "px";

      const offset = index - pos;            // signed distance from centre
      const abs = Math.abs(offset);
      // Cards farther from centre slide sideways, recede in z, rotate away,
      // shrink and fade -- the cover-flow look. Sideways spacing is a fraction
      // of card width so neighbours overlap and stay within the stage.
      const x = offset * cardW * spread;
      const z = -abs * depth;
      const rotY = -Math.max(-1, Math.min(1, offset)) * maxTilt;
      const scale = Math.max(0.55, 1 - abs * 0.12);
      // Dissolve into the background, NOT via card opacity (which would let the
      // cards behind show through). Instead drive a solid-background veil whose
      // alpha rises with distance, so each card fades bit by bit into the stage
      // while remaining fully opaque to the cards stacked behind it.
      const veilAlpha = Math.min(0.82, abs * 0.32);

      // The card is absolutely positioned at top:50%/left:0; -50%/-50% keeps
      // it centred. Lift the whole stack up by half the caption strip so cards
      // sit vertically centred in the *visible* area above the caption.
      const yLift = geom.captionH / 2;

      card.style.transform =
        `translateX(calc(-50% + ${x}px)) translateY(calc(-50% - ${yLift}px)) ` +
        `translateZ(${z}px) rotateY(${rotY}deg) scale(${scale})`;
      card.style.opacity = "1";
      card.style.filter = "none";
      const veil = card.querySelector(".fcv-veil");
      if (veil) veil.style.opacity = String(veilAlpha);
      card.style.zIndex = String(1000 - Math.round(abs * 10));
      card.classList.toggle("is-centered", index === centeredIndex);
      card.classList.toggle("is-selected", sel.has(index));
      card.setAttribute(
        "aria-selected", sel.has(index) ? "true" : "false"
      );
      // Side cards shouldn't steal pointer focus from the centred one's body.
      card.style.pointerEvents = "auto";
    });
    updateCaption(centeredIndex);
  }

  function updateCaption(centeredIndex) {
    const titles = model.get("titles") || [];
    const total = cards.length;
    const name = titles[centeredIndex] || `Item ${centeredIndex + 1}`;
    const selCount = selectedSet().size;
    caption.textContent =
      total === 0
        ? "No items"
        : `${name}  -  ${centeredIndex + 1} / ${total}` +
          (selCount ? `  -  ${selCount} selected` : "");
  }

  // ----- animation: ease `pos` toward a target index -----
  let raf = null;
  function animateTo(target) {
    target = clampPos(target);
    if (raf) cancelAnimationFrame(raf);
    const start = pos;
    const t0 = performance.now();
    const dur = 360;
    function step(now) {
      const k = Math.min(1, (now - t0) / dur);
      // easeOutCubic
      const e = 1 - Math.pow(1 - k, 3);
      pos = start + (target - start) * e;
      layout();
      if (k < 1) {
        raf = requestAnimationFrame(step);
      } else {
        pos = target;
        layout();
        commitCenter(Math.round(pos));
      }
    }
    raf = requestAnimationFrame(step);
  }

  function commitCenter(index) {
    if (model.get("centered_index") !== index) {
      model.set("centered_index", index);
      model.save_changes();
    }
    if (selectOnCenter && selectable) setSelection([index]);
  }

  // ----- selection round-trip to Python -----
  function setSelection(indices) {
    const sorted = Array.from(new Set(indices)).sort((a, b) => a - b);
    model.set("selected_indices", sorted);
    model.save_changes();
    layout();
  }

  function toggleSelect(index) {
    const sel = selectedSet();
    if (sel.has(index)) sel.delete(index);
    else sel.add(index);
    setSelection(Array.from(sel));
  }

  // ----- input: arrows, drag, wheel -----
  leftBtn.addEventListener("click", () => animateTo(Math.round(pos) - 1));
  rightBtn.addEventListener("click", () => animateTo(Math.round(pos) + 1));

  let dragging = false;
  let dragStartX = 0;
  let dragStartPos = 0;

  function onDown(clientX) {
    dragging = true;
    dragStartX = clientX;
    dragStartPos = pos;
    if (raf) cancelAnimationFrame(raf);
    stage.classList.add("is-dragging");
  }
  function onMove(clientX) {
    if (!dragging) return;
    // px-per-card tracks the current (reactive) card width.
    const pxPerCard = Math.max(40, geom.cardW * spread);
    const delta = (dragStartX - clientX) / pxPerCard;
    pos = clampPos(dragStartPos + delta);
    layout();
  }
  function onUp() {
    if (!dragging) return;
    dragging = false;
    stage.classList.remove("is-dragging");
    animateTo(Math.round(pos));   // snap to nearest card
  }

  stage.addEventListener("mousedown", (e) => { e.preventDefault(); onDown(e.clientX); });
  window.addEventListener("mousemove", (e) => onMove(e.clientX));
  window.addEventListener("mouseup", onUp);
  stage.addEventListener("touchstart", (e) => onDown(e.touches[0].clientX), { passive: true });
  stage.addEventListener("touchmove", (e) => onMove(e.touches[0].clientX), { passive: true });
  stage.addEventListener("touchend", onUp);

  // Horizontal wheel / shift+wheel scrolls through cards -- but a wheel gesture
  // *inside* the centred card's scrollable body should scroll that content, not
  // drive the carousel. So when the event originates within the centred card's
  // body we let the browser handle it natively (unless that body can't actually
  // scroll in the wheel's direction, in which case we fall through to paging).
  stage.addEventListener("wheel", (e) => {
    const centeredCard = cards[Math.round(pos)];
    const body = centeredCard
      ? centeredCard.querySelector(".fcv-card-body")
      : null;
    if (body && body.contains(e.target)) {
      const canScrollDown =
        e.deltaY > 0 &&
        body.scrollTop + body.clientHeight < body.scrollHeight - 1;
      const canScrollUp = e.deltaY < 0 && body.scrollTop > 0;
      // The body can absorb this scroll: leave it to the browser.
      if (canScrollDown || canScrollUp) return;
    }
    const d = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
    if (Math.abs(d) < 2) return;
    e.preventDefault();
    animateTo(Math.round(pos) + (d > 0 ? 1 : -1));
  }, { passive: false });

  // ----- react to Python-side trait changes -----
  model.on("change:items", buildCards);
  model.on("change:titles", () => { buildCards(); });
  model.on("change:selected_indices", layout);
  model.on("change:centered_index", () => {
    const idx = clampPos(model.get("centered_index"));
    if (Math.round(pos) !== idx) animateTo(idx);
  });

  // Re-layout whenever the stage (i.e. the cell / window) changes size, so the
  // carousel scales reactively and cards keep fitting inside the stage.
  let resizeRaf = null;
  const ro = new ResizeObserver(() => {
    if (resizeRaf) cancelAnimationFrame(resizeRaf);
    resizeRaf = requestAnimationFrame(() => { if (!dragging) layout(); });
  });
  ro.observe(stage);

  buildCards();

  // anywidget calls the returned function on teardown.
  return () => {
    ro.disconnect();
    window.removeEventListener("mousemove", onMove);
    window.removeEventListener("mouseup", onUp);
  };
}

export default { render };
"""


_CSS = r"""
.floating-card-view {
  position: relative;
  font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
  width: 100%;
  color-scheme: light dark;

  --fcv-bg: #f4f5f7;
  --fcv-card-bg: #ffffff;
  --fcv-card-border: #e1e5e9;
  --fcv-text-primary: #172b4d;
  --fcv-text-secondary: #6b778c;
  --fcv-accent: #0052cc;
  --fcv-shadow: rgba(0, 0, 0, 0.28);
  --fcv-arrow-bg: rgba(255, 255, 255, 0.9);
  /* Scrollbar thumb: a slightly darker version of the card background. */
  --fcv-scrollbar: color-mix(in srgb, var(--fcv-card-bg) 82%, #000);
  --fcv-scrollbar-hover: color-mix(in srgb, var(--fcv-card-bg) 68%, #000);

  display: flex;
  align-items: center;
  gap: 6px;
}
.floating-card-view .fcv-stage {
  position: relative;
  flex: 1;
  min-width: 0;
  perspective: 1400px;
  perspective-origin: 50% 50%;
  overflow: hidden;
  border-radius: 12px;
  background:
    radial-gradient(ellipse at 50% 40%,
      color-mix(in srgb, var(--fcv-bg) 70%, transparent), var(--fcv-bg));
  cursor: grab;
  user-select: none;
}
.floating-card-view .fcv-stage.is-dragging {
  cursor: grabbing;
}
.floating-card-view .fcv-track {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translateY(-50%);
  transform-style: preserve-3d;
  width: 0;
  height: 0;
}
.floating-card-view .fcv-card {
  position: absolute;
  left: 0;
  top: 50%;
  margin-top: 0;
  transform-origin: center center;
  transform: translateX(-50%) translateY(-50%);
  background: var(--fcv-card-bg);
  border: 1px solid var(--fcv-card-border);
  border-radius: 12px;
  box-shadow: 0 10px 28px var(--fcv-shadow);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: box-shadow 0.2s ease;
  will-change: transform;
}
.floating-card-view .fcv-veil {
  position: absolute;
  inset: 0;
  z-index: 6;
  pointer-events: none;
  border-radius: inherit;
  /* Matches the stage backdrop so a receding card dissolves into it. */
  background: var(--fcv-bg);
  opacity: 0;
}
.floating-card-view .fcv-card.is-centered {
  box-shadow: 0 24px 60px var(--fcv-shadow);
}
.floating-card-view .fcv-card.is-selected {
  border-color: var(--fcv-accent);
  box-shadow: 0 0 0 2px var(--fcv-accent), 0 24px 60px var(--fcv-shadow);
}
.floating-card-view .fcv-card-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--fcv-text-secondary);
  padding: 8px 12px;
  border-bottom: 1px solid var(--fcv-card-border);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex-shrink: 0;
}
.floating-card-view .fcv-card-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 12px;
  font-size: 13px;
  color: var(--fcv-text-primary);
  /* Scrollbar: a slightly darker shade of the card background. */
  scrollbar-width: thin;
  scrollbar-color: var(--fcv-scrollbar) transparent;
}
.floating-card-view .fcv-card-body::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}
.floating-card-view .fcv-card-body::-webkit-scrollbar-track {
  background: transparent;
}
.floating-card-view .fcv-card-body::-webkit-scrollbar-thumb {
  background: var(--fcv-scrollbar);
  border-radius: 6px;
  /* Inset the thumb with a transparent border so it reads as a thin pill. */
  border: 2px solid transparent;
  background-clip: padding-box;
}
.floating-card-view .fcv-card-body::-webkit-scrollbar-thumb:hover {
  background: var(--fcv-scrollbar-hover);
  background-clip: padding-box;
}
.floating-card-view .fcv-card-body img,
.floating-card-view .fcv-card-body svg,
.floating-card-view .fcv-card-body canvas {
  max-width: 100%;
  height: auto;
}
.floating-card-view .fcv-check {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 7;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  border: 1px solid var(--fcv-card-border);
  background: var(--fcv-card-bg);
  color: transparent;
  cursor: pointer;
  transition: background 0.12s ease, color 0.12s ease, border-color 0.12s ease;
}
.floating-card-view .fcv-check:hover {
  border-color: var(--fcv-accent);
}
.floating-card-view .fcv-card.is-selected .fcv-check {
  background: var(--fcv-accent);
  border-color: var(--fcv-accent);
  color: #ffffff;
}
.floating-card-view .fcv-render-error {
  color: #b3261e;
  font-size: 12px;
}
.floating-card-view .fcv-arrow {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: 50%;
  border: 1px solid var(--fcv-card-border);
  background: var(--fcv-arrow-bg);
  color: var(--fcv-text-primary);
  cursor: pointer;
  transition: background 0.12s ease, border-color 0.12s ease;
}
.floating-card-view .fcv-arrow:hover {
  border-color: var(--fcv-accent);
  color: var(--fcv-accent);
}
.floating-card-view .fcv-caption {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 8px;
  text-align: center;
  font-size: 12px;
  color: var(--fcv-text-secondary);
  pointer-events: none;
}

.dark .floating-card-view,
.dark-theme .floating-card-view {
  --fcv-bg: #161616;
  --fcv-card-bg: #232323;
  --fcv-card-border: #3a3a3a;
  --fcv-text-primary: #e0e0e0;
  --fcv-text-secondary: #a0a0a0;
  --fcv-accent: #4d9fff;
  --fcv-shadow: rgba(0, 0, 0, 0.55);
  --fcv-arrow-bg: rgba(40, 40, 40, 0.9);
  /* On a dark card, darken toward black with a larger delta so the thumb
     stays visible while still reading as the same (darker) colour. */
  --fcv-scrollbar: color-mix(in srgb, var(--fcv-card-bg) 60%, #000);
  --fcv-scrollbar-hover: color-mix(in srgb, var(--fcv-card-bg) 40%, #000);
}
"""


class FloatingCardView(anywidget.AnyWidget):
    """anywidget rendering the 3D card track.

    Cards are *static* previews (rendered-object HTML slotted as innerHTML);
    behaviour, geometry and selection all live in traits so the Python wrapper
    can observe them. ``items`` is positionally aligned with the original
    objects held by the wrapper; ``selected_indices`` / ``centered_index`` point
    into that list.
    """

    _esm = traitlets.Unicode(_ESM).tag(sync=True)
    _css = traitlets.Unicode(_CSS).tag(sync=True)

    # Card content: [{"html": <rendered object html>}], aligned with the originals.
    items = traitlets.List(traitlets.Dict()).tag(sync=True)
    titles = traitlets.List(traitlets.Unicode()).tag(sync=True)

    # Geometry / behaviour (set once at construction).
    #
    # Sizes are reactive by default: the stage fills the cell width and takes
    # ``aspect_ratio`` of that as its height; cards are then sized from the
    # stage so they always fit (no spilling) and scale with the cell / window.
    aspect_ratio = traitlets.Float(default_value=0.6).tag(sync=True)
    card_height_frac = traitlets.Float(default_value=0.82).tag(sync=True)
    card_aspect = traitlets.Float(default_value=0.74).tag(sync=True)
    # Optional explicit overrides; "" means "derive from the stage". Accept a
    # px or % CSS string (the frontend also accepts a bare number as px).
    card_width = traitlets.Unicode("").tag(sync=True)
    card_height = traitlets.Unicode("").tag(sync=True)
    max_tilt = traitlets.Float(default_value=45.0).tag(sync=True)
    spread = traitlets.Float(default_value=0.62).tag(sync=True)
    selectable = traitlets.Bool(default_value=True).tag(sync=True)
    select_on_center = traitlets.Bool(default_value=False).tag(sync=True)

    # State that round-trips with the frontend.
    centered_index = traitlets.Int(default_value=0).tag(sync=True)
    selected_indices = traitlets.List(traitlets.Int()).tag(sync=True)


# ---------------------------------------------------------------------------
# Public element
# ---------------------------------------------------------------------------


class _FloatingCardViewElement(mo.ui.anywidget):
    """``mo.ui.anywidget`` wrapper exposing the selected / centred objects.

    Holds the original Python objects (the wrapper, not the widget, owns them so
    they survive trait serialization) and narrows ``.value`` to the selected
    ones. ``.centered`` returns the currently centred object for live rendering
    in a downstream cell.
    """

    def __init__(
        self,
        widget: FloatingCardView,
        *,
        objects: Sequence[Any],
        multiselect: bool,
    ) -> None:
        self._objects = list(objects)
        self._multiselect = multiselect
        self._selectable = bool(widget.selectable)
        self._raw_widget = widget

        super().__init__(widget)

        if not multiselect:
            # In single-select mode, keep at most one selected index.
            widget.observe(self._enforce_single_select, names="selected_indices")

    def _enforce_single_select(self, change) -> None:
        indices = change["new"] or []
        if len(indices) > 1:
            # Keep the most recently added (last) selection only.
            self._raw_widget.selected_indices = [indices[-1]]

    # -- accessors ----------------------------------------------------------

    @property
    def objects(self) -> List[Any]:
        """The original objects passed in, in card order."""
        return list(self._objects)

    @property
    def centered(self) -> Optional[Any]:
        """The currently centred object (for live rendering downstream).

        Reading this in a separate cell makes that cell re-run whenever the
        carousel is scrolled, so the centred object renders through marimo's
        normal output pipeline and stays fully interactive.
        """
        n = len(self._objects)
        idx = self._raw_widget.centered_index
        if 0 <= idx < n:
            return self._objects[idx]
        return None

    @property
    def centered_index(self) -> int:
        """Index of the currently centred card (``-1`` when empty)."""
        n = len(self._objects)
        idx = self._raw_widget.centered_index
        return idx if 0 <= idx < n else -1

    @property
    def selected(self) -> List[Any]:
        """Alias for :attr:`value` -- the selected original objects."""
        return self.value

    # -- value --------------------------------------------------------------

    @property
    def value(self) -> List[Any]:
        """The selected object(s), always as a list.

        Returns ``[]`` when nothing is selected, and one entry per selected card
        (in card order) otherwise. Mirrors ``nosql_doc_browser``'s convention so
        single- and multi-select share a uniform list-valued API. A browse-only
        gallery (``selectable=False``) always returns ``[]``.
        """
        if not self._selectable:
            return []
        n = len(self._objects)
        indices = sorted(i for i in self._raw_widget.selected_indices if 0 <= i < n)
        return [self._objects[i] for i in indices]

    @value.setter
    def value(self, value):
        del value
        raise RuntimeError("Setting the value of a UIElement is not allowed.")


def floating_card_view(
    items: Sequence[Any],
    *,
    titles: Optional[Sequence[str]] = None,
    aspect_ratio: float = 0.4,
    card_width: Optional[Union[int, float, str]] = None,
    card_height: Optional[Union[int, float, str]] = None,
    card_height_frac: float = 0.90,
    card_aspect: float = 0.70,
    multiselect: bool = False,
    selectable: bool = True,
    select_on_center: bool = False,
    max_tilt: float = 55.0,
    spread: float = 0.62,
    initial_index: int = 0,
) -> _FloatingCardViewElement:
    """A 3D cover-flow gallery of arbitrary marimo outputs.

    Each item becomes a card on a horizontal track tilted in 3D so the cards
    recede toward the sides. Drag, scroll, click a card, or use the arrow
    buttons to bring a card to the centre; cards are selectable and the selected
    *original* objects are exposed on ``.value``.

    Sizing is reactive: the carousel fills the width of the cell and is
    ``aspect_ratio`` of that wide tall (default 60% of the width). Cards are
    sized from that stage so they always fit inside it -- they never spill below
    the cell -- and rescale automatically when the cell or window resizes. Pass
    ``card_width`` / ``card_height`` only when you want to pin a fixed size.

    Cards on the track are *static* previews (a marimo anywidget cannot
    re-hydrate other UI elements nested in its DOM). To keep the focused item
    fully interactive, render ``.centered`` in a separate cell::

        gallery = floating_card_view([df, mo.ui.slider(1, 10), my_widget])
        gallery            # the 3D carousel

        # separate cell -- re-runs on scroll, renders the centred item live:
        gallery.centered

    Args:
        items: The objects to show, one per card. Anything marimo can render
            (``mo.md``, DataFrames, images, plots, ``mo.ui`` elements, custom
            anywidgets, ...).
        titles: Optional per-card titles, positionally aligned with *items*.
            Defaults to ``"Item 1"``, ``"Item 2"``, ...
        aspect_ratio: Stage height as a fraction of the cell width. Defaults to
            ``0.6`` (the carousel is 60% as tall as it is wide).
        card_width: Optional fixed card width override -- a number (pixels) or a
            CSS string. ``"50%"`` is taken relative to the stage width. When
            ``None`` (default) the width is derived from the card height and
            ``card_aspect`` so cards scale with the stage.
        card_height: Optional fixed card height override, same units as
            *card_width* (``"%"`` is relative to the stage height). When ``None``
            (default) the height is ``card_height_frac`` of the stage height.
        card_height_frac: When *card_height* is not given, the centred card's
            height as a fraction of the stage height. Defaults to ``0.82``.
        card_aspect: Card width / height ratio used when *card_width* is not
            given. Defaults to ``0.74`` (portrait, like the inspiration cards).
        multiselect: When True several cards can be selected at once; when False
            (default) only one card is selected at a time. ``.value`` is a list
            either way.
        selectable: When True (default) cards show a checkmark and can be
            selected. When False, the gallery is browse-only and ``.value`` is
            always empty (use ``.centered`` instead).
        select_on_center: When True, whatever card is centred is automatically
            selected (cover-flow "current item" behaviour). Defaults to False.
        max_tilt: Degrees of 3D Y-rotation applied to the side cards at the edge.
            Defaults to ``45``.
        spread: Horizontal spacing of cards as a fraction of card width. Smaller
            values overlap the cards more (more cover-flow-like). Defaults to
            ``0.62``.
        initial_index: Index of the card centred initially. Defaults to ``0``.

    Returns:
        A marimo UI element whose ``.value`` is the list of selected original
        objects, with ``.centered`` for the live-render-able focused object.
    """
    objects = list(items)
    n = len(objects)

    if titles is not None and len(titles) != n:
        raise ValueError("titles must have the same length as items")

    # Empty string => "derive from the stage" on the frontend.
    card_w = _css_length(card_width, default="") if card_width is not None else ""
    card_h = _css_length(card_height, default="") if card_height is not None else ""

    rendered = [{"html": _render_card_html(obj)} for obj in objects]
    card_titles = (
        [str(t) for t in titles]
        if titles is not None
        else [f"Item {i + 1}" for i in range(n)]
    )

    start = initial_index if 0 <= initial_index < n else 0

    widget = FloatingCardView(
        items=rendered,
        titles=card_titles,
        aspect_ratio=float(aspect_ratio),
        card_width=card_w,
        card_height=card_h,
        card_height_frac=float(card_height_frac),
        card_aspect=float(card_aspect),
        max_tilt=float(max_tilt),
        spread=float(spread),
        selectable=selectable,
        select_on_center=select_on_center,
        centered_index=start,
        selected_indices=[start] if (select_on_center and selectable and n) else [],
    )

    return _FloatingCardViewElement(
        widget,
        objects=objects,
        multiselect=multiselect,
    )
