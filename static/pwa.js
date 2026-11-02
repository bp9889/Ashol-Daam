/* Asol Dam as an app: install button, "Share to Asol Dam" from the Daraz app, offline support. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const calm = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  const installed = () => matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;

  // ---------- 1. Shared from the Daraz app (Share → Asol Dam) ----------
  // Android sends the shared text and link as ?title=…&text=…&url=…; Daraz puts its short link
  // (s.daraz.com.bd/…) in the text. Find the link, skip the intro and check it straight away.
  const params = new URLSearchParams(location.search);
  const shared = ["url", "text", "title"].map((k) => params.get(k) || "").join(" ");
  const link = (shared.match(/https?:\/\/[^\s"'<>]*daraz\.[^\s"'<>]+/i) || [])[0];
  if (params.has("source") || link) history.replaceState(null, "", location.pathname + (link ? "#app" : location.hash));
  if (link) {
    const go = () => { $("url").value = link; $("checkForm").requestSubmit(); };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", go); else go();
  } else if (shared.trim() && $("formMessage")) {
    $("formMessage").textContent = "That share didn't include a Daraz link. In the Daraz app, open a product and tap Share.";
  }

  // ---------- 2. Offline: works without the internet, and says so ----------
  if ("serviceWorker" in navigator) {
    addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
  }
  const offlineNote = () => {
    document.body.classList.toggle("is-offline", !navigator.onLine);
    toast(navigator.onLine ? "Back online." : "You're offline. You can still open products you've checked.", navigator.onLine ? 2200 : 5000);
  };
  // The server can't be reached (no internet, or the local server is stopped): say so once.
  let savedNoted = 0;
  addEventListener("asol:saved", () => {
    if (Date.now() - savedNoted < 60000) return;
    savedNoted = Date.now();
    toast("No connection right now, so you're seeing saved copies. Prices update when it's back.", 5000);
  });
  addEventListener("online", offlineNote);
  addEventListener("offline", offlineNote);

  // ---------- 3. Install button ----------
  // The buttons always show until the app is installed. Chrome/Edge/Android may offer their own
  // install pop-up (sometimes only after you've used the site for a bit); when they have, the button
  // opens it. Otherwise (iPhone, or before Chrome is ready) it shows the exact taps for that phone.
  let offer = null;
  const buttons = [...document.querySelectorAll("[data-install]")];
  const ua = navigator.userAgent;
  const ios = /iphone|ipad|ipod/i.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const phone = ios || /android/i.test(ua);
  const show = (on) => buttons.forEach((b) => {
    if (on && b.hidden) {
      b.hidden = false;
      if (!calm()) b.animate([{ opacity: 0, transform: "translateY(-6px) scale(0.96)" }, { opacity: 1, transform: "none" }],
        { duration: 420, easing: "cubic-bezier(0.2, 0.9, 0.25, 1)" });
    } else if (!on) b.hidden = true;
  });
  addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); offer = e; });
  addEventListener("appinstalled", () => {
    offer = null; show(false); banner(false);
    toast("Installed! Find Asol Dam on your home screen. On Android, you can now Share from Daraz to Asol Dam.", 6000);
  });
  if (!installed()) show(true);

  for (const b of buttons) b.addEventListener("click", async () => {
    if (offer) {
      offer.prompt();
      const { outcome } = await offer.userChoice.catch(() => ({}));
      if (outcome === "accepted") { show(false); banner(false); }
      offer = null;
    } else {
      installHelp(b);
    }
  });

  // The taps differ by phone and browser; show the right ones.
  function steps() {
    if (ios && /CriOS|EdgiOS|FxiOS/.test(ua)) return ["Tap <b>Share</b> <span class='ih-icon'>⎋</span> in the address bar", "Choose <b>Add to Home Screen</b>", "Tap <b>Add</b>. Done!"];
    if (ios) return ["Tap <b>Share</b> <span class='ih-icon'>⎋</span> at the bottom of Safari", "Scroll down, choose <b>Add to Home Screen</b>", "Tap <b>Add</b>. Done!"];
    if (/SamsungBrowser/.test(ua)) return ["Tap the <b>menu ≡</b> at the bottom", "Choose <b>Add page to</b> → <b>Home screen</b>", "Tap <b>Add</b>. Done!"];
    if (/Firefox/.test(ua) && phone) return ["Tap the <b>menu ⋮</b>", "Choose <b>Install</b> (or <b>Add to Home screen</b>)", "Tap <b>Add</b>. Done!"];
    if (phone) return ["Tap Chrome's <b>menu ⋮</b> at the top right", "Choose <b>Install app</b> (or <b>Add to Home screen</b>)", "Tap <b>Install</b>. Done!"];
    if (/Firefox/.test(ua)) return ["Firefox on computers can't install sites as apps", "Open this page in <b>Chrome</b> or <b>Edge</b>", "Click <b>Install app</b> there"];
    return ["Click the <b>install icon</b> at the right end of the address bar", "Or open the browser <b>menu</b> → <b>Install Asol Dam</b>", "Click <b>Install</b>. Done!"];
  }

  function installHelp(from) {
    const card = $("installHelp");
    if (!card) return;
    card.querySelector("ol").innerHTML = steps().map((s) => `<li>${s}</li>`).join("");
    card.hidden = false;
    const r = from.getBoundingClientRect();
    const below = r.bottom + 10 + card.offsetHeight < innerHeight;
    card.style.top = `${below ? r.bottom + 10 : Math.max(10, r.top - card.offsetHeight - 10)}px`;
    card.style.left = `${Math.max(10, Math.min(r.right - card.offsetWidth, innerWidth - card.offsetWidth - 10))}px`;
    if (!calm()) card.animate([{ opacity: 0, transform: `translateY(${below ? -8 : 8}px) scale(0.97)` }, { opacity: 1, transform: "none" }],
      { duration: 280, easing: "cubic-bezier(0.2, 0.9, 0.25, 1)" });
    const close = (e) => {
      if (e && card.contains(e.target) && !e.target.closest("[data-close-help]")) return;
      card.hidden = true;
      removeEventListener("pointerdown", close, true);
    };
    setTimeout(() => addEventListener("pointerdown", close, true), 0);
    card.querySelector("[data-close-help]").onclick = () => close();
  }

  // ---------- 4. On phones: a "Get the app" bar slides up from the bottom ----------
  // Shown a few seconds after opening; × hides it for a week.
  const BANNER_KEY = "asol-app-banner-closed";
  function banner(on) {
    const bar = $("appBanner");
    if (!bar) return;
    if (!on) {
      if (bar.hidden) return;
      if (calm()) { bar.hidden = true; return; }
      bar.animate([{ transform: "none", opacity: 1 }, { transform: "translateY(110%)", opacity: 0 }],
        { duration: 260, easing: "cubic-bezier(0.4, 0, 1, 1)" }).finished.then(() => { bar.hidden = true; }, () => { bar.hidden = true; });
      return;
    }
    bar.hidden = false;
    if (!calm()) bar.animate([{ transform: "translateY(110%)", opacity: 0 }, { transform: "none", opacity: 1 }],
      { duration: 520, easing: "cubic-bezier(0.2, 0.9, 0.25, 1)" });
  }
  let closedAt = 0;
  try { closedAt = Number(localStorage.getItem(BANNER_KEY)) || 0; } catch (e) {}
  if (phone && !installed() && Date.now() - closedAt > 7 * 864e5) setTimeout(() => banner(true), 2500);
  $("appBannerClose")?.addEventListener("click", () => {
    banner(false);
    try { localStorage.setItem(BANNER_KEY, String(Date.now())); } catch (e) {}
  });

  // ---------- A small message that slides up from the bottom ----------
  let toastTimer = null;
  function toast(text, ms) {
    const t = $("toast");
    if (!t) return;
    t.textContent = text;
    t.hidden = false;
    t.classList.remove("is-leaving");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      t.classList.add("is-leaving");
      setTimeout(() => { t.hidden = true; t.classList.remove("is-leaving"); }, calm() ? 0 : 260);
    }, ms);
  }
})();
