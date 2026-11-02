/* Asol Dam: the intro (GSAP + ScrollTrigger).
   1. Arrival: each word of the logo rolls into place from its translation (Ashol → আসল, দাম → Dam, …),
      the slash stands up, and a red pen circles আসল ("real").
   2. Scroll: the big logo shrinks and glides into the header's logo spot as the checker comes up;
      when it lands, it hands over to the real header logo. Scrolling back up reverses it. */
(() => {
  "use strict";
  const intro = document.getElementById("intro");
  const mark = document.getElementById("introMark");
  const target = document.querySelector(".top .logo");
  const root = document.documentElement;
  if (!intro || !mark || !target) return;

  const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;

  const toApp = (smooth) => scrollTo({ top: intro.offsetHeight, behavior: smooth && !calm ? "smooth" : "auto" });

  // A shared product link (#p=…) goes straight to the checker.
  if (/(^#|&)(p=\d+|app)/.test(location.hash)) requestAnimationFrame(() => toApp(false));
  for (const link of intro.querySelectorAll('a[href="#app"]')) {
    link.addEventListener("click", (e) => { e.preventDefault(); toApp(true); });
  }

  const ready = () => root.classList.remove("intro-wait");
  if (calm || !window.gsap || !window.ScrollTrigger) { mark.dataset.ready = "1"; ready(); return; }  // a plain, still intro
  gsap.registerPlugin(ScrollTrigger);
  document.body.classList.add("has-intro");

  const words = [...mark.querySelectorAll(".w")];
  const froms = words.map((w) => w.querySelector(".w-from"));
  const tos = words.map((w) => w.querySelector(".w-to"));
  const pen = mark.querySelector(".intro-pen");
  const penPath = pen.querySelector("path");
  let penLength = 0;

  // The pen goes around the first word, আসল.
  const placePen = () => {
    const word = words[0];
    const w = word.offsetWidth, h = word.offsetHeight;
    let x = 0, y = 0;
    for (let node = word; node && node !== mark; node = node.offsetParent) { x += node.offsetLeft; y += node.offsetTop; }
    const W = w * 1.28, H = h * 1.12;
    Object.assign(pen.style, { left: `${x - w * 0.15}px`, top: `${y - h * 0.06}px`, width: `${W}px`, height: `${H}px` });
    // The loop is drawn in real pixels (no stretching), so the pen's line can be measured and drawn exactly.
    pen.setAttribute("viewBox", `0 0 ${W} ${H}`);
    const sx = W / 200, sy = H / 90;
    const pts = [[34, 60], [12, 44], [22, 18], [70, 10], [116, 2], [174, 12], [188, 36], [200, 58], [170, 76], [118, 80],
      [72, 84], [26, 76], [14, 56], [8, 44], [20, 32], [36, 26]].map(([px, py]) => [px * sx, py * sy]);
    const p = (i) => pts[i].map((n) => n.toFixed(1)).join(" ");
    penPath.setAttribute("d", `M${p(0)}C${p(1)} ${p(2)} ${p(3)}C${p(4)} ${p(5)} ${p(6)}C${p(7)} ${p(8)} ${p(9)}C${p(10)} ${p(11)} ${p(12)}C${p(13)} ${p(14)} ${p(15)}`);
    penLength = penPath.getTotalLength();
    penPath.style.strokeDasharray = `${penLength} ${penLength + 10}`;
  };

  // Line each "from" word up on the same baseline as the word it turns into (Bangla and Latin
  // letters sit differently), using tiny zero-size markers that sit on each baseline.
  const alignFroms = () => words.forEach((w, i) => {
    const probe = () => Object.assign(document.createElement("i"), { className: "baseline-probe" });
    const a = w.querySelector(":scope > .baseline-probe") || w.insertBefore(probe(), froms[i]);
    const b = froms[i].querySelector(".baseline-probe") || froms[i].appendChild(probe());
    froms[i].style.top = "0px";
    froms[i].style.top = `${a.offsetTop - b.offsetTop}px`;
  });

  // ---------- 1. Arrival ----------
  // Distances are measured from each word's own window (in pixels), so the old word always leaves
  // the window completely and the new one always comes in from fully below it, at any size.
  const below = (to) => to.parentElement.offsetHeight - to.offsetTop + 2;
  const above = (from) => -(from.offsetTop + from.offsetHeight + 2);
  gsap.set(penPath, { opacity: 0 });  // hidden until the pen touches the paper
  const arrive = gsap.timeline({ paused: true, delay: 0.1, defaults: { ease: "power3.inOut" } })
    .from(".mark-wrap", { autoAlpha: 0, y: 16, duration: 0.7, ease: "power2.out" }, 0)
    .to(froms, { y: (i, el) => above(el), duration: 0.8, stagger: 0.13 }, 0.45)
    .to(tos, { y: 0, duration: 0.8, stagger: 0.13 }, 0.45)
    // Each word's space changes from the old word's width to the new one's at the same time, so the
    // logo reads "Ashol দাম / আসল Dam" at first and smoothly rearranges into "আসল Dam / Ashol দাম".
    .to(words, { width: (i) => tos[i].offsetWidth, duration: 0.8, stagger: 0.13, clearProps: "width" }, 0.45)
    .call(() => { mark.dataset.ready = "1"; }, null, 1.4)  // from now on, hovering it scrambles it (motion.js)
    .from(".intro-kicker", { autoAlpha: 0, y: 8, duration: 0.6, ease: "power2.out" }, 0.9)
    .from(".intro-line, .intro-scroll", { autoAlpha: 0, y: 10, duration: 0.6, ease: "power2.out", stagger: 0.1 }, 1.05)
    .from(".intro-side > *", { autoAlpha: 0, y: 10, duration: 0.6, ease: "power2.out", stagger: 0.06 }, 1.2)
    .add(placePen, 1.3)
    // The pen: it touches down softly, speeds up round the loop and slows as it closes, pressing
    // a little harder in the middle of the stroke, like a real hand.
    .fromTo(penPath, { strokeDashoffset: () => penLength, strokeWidth: 1.2 },
      { strokeDashoffset: 0, duration: 1.25, ease: "power1.inOut", immediateRender: false }, 1.35)
    .to(penPath, { opacity: 1, duration: 0.18, ease: "power1.out" }, 1.35)
    .to(penPath, { strokeWidth: 2.8, duration: 0.6, ease: "sine.out" }, 1.4)
    .to(penPath, { strokeWidth: 2.4, duration: 0.6, ease: "sine.inOut" }, 2.0);
  // Start once the fonts are in (or after a second at most), so nothing shifts mid-roll.
  let started = false;
  const begin = () => {
    if (started) return;
    started = true;
    alignFroms();
    gsap.set(froms, { visibility: "visible", xPercent: -50, x: 0, y: 0 });
    gsap.set(tos, { y: (i, el) => below(el) });
    gsap.set(words, { width: (i) => froms[i].offsetWidth });
    ready();
    arrive.play();
  };
  (document.fonts ? Promise.race([document.fonts.ready, new Promise((r) => setTimeout(r, 1000))]) : Promise.resolve()).then(begin);

  // ---------- 2. Scroll: glide into the header ----------
  // Positions from the layout (offsets ignore transforms), so they stay right while anything moves.
  const pagePos = (el) => {
    let x = 0, y = 0;
    for (let node = el; node; node = node.offsetParent) { x += node.offsetLeft; y += node.offsetTop; }
    return { x, y };
  };
  const delta = () => {
    const from = pagePos(mark), to = pagePos(target);
    return { x: to.x - from.x, y: to.y - from.y, scale: target.offsetWidth / mark.offsetWidth };
  };

  gsap.to(mark, {
    x: () => delta().x,
    y: () => delta().y,
    scale: () => delta().scale,
    transformOrigin: "0 0",
    ease: "power1.inOut",
    scrollTrigger: { trigger: intro, start: "top top", end: "bottom top", scrub: 0.6, invalidateOnRefresh: true },
    onUpdate() { document.body.classList.toggle("logo-landed", this.progress() > 0.995); },
  });
  // Everything else in the intro steps back in the first part of the scroll.
  const stepBack = (targets, y) => gsap.to(targets, {
    autoAlpha: 0, y, ease: "none",
    scrollTrigger: { trigger: intro, start: "top top", end: "22% top", scrub: 0.3 },
  });
  stepBack(intro.querySelector(".intro-fade"), -24);              // "Daraz price check · Bangladesh"
  stepBack([...intro.querySelectorAll(".intro-fade")].slice(1), 28);  // the line and "Scroll"
  stepBack(intro.querySelectorAll(".intro-side"), 28);                // the side notes
  gsap.to(pen, {
    autoAlpha: 0, ease: "none",
    scrollTrigger: { trigger: intro, start: "top top", end: "25% top", scrub: 0.4 },
  });
  // The page's column lines slowly fade as the real columns arrive.
  gsap.to(".intro-guides", {
    autoAlpha: 0, ease: "none",
    scrollTrigger: { trigger: intro, start: "30% top", end: "bottom top", scrub: true },
  });

  // Fonts change the logo's size: measure again once they're in.
  document.fonts?.ready.then(() => { alignFroms(); placePen(); ScrollTrigger.refresh(); });
  addEventListener("resize", () => { if (arrive.progress() === 1) placePen(); });
})();
