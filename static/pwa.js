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
  // Chrome/Edge/Android offer installing; we keep that offer and show our own button.
  // iPhone/iPad (Safari) has no such offer, so the button explains Share → Add to Home Screen.
  let offer = null;
  const buttons = [...document.querySelectorAll("[data-install]")];
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const show = (on) => buttons.forEach((b) => {
    if (on && b.hidden) {
      b.hidden = false;
      if (!calm()) b.animate([{ opacity: 0, transform: "translateY(-6px) scale(0.96)" }, { opacity: 1, transform: "none" }],
        { duration: 420, easing: "cubic-bezier(0.2, 0.9, 0.25, 1)" });
    } else if (!on) b.hidden = true;
  });
  addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); offer = e; if (!installed()) show(true); });
  addEventListener("appinstalled", () => {
    offer = null; show(false);
    toast("Installed! Find Asol Dam on your home screen. On Android, you can now Share from Daraz to Asol Dam.", 6000);
  });
  if (ios && !installed()) show(true);

  for (const b of buttons) b.addEventListener("click", async () => {
    if (offer) {
      offer.prompt();
      const { outcome } = await offer.userChoice.catch(() => ({}));
      if (outcome === "accepted") show(false);
      offer = null;
    } else if (ios) {
      iosHelp(b);
    }
  });

  function iosHelp(from) {
    const card = $("installHelp");
    if (!card) return;
    card.hidden = false;
    const r = from.getBoundingClientRect();
    card.style.top = `${Math.min(r.bottom + 10, innerHeight - card.offsetHeight - 10)}px`;
    card.style.left = `${Math.max(10, Math.min(r.right - card.offsetWidth, innerWidth - card.offsetWidth - 10))}px`;
    if (!calm()) card.animate([{ opacity: 0, transform: "translateY(-8px) scale(0.97)" }, { opacity: 1, transform: "none" }],
      { duration: 280, easing: "cubic-bezier(0.2, 0.9, 0.25, 1)" });
    const close = (e) => {
      if (e && card.contains(e.target) && !e.target.closest("[data-close-help]")) return;
      card.hidden = true;
      removeEventListener("pointerdown", close, true);
    };
    setTimeout(() => addEventListener("pointerdown", close, true), 0);
    card.querySelector("[data-close-help]").onclick = () => close();
  }

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
