/* Asol Dam: hover and loading motion, ported from VengeanceUI components to plain JavaScript.
   Each block names the component it comes from. Delete this file and motion.css to remove all of it. */
(() => {
  "use strict";
  const calm = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $ = (id) => document.getElementById(id);

  // ---------- 1. ASCII Glitch Ripple: hovering the logo scrambles it in a wave from the cursor ----------
  // Works on the bilingual logo (আসল Dam / Ashol দাম): it splits each word into whole letters
  // (a Bangla letter with its vowel sign counts as one), so Bangla never breaks into pieces.
  function glitch(logo) {
    const CHARS = '.,·-─~+:;=*π""┐┌┘┴┬╗╔╝╚╬╠╣╩╦║░▒▓█▄▀▌▐■!?&#$@0123456789*';
    const DUR = 1000, WAVE_THRESH = 3, CHAR_MULT = 3, ANIM_STEP = 40, WAVE_BUF = 5;
    const split = (text) => (window.Intl?.Segmenter
      ? [...new Intl.Segmenter("bn", { granularity: "grapheme" }).segment(text)].map((s) => s.segment)
      : [...text]);
    const words = [...logo.querySelectorAll(".w-to")];
    if (!words.length) return;
    let parts = null, total = 0;  // [{ node, letters, start }]
    let waves = [], frame = null, cursor = 0, hover = false;

    const position = (e) => {
      const r = logo.getBoundingClientRect();
      cursor = Math.max(0, Math.min(Math.round(((e.clientX - r.left) / r.width) * total), total - 1));
    };
    const glyph = (i, t) => {
      let out = null;
      for (const w of waves) {
        const age = t - w.start, dist = Math.abs(i - w.pos);
        const radius = Math.min(age / DUR, 1) * (Math.max(w.pos, total - w.pos - 1) + WAVE_BUF);
        const strength = radius - dist;
        if (dist <= radius && strength > 0 && strength <= WAVE_THRESH) {
          out = CHARS[(dist * CHAR_MULT + Math.floor(age / ANIM_STEP)) % CHARS.length];
        }
      }
      return out;
    };
    const stop = () => {
      for (const p of parts) { p.node.textContent = p.letters.join(""); p.node.style.width = ""; p.node.classList.remove("is-glitching"); }
      frame = null;
    };
    const tick = () => {
      const t = performance.now();
      waves = waves.filter((w) => t - w.start < DUR);
      if (!waves.length) return stop();
      for (const p of parts) p.node.textContent = p.letters.map((ch, k) => glyph(p.start + k, t) ?? ch).join("");
      frame = requestAnimationFrame(tick);
    };
    const wave = () => {
      if (calm() || (logo.classList.contains("intro-mark") && !logo.dataset.ready)) return;
      if (!frame) {
        let start = 0;
        parts = words.map((node) => {
          const letters = split(node.textContent);
          const p = { node, letters, start };
          start += letters.length;
          return p;
        });
        total = start;
        for (const p of parts) {  // no layout jump while scrambled
          p.node.style.width = `${p.node.getBoundingClientRect().width / (logo.getBoundingClientRect().width / logo.offsetWidth || 1)}px`;
          p.node.classList.add("is-glitching");
        }
        frame = requestAnimationFrame(tick);
      }
      waves.push({ pos: cursor, start: performance.now() });
    };
    logo.addEventListener("mouseenter", (e) => { hover = true; if (!frame) { total = total || 1; } position(e); wave(); });
    logo.addEventListener("mousemove", (e) => {
      if (!hover) return;
      const before = cursor; position(e);
      if (cursor !== before) wave();
    });
    logo.addEventListener("mouseleave", () => { hover = false; });
  }

  // ---------- Light / dark switch: the new colours spread out in a circle from the button ----------
  function themeSwitch() {
    const main = $("themeToggle");
    if (!main) return;
    let passing = false;
    const flip = () => { passing = true; main.click(); passing = false; };
    const run = (origin) => {
      if (!document.startViewTransition || calm()) return flip();
      const r = origin.getBoundingClientRect();
      const x = r.left + r.width / 2, y = r.top + r.height / 2;
      const radius = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
      const change = document.startViewTransition(flip);
      change.ready.then(() => document.documentElement.animate(
        { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
        { duration: 560, easing: "cubic-bezier(0.65, 0, 0.35, 1)", pseudoElement: "::view-transition-new(root)" },
      )).catch(() => {});
    };
    // The header button (app.js does the actual switch) and any other button marked data-theme-toggle.
    main.addEventListener("click", (e) => { if (passing) return; e.stopImmediatePropagation(); run(main); }, true);
    for (const b of document.querySelectorAll("[data-theme-toggle]")) b.addEventListener("click", () => run(b));
  }

  // ---------- 2. "Check" button: on hover each letter rolls up and an amber copy rolls in ----------
  // (A letter-by-letter roll, like the digits on a cash register.)
  function roll(button) {
    const build = () => {
      const label = button.textContent.trim();
      if (!label || button.dataset.label === label) return;
      button.dataset.label = label;
      button.setAttribute("aria-label", label);
      button.textContent = "";
      const word = document.createElement("span");
      word.className = "roll";
      word.setAttribute("aria-hidden", "true");
      [...label].forEach((ch, i) => {
        const cell = document.createElement("span");
        cell.className = "roll-ch";
        cell.style.setProperty("--i", i);
        const glyph = ch === " " ? " " : ch;
        cell.innerHTML = `<span>${glyph}</span><span>${glyph}</span>`;
        word.appendChild(cell);
      });
      button.appendChild(word);
    };
    build();
    // app.js swaps the text to "Checking…" and back: rebuild the letters each time.
    new MutationObserver(() => { if (!button.querySelector(".roll")) { delete button.dataset.label; build(); } })
      .observe(button, { childList: true, characterData: true, subtree: true });
  }

  // ---------- 3. Loader: a little receipt printing, in the middle of the receipt column ----------
  // Paper glides out of a printer slot while the price digits spin and land like a cash register. Then it's torn off and the next one prints.
  function loader() {
    const wrap = document.querySelector(".slip-wrap");
    const column = document.querySelector(".col-center") || wrap;
    const box = document.createElement("div");
    box.className = "printer";
    box.setAttribute("role", "status");
    // Each digit is a strip of 21 numbers that rolls and eases to a stop; they land one after
    // another (left to right), like a till working out the price: ৳2,739.
    const reels = [[1, 11], [4, 13], [8, 15], [2, 17]].map(([start, travel]) =>
      `<span class="reel"><span style="--t:${travel}">${[...Array(21).keys()].map((n) => (n + start) % 10).join("<br>")}</span></span>`);
    box.innerHTML = `
      <div class="printer-slot" aria-hidden="true"></div>
      <div class="printer-out" aria-hidden="true">
        <div class="printer-paper">
          <p class="pp-head">ASOL DAM</p>
          <p class="pp-price">৳ ${reels[0]},${reels.slice(1).join("")}</p>
          <i class="pp-line" style="--w:86%"></i><i class="pp-line" style="--w:62%"></i><i class="pp-line" style="--w:74%"></i>
          <div class="pp-bars"></div>
        </div>
      </div>
      <p class="printer-say mono"><span>Reading the price</span><span>Searching other sellers</span><span>Comparing the real price</span></p>
      <span class="visually-hidden">Checking the price…</span>`;
    box.hidden = true;
    document.body.appendChild(box);

    // Centre it on the part of the receipt column you can see, wherever you've scrolled.
    const place = () => {
      const r = column.getBoundingClientRect();
      const top = Math.max(r.top, 0), bottom = Math.min(r.bottom, innerHeight);
      box.style.left = `${r.left + r.width / 2}px`;
      box.style.top = `${(bottom > top ? (top + bottom) / 2 : innerHeight / 2)}px`;
    };

    // It prints whenever you're waiting for a receipt:
    //  - a check is running ("Check", "Check again", or the price you typed);
    //  - you clicked a seller in "Where to buy" (after their photo has flown to the receipt);
    //  - you opened something from "Recently checked" and it takes more than a moment.
    const busy = ["checkBtn", "askBtn", "rRefresh"].map($).filter(Boolean);
    const result = $("result");
    let opening = false, openingSince = 0;
    let shown = false, showTimer = null, hideTimer = null;

    const show = () => {
      clearTimeout(hideTimer);
      shown = true;
      place();
      box.classList.remove("is-leaving");
      box.hidden = false;
      wrap.classList.add("is-loading");
    };
    const hide = () => {
      shown = false;
      wrap.classList.remove("is-loading");  // the receipt comes back into focus as the new one prints
      if (calm()) { box.hidden = true; return; }
      box.classList.add("is-leaving");
      hideTimer = setTimeout(() => { box.hidden = true; box.classList.remove("is-leaving"); }, 220);
    };
    const update = () => {
      const checking = busy.some((b) => b.disabled);
      const switching = result.classList.contains("is-switching");
      const wanted = checking || switching || opening;
      clearTimeout(showTimer);
      if (wanted && !shown) {
        // A check shows it at once; a seller waits for the photo's flight; a quick open never flashes it.
        const wait = checking ? 0 : switching ? 320 : 220;
        showTimer = setTimeout(show, wait);
      } else if (!wanted && shown) hide();
    };
    const watch = new MutationObserver(update);
    for (const b of busy) watch.observe(b, { attributes: true, attributeFilter: ["disabled"] });
    watch.observe(result, { attributes: true, attributeFilter: ["class"] });

    // "Recently checked": waiting from the click until the receipt shows the new product.
    $("watchList")?.addEventListener("click", (e) => {
      if (!e.target.closest("button")) return;
      opening = true; openingSince = Date.now(); update();
      setTimeout(() => { if (opening && Date.now() - openingSince >= 15000) { opening = false; update(); } }, 15000);
    });
    const done = () => { if (opening) { opening = false; update(); } };
    new MutationObserver(done).observe($("rTitle"), { childList: true, characterData: true, subtree: true });
    new MutationObserver(done).observe($("formMessage"), { childList: true });  // an error message
    new MutationObserver(done).observe(result, { attributes: true, attributeFilter: ["data-verdict"] });
    addEventListener("resize", () => { if (!box.hidden) place(); });
    addEventListener("scroll", () => { if (!box.hidden) place(); }, { passive: true });
  }

  // ---------- 4. Highlight Grid: one highlight glides behind the row under the cursor ----------
  // Its colour follows the row: green for real deals and the best pick, red for fake discounts,
  // amber for "similar, not the same", plain paper otherwise.
  function tintOf(li) {
    const v = li.querySelector("[data-verdict]")?.dataset.verdict;
    if (v === "real_deal" || li.classList.contains("is-best")) return "var(--real)";
    if (v === "fake_discount") return "var(--fake)";
    if (v === "fair" || v === "overpriced" || li.querySelector(".chip.alt")) return "var(--fair)";
    return "var(--ink)";
  }

  function glide(list) {
    if (!list) return;
    const host = list.parentElement;
    host.classList.add("glide-host");
    list.classList.add("glide");
    const glider = document.createElement("div");
    glider.className = "glider";
    glider.setAttribute("aria-hidden", "true");
    host.prepend(glider);
    let showing = false;

    const moveTo = (li) => {
      const r = li.getBoundingClientRect(), h = host.getBoundingClientRect();
      if (!r.width || !r.height) return;
      if (!showing) glider.classList.add("no-slide");  // first row: appear in place, don't fly in
      glider.style.transform = `translate(${r.left - h.left - host.clientLeft + host.scrollLeft}px, ${r.top - h.top - host.clientTop + host.scrollTop}px)`;
      glider.style.width = `${r.width}px`;
      glider.style.height = `${r.height}px`;
      glider.style.setProperty("--tint", tintOf(li));
      glider.style.opacity = "1";
      if (!showing) { glider.getBoundingClientRect(); glider.classList.remove("no-slide"); showing = true; }
    };
    const hide = () => { glider.style.opacity = "0"; showing = false; };
    const rowOf = (target) => {
      const li = target.closest?.("li");
      return li && li.parentElement === list ? li : null;
    };
    list.addEventListener("pointerover", (e) => { const li = rowOf(e.target); if (li) moveTo(li); });
    list.addEventListener("pointerleave", hide);
    list.addEventListener("focusin", (e) => { const li = rowOf(e.target); if (li) moveTo(li); });
    list.addEventListener("focusout", (e) => { if (!list.contains(e.relatedTarget)) hide(); });
    new MutationObserver(hide).observe(list, { childList: true });  // list re-drawn: start over
  }

  // ---------- 5. Line Hover Link ("swap"): the receipt's links; the line slides away as a new one slides in ----------
  // Seller names get a quiet cue instead (motion.css): the name steps aside for a small arrow.
  function lines() {
    for (const node of [$("rLink"), $("rRefresh"), $("rRemove")]) node?.classList.add("link-swap");
  }

  // ---------- 6. FAQ Accordion: "Price history" and the other folds open and close smoothly ----------
  function accordion(details) {
    const summary = details.querySelector(":scope > summary");
    if (!summary) return;
    const body = document.createElement("div");
    body.className = "fold-body";
    const inner = document.createElement("div");
    inner.className = "fold-inner";
    for (const child of [...details.children]) if (child !== summary) inner.appendChild(child);
    body.appendChild(inner);
    details.appendChild(body);
    details.classList.add("smooth");
    if (details.open) body.classList.add("is-open");

    let closing = null;
    // Once fully open, nothing is clipped (the chart's price tips can poke out).
    body.addEventListener("transitionend", () => body.classList.toggle("is-settled", body.classList.contains("is-open")));
    summary.addEventListener("click", (event) => {
      if (calm()) return;  // let the browser open/close it instantly
      event.preventDefault();
      if (!details.open) {
        clearTimeout(closing);
        details.open = true;
        body.getBoundingClientRect();  // start from closed
        body.classList.add("is-open");
      } else if (body.classList.contains("is-open")) {
        body.classList.remove("is-open", "is-settled");
        closing = setTimeout(() => { if (!body.classList.contains("is-open")) details.open = false; }, 320);
      }
    });
    // Opened or closed by the page itself (a new product, say): match it without animating.
    details.addEventListener("toggle", () => {
      if (!details.open) body.classList.remove("is-open", "is-settled");
      else if (!body.classList.contains("is-open")) requestAnimationFrame(() => body.classList.add("is-open"));
    });
  }

  // ---------- 7. "Where to buy" as a departure board ----------
  // When you switch products, the old sellers flip away like the panels of a station's
  // departure board, the new ones flip down into place one by one, and each price rolls
  // to its number like the till on the loader receipt.
  function board(list) {
    if (!list) return;
    const host = list.parentElement;
    const EASE_OUT = "cubic-bezier(0.2, 0.9, 0.25, 1)";

    const flipAway = (rows) => {
      if (!rows.length || list.hidden) return;
      const ghost = document.createElement("ol");
      ghost.className = "rank board-ghost";
      ghost.setAttribute("aria-hidden", "true");
      Object.assign(ghost.style, { top: `${list.offsetTop}px`, left: `${list.offsetLeft}px`, width: `${list.offsetWidth}px` });
      rows.slice(0, 6).forEach((row) => { row.classList.remove("enter", "is-picked"); ghost.appendChild(row); });
      host.appendChild(ghost);
      const runs = [...ghost.children].map((row, i) => row.animate([
        { transform: "perspective(900px) rotateX(0deg)", opacity: 1 },
        { transform: "perspective(900px) rotateX(78deg) translateY(-6px)", opacity: 0 },
      ], { duration: 240, delay: i * 35, easing: "cubic-bezier(0.55, 0, 1, 0.45)", fill: "both" }).finished);
      Promise.all(runs).catch(() => {}).then(() => ghost.remove());
    };

    const rollPrice = (row, index) => {
      const p = row.querySelector(".p");
      const text = p?.firstChild;
      if (!text || text.nodeType !== Node.TEXT_NODE || !/\d/.test(text.data)) return;
      const label = text.data;
      const holder = document.createElement("span");
      holder.className = "price-roll";
      holder.setAttribute("aria-label", label);
      let digitNo = 0;
      const runs = [];
      for (const ch of label) {
        if (!/\d/.test(ch)) { holder.append(Object.assign(document.createElement("span"), { textContent: ch, ariaHidden: "true" })); continue; }
        const reel = document.createElement("span");
        reel.className = "price-reel";
        reel.setAttribute("aria-hidden", "true");
        const strip = document.createElement("span");
        strip.innerHTML = [...Array(20).keys()].map((n) => n % 10).join("<br>");
        reel.appendChild(strip);
        holder.appendChild(reel);
        const land = 10 + Number(ch);  // the second time round, so every digit spins
        runs.push(strip.animate(
          [{ transform: "translateY(0)" }, { transform: `translateY(${(-land / 20) * 100}%)` }],
          { duration: 760, delay: 220 + index * 70 + digitNo * 60, easing: "cubic-bezier(0.15, 0.55, 0.25, 1)", fill: "both" },
        ).finished);
        digitNo += 1;
      }
      text.replaceWith(holder);
      // Afterwards, plain text again (so it reads, copies and wraps like before).
      Promise.all(runs).catch(() => {}).then(() => { if (holder.isConnected) holder.replaceWith(label); });
    };

    new MutationObserver((records) => {
      if (calm()) return;
      const added = records.flatMap((r) => [...r.addedNodes]).filter((n) => n.nodeType === 1 && n.classList.contains("enter"));
      if (!added.length) return;
      flipAway(records.flatMap((r) => [...r.removedNodes]).filter((n) => n.nodeType === 1 && n.tagName === "LI"));
      added.forEach(rollPrice);
    }).observe(list, { childList: true });
  }

  // ---------- 8. Scratch card: scratch the receipt's barcode with a ৳ coin for a surprise ----------
  // The barcode is drawn on a "foil" you scratch off; bits of foil flake away as you go. Once about
  // half is gone the rest dissolves, and "Click to avail the offer" pops in with a shine.
  // It stays revealed for the rest of the visit.
  function scratchCard() {
    const box = $("scratch"), foil = $("scratchFoil"), link = $("offerLink"), key = $("scratchKey");
    if (!box || !foil) return;
    const ctx = foil.getContext("2d");
    let drawnAt = "", scratched = false, revealed = false, last = null, moves = 0, travelled = 0;

    const colour = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#22201C";
    const paint = () => {
      const w = box.clientWidth, h = box.clientHeight, dpr = Math.min(devicePixelRatio || 1, 2);
      if (!w || !h || revealed) return;
      const sig = `${w}x${h}@${dpr}:${colour("--ink")}`;
      if (sig === drawnAt) return;
      if (scratched && drawnAt) return;  // don't repaint over a half-scratched card
      drawnAt = sig;
      foil.width = Math.round(w * dpr); foil.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.globalCompositeOperation = "source-over";
      ctx.fillStyle = colour("--slip"); ctx.fillRect(0, 0, w, h);
      // the barcode (same rhythm as the one printed on the receipt)
      ctx.fillStyle = colour("--ink");
      ctx.globalAlpha = 0.85;
      const bars = [[0, 2], [4, 1], [9, 3]];
      for (let x = 0; x < w; x += 14) for (const [o, bw] of bars) ctx.fillRect(x + o, 0, bw, h);
      ctx.globalAlpha = 1;
      // the label, on a little paper strip
      const label = "SCRATCH FOR A SURPRISE";
      ctx.font = "600 10px 'JetBrains Mono', ui-monospace, monospace";
      const tw = ctx.measureText(label).width;
      const lw = tw + 34, lh = 22, lx = (w - lw) / 2, ly = (h - lh) / 2;
      ctx.fillStyle = colour("--slip"); ctx.fillRect(lx, ly, lw, lh);
      ctx.strokeStyle = colour("--ink"); ctx.lineWidth = 1; ctx.strokeRect(lx + 0.5, ly + 0.5, lw - 1, lh - 1);
      ctx.fillStyle = "#E7B04A"; ctx.beginPath(); ctx.arc(lx + 12, h / 2, 4.5, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = colour("--ink"); ctx.textBaseline = "middle"; ctx.fillText(label, lx + 22, h / 2 + 0.5);
    };

    const flakes = (x, y) => {
      if (calm()) return;
      for (let k = 0; k < 2; k++) {
        const f = document.createElement("span");
        const size = 2 + Math.random() * 3;
        f.className = "flake";
        f.style.width = `${size}px`; f.style.height = `${size * (0.6 + Math.random() * 0.8)}px`;
        f.style.background = Math.random() < 0.6 ? colour("--ink") : colour("--muted");
        box.appendChild(f);
        const dx = (Math.random() - 0.5) * 40, dy = 26 + Math.random() * 40, spin = (Math.random() - 0.5) * 540;
        f.animate([
          { transform: `translate(${x}px, ${y}px) rotate(0deg)`, opacity: 1 },
          { transform: `translate(${x + dx * 0.6}px, ${y - 8}px) rotate(${spin * 0.4}deg)`, opacity: 1, offset: 0.25 },
          { transform: `translate(${x + dx}px, ${y + dy}px) rotate(${spin}deg)`, opacity: 0 },
        ], { duration: 650 + Math.random() * 350, easing: "cubic-bezier(0.3, 0.1, 0.6, 1)" }).finished.then(() => f.remove(), () => f.remove());
      }
    };

    const cleared = () => {
      const { data } = ctx.getImageData(0, 0, foil.width, foil.height);
      let clear = 0, total = 0;
      for (let i = 3; i < data.length; i += 4 * 6) { total += 1; if (data[i] < 128) clear += 1; }
      return clear / total;
    };

    const reveal = () => {
      if (revealed) return;
      revealed = true;
      box.classList.add("is-done");
      link.removeAttribute("tabindex"); link.removeAttribute("aria-hidden");
      if (calm()) { foil.style.opacity = "0"; return; }
      foil.animate([{ opacity: 1, filter: "blur(0px)", transform: "scale(1)" }, { opacity: 0, filter: "blur(3px)", transform: "scale(1.06)" }],
        { duration: 480, easing: "cubic-bezier(0.4, 0, 0.2, 1)", fill: "forwards" });
      // a little burst of sparkles from the middle
      for (let k = 0; k < 9; k++) {
        const s = document.createElement("span");
        s.className = "sparkle"; s.textContent = k % 3 ? "✦" : "৳"; s.setAttribute("aria-hidden", "true");
        box.appendChild(s);
        const a = (k / 9) * Math.PI * 2 + Math.random() * 0.4, r = 70 + Math.random() * 40;
        s.animate([
          { transform: "translate(-50%, -50%) scale(0.2)", opacity: 0 },
          { transform: `translate(calc(-50% + ${Math.cos(a) * r * 0.7}px), calc(-50% + ${Math.sin(a) * r * 0.35}px)) scale(1)`, opacity: 1, offset: 0.45 },
          { transform: `translate(calc(-50% + ${Math.cos(a) * r}px), calc(-50% + ${Math.sin(a) * r * 0.5 + 10}px)) scale(0.6)`, opacity: 0 },
        ], { duration: 900, delay: 120 + k * 18, easing: "cubic-bezier(0.2, 0.9, 0.3, 1)", fill: "both" }).finished.then(() => s.remove(), () => s.remove());
      }
    };

    const scratchTo = (x, y) => {
      ctx.globalCompositeOperation = "destination-out";
      ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.lineWidth = 26;
      ctx.beginPath();
      ctx.moveTo(last ? last.x : x, last ? last.y : y);
      ctx.lineTo(x, y);
      ctx.stroke();
      travelled += last ? Math.hypot(x - last.x, y - last.y) : 0;
      if (travelled > 12) { flakes(x, y); travelled = 0; }
      last = { x, y };
      moves += 1;
      if (moves % 6 === 0 && cleared() > 0.5) reveal();
    };
    const point = (e) => { const r = foil.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };

    foil.addEventListener("pointerdown", (e) => {
      if (revealed) return;
      paint();
      scratched = true; box.classList.add("is-started");
      foil.setPointerCapture(e.pointerId);
      last = null;
      const p = point(e); scratchTo(p.x, p.y);
    });
    foil.addEventListener("pointermove", (e) => {
      if (revealed || !foil.hasPointerCapture(e.pointerId)) return;
      const p = point(e); scratchTo(p.x, p.y);
    });
    const lift = () => { last = null; if (!revealed && scratched && cleared() > 0.5) reveal(); };
    foil.addEventListener("pointerup", lift);
    foil.addEventListener("pointercancel", lift);

    // Keyboard: scratches itself in a few quick zig-zags, then reveals.
    key.addEventListener("click", () => {
      if (revealed) { link.focus(); return; }
      paint(); scratched = true; box.classList.add("is-started");
      const w = box.clientWidth, h = box.clientHeight;
      const path = []; for (let i = 0; i <= 10; i++) path.push([(w * i) / 10, i % 2 ? h * 0.85 : h * 0.15]);
      let i = 0; last = null;
      const step = () => {
        if (i >= path.length || revealed) { reveal(); setTimeout(() => link.focus(), 300); return; }
        scratchTo(path[i][0], path[i][1]); i += 1;
        setTimeout(step, calm() ? 0 : 40);
      };
      step();
    });

    // Draw the foil whenever the receipt is shown or resized, and again if the theme changes.
    new ResizeObserver(paint).observe(box);
    new MutationObserver(() => { if (!scratched) { drawnAt = ""; paint(); } })
      .observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => { if (!scratched) { drawnAt = ""; paint(); } });
    document.fonts?.ready.then(() => { if (!scratched) { drawnAt = ""; paint(); } });
    paint();
  }

  function start() {
    for (const logo of document.querySelectorAll(".logo")) glitch(logo);
    themeSwitch();
    scratchCard();
    if ($("checkBtn")) roll($("checkBtn"));
    loader();
    for (const d of document.querySelectorAll("details.fold, details.unproven")) accordion(d);  // before glide: it moves lists
    for (const id of ["rBuyList", "rUnprovenList", "rAltList", "watchList", "watchMore"]) glide($(id));
    lines();
    board($("rBuyList"));
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
