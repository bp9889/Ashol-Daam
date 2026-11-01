"use strict";

const $ = (id) => document.getElementById(id);

const VERDICT_LABEL = {
  real_deal: "Real deal",
  fair: "Normal price",
  fake_discount: "Fake discount",
  overpriced: "Cheaper elsewhere",
  unconfirmed: "Can't confirm yet",
};
const SHORT_LABEL = { real_deal: "Real", fair: "Normal", fake_discount: "Fake", overpriced: "Cheaper elsewhere", unconfirmed: "Unsure" };
const SYMBOL = { BDT: "৳", PKR: "Rs ", LKR: "Rs ", NPR: "Rs " };
const BUY_SHOWN = 3;
const reduceMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

let products = [];
let current = null;
let status = { alerts_enabled: false, scheduler: { enabled: false } };
let filter = "all";
let showAllSellers = false;

// ---------- helpers ----------

function money(value, currency = "BDT") {
  if (value == null) return "–";
  return (SYMBOL[currency] ?? currency + " ") + Math.round(value).toLocaleString("en-IN");
}

function plural(n, word) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

function timeAgo(iso) {
  if (!iso) return "";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 2) return "Checked just now";
  if (mins < 60) return `Checked ${mins} minutes ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `Checked ${plural(hours, "hour")} ago`;
  return `Checked ${plural(Math.round(hours / 24), "day")} ago`;
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else node.setAttribute(k, v);
  }
  node.append(...children.filter((c) => c != null && c !== false));
  return node;
}

function svg(tag, attrs = {}) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

function firstLetter(text) {
  return ((text || "").match(/[A-Za-z\u0980-\u09FF]/) || ["?"])[0].toUpperCase();
}

// A square photo tile. Images blend into the paper (see .tile img in the CSS).
function fillPhoto(box, imageUrl, title) {
  box.textContent = "";
  box.classList.toggle("empty-photo", !imageUrl);
  if (!imageUrl) { box.textContent = firstLetter(title); return; }
  const img = new Image();
  img.alt = "";
  img.decoding = "async";
  img.loading = "lazy";
  img.referrerPolicy = "no-referrer";
  img.onerror = () => { box.textContent = firstLetter(title); box.classList.add("empty-photo"); };
  img.src = imageUrl;
  box.appendChild(img);
}

function tile(imageUrl, title) {
  const box = el("span", { class: "tile", "aria-hidden": "true" });
  fillPhoto(box, imageUrl, title);
  return box;
}

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(typeof body.detail === "string" ? body.detail : "Something went wrong. Try again.");
    error.body = body;
    throw error;
  }
  return body;
}

// ---------- header ----------

function showCountdown() {
  const now = new Date();
  let sale = new Date(now.getFullYear(), 10, 11); // 11 November, local time
  const end = new Date(sale.getTime() + 864e5);
  if (now >= end) sale = new Date(now.getFullYear() + 1, 10, 11);
  const days = Math.ceil((sale - now) / 864e5);
  const box = $("countdown");
  if (now >= sale && now < end) box.textContent = "11.11 sale is on today";
  else if (days <= 45) box.textContent = `11.11 sale in ${plural(days, "day")}`;
  else return;
  box.hidden = false;
}

function showToday() {
  $("today").textContent = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric" }).format(new Date());
}

function setupTheme() {
  $("themeToggle").addEventListener("click", () => {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("asol-theme", root.dataset.theme); } catch (e) {}
    if (current && $("rHistory").open) drawChart(current);
  });
}

// ---------- recently checked ----------

function visibleProducts() {
  if (filter === "all") return products;
  const list = products.filter((p) => p.verdict.verdict === filter);
  const score = filter === "real_deal"
    ? (p) => p.verdict.real_off_pct ?? 0
    : (p) => (p.verdict.claimed_off_pct ?? 0) - Math.max(p.verdict.real_off_pct ?? 0, 0);
  return [...list].sort((a, b) => score(b) - score(a));
}

function renderFilters() {
  for (const button of document.querySelectorAll(".filters button")) {
    const key = button.dataset.filter;
    button.dataset.label ??= button.textContent.trim();
    const count = key === "all" ? products.length : products.filter((p) => p.verdict.verdict === key).length;
    button.setAttribute("aria-pressed", String(key === filter));
    button.textContent = button.dataset.label;
    button.appendChild(el("span", { text: String(count) }));
  }
}

function renderList() {
  renderFilters();
  const list = $("watchList");
  list.textContent = "";
  const shown = visibleProducts();
  $("watchEmpty").hidden = products.length > 0;
  $("filterEmpty").hidden = !(products.length && !shown.length);
  $("filterEmpty").textContent = filter === "real_deal"
    ? "No real deals right now. Prices usually drop during big sales like 11.11."
    : "No fake discounts spotted right now.";

  for (const p of shown) {
    const title = el("span", { class: "recent-title", text: p.title }, p.is_demo ? el("small", { text: "Sample" }) : null);
    const button = el("button", { type: "button" },
      tile(p.image_url, p.title), title,
      el("span", { class: "flag", "data-verdict": p.verdict.verdict, text: SHORT_LABEL[p.verdict.verdict] ?? "" }),
      el("span", { class: "recent-price", text: money(p.verdict.price, p.currency) }),
    );
    button.addEventListener("click", () => openProduct(p.id, true));
    const li = el("li", {}, button);
    if (current && current.id === p.id) li.setAttribute("aria-current", "true");
    list.appendChild(li);
  }
}

function setupFilters() {
  for (const button of document.querySelectorAll(".filters button")) {
    button.addEventListener("click", () => { filter = button.dataset.filter; renderList(); });
  }
}

async function loadList() {
  products = await api("/api/products");
  renderList();
}

// ---------- result ----------

// Shown elsewhere already (the "Compared with…" line and the price history section).
const HIDDEN_REASONS = /^(We've checked this product|We couldn't find other sellers|\d+ other sellers on Daraz sell it)/;

// The badge already says "Fake discount", so don't start the headline with it too.
function headlineWithoutLabel(headline, verdict) {
  const label = VERDICT_LABEL[verdict];
  const text = label && headline.startsWith(label + ". ") ? headline.slice(label.length + 2) : headline;
  return text.charAt(0).toUpperCase() + text.slice(1);
}

// ---------- step two: sellers' pages (sizes, sale prices, delivery fees) ----------
// The verdict comes back in seconds; "Where to buy" and the delivery fee follow a moment later.
const detailsAsked = new Set();

function detailsPending(r) {
  return Boolean(r && !r.is_demo && r.market && !r.market.detailed && !detailsAsked.has(`done:${r.id}`));
}

async function loadDetails(r) {
  if (!detailsPending(r) || detailsAsked.has(r.id)) return;
  detailsAsked.add(r.id);
  $("rBuyLoading").hidden = false;
  try {
    const full = await api(`/api/products/${r.id}/details`, { method: "POST" });
    detailsAsked.add(`done:${r.id}`);
    if (current && current.id === r.id) {
      const y = window.scrollY;
      renderResult(full, { fresh: false });
      window.scrollTo(0, y);
    }
  } catch (err) {
    detailsAsked.add(`done:${r.id}`);  // keep the quick result; don't keep retrying
    if (current && current.id === r.id) renderNumbers(current);
  } finally {
    if (!current || current.id === r.id) $("rBuyLoading").hidden = true;
  }
}

function renderResult(r, { fresh = true } = {}) {
  current = r;
  showAllSellers = false;
  const v = r.verdict;
  const box = $("result");
  box.hidden = false;
  $("emptySlip").hidden = true;
  box.dataset.verdict = v.verdict;
  if (fresh && !reduceMotion()) {
    box.classList.remove("is-new");
    void box.offsetWidth;
    box.classList.add("is-new");
  }

  // Product
  fillPhoto($("rPhoto"), r.image_url, r.title);
  $("rTitle").textContent = r.title;
  $("rVariant").hidden = !r.variant;
  $("rVariant").textContent = r.variant ? `Size / option: ${r.variant}` : "";
  $("rRemove").hidden = r.is_demo;
  $("rSample").hidden = !r.is_demo;
  $("rLink").hidden = r.is_demo;
  $("rLink").href = r.url;
  $("rRefresh").hidden = r.is_demo;
  $("rChecked").textContent = r.is_demo ? "" : timeAgo(r.last_checked_at);

  // Verdict
  $("rBadge").textContent = VERDICT_LABEL[v.verdict] ?? v.verdict;
  $("rHeadline").textContent = headlineWithoutLabel(v.headline, v.verdict);
  $("rBasis").textContent = {
    history: v.tracked_days >= 1 ? `Compared with ${plural(v.tracked_days, "day")} of this product's own prices.`
      : "Compared with this product's earlier prices.",
    other_sellers: `Compared with ${plural(v.sellers, "other seller")} of the same product on Daraz` +
      (r.market?.low && r.market?.high && r.market.low !== r.market.high
        ? `, who charge ${money(r.market.low, r.currency)} to ${money(r.market.high, r.currency)}.` : "."),
    page: "We couldn't find other sellers of this exact product to compare with yet.",
  }[v.basis] ?? "";

  renderNumbers(r);

  const reasons = $("rReasons");
  reasons.textContent = "";
  // At most three reasons, most important first, so the receipt stays easy to read.
  for (const reason of v.reasons.filter((x) => !HIDDEN_REASONS.test(x)).slice(0, 3)) reasons.appendChild(el("li", { text: reason }));
  $("rWhy").hidden = !reasons.children.length;
  $("rFoot").textContent = `Checked by Asol Dam, ${new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" }).format(new Date(r.last_checked_at || Date.now()))}`;

  renderWhereToBuy(r);
  $("rBuyLoading").hidden = !(detailsPending(r) && detailsAsked.has(r.id));
  loadDetails(r);
  renderHistory(r);
  renderAlert(r);
  renderList();
}

function renderNumbers(r) {
  const v = r.verdict;
  const c = r.currency;

  $("nNow").textContent = money(v.price, c);
  // What you actually pay: price + this seller's delivery fee (when we've read it from the page).
  $("nNowSub").textContent = r.delivery > 0
    ? `+ ${money(r.delivery, c)} delivery, ${money(v.price + r.delivery, c)} in total`
    : r.delivery === 0 ? "Free delivery" : detailsPending(r) ? "Reading the delivery fee…" : "Delivery fee not shown";

  $("nClaim").textContent = v.claimed_off_pct ? `${Math.round(v.claimed_off_pct)}% off` : "No discount";
  $("nClaimSub").textContent = v.original_price ? `Old price shown: ${money(v.original_price, c)}`
    : "Daraz isn't showing a discount";

  const real = v.real_off_pct;
  const ref = money(v.usual_price, c);
  const where = v.basis === "history" ? "Its usual price" : "Other sellers charge";
  if (v.basis === "page" || real == null) {
    $("nReal").textContent = "?";
    $("nRealSub").textContent = "Can't tell yet";
  } else if (real >= 1) {
    $("nReal").textContent = `${Math.round(real)}%`;
    $("nRealSub").textContent = `${where}: about ${ref}`;
  } else if (real > -3) {
    $("nReal").textContent = "None";
    $("nRealSub").textContent = `That's the normal price (about ${ref})`;
  } else {
    $("nReal").textContent = "None";
    $("nRealSub").textContent = v.basis === "history" ? `It usually costs less: about ${ref}` : `Others charge less: about ${ref}`;
  }
}

// ---------- where to buy ----------

function factClass(text) {
  if (/^Poorly rated/.test(text)) return "warn";
  if (/^(No reviews|Only \d|Much cheaper)|overseas/i.test(text)) return "caution";
  return null;
}

function sellerRow(r, l, { best = false, rank = null } = {}) {
  const name = l.seller || "A seller";
  const nameNode = l.url && !r.is_demo
    ? el("a", { href: l.url, target: "_blank", rel: "noopener", title: l.title, text: name })
    : name;
  const who = el("div", { class: "who" },
    el("div", { class: "s" }, nameNode,
      best ? el("span", { class: "chip best", text: "Best pick" }) : null,
      l.is_this ? el("span", { class: "chip this", text: "You pasted this" }) : null),
    el("div", { class: "facts" },
      ...(l.notes || []).map((text) => el("span", factClass(text) ? { class: factClass(text), text } : { text }))),
  );
  const price = el("span", { class: "p", text: money(l.price, r.currency) },
    l.original_price && l.original_price > l.price ? el("s", { text: money(l.original_price, r.currency) }) : null,
    l.price_unconfirmed ? el("small", { class: "reg", text: "regular" }) : null,
    l.delivery > 0 ? el("small", { class: "fee", text: `+${money(l.delivery, r.currency)} delivery` }) : null);
  if (l.price_unconfirmed && l.url && !r.is_demo) {
    // We only know this size's regular price. One click checks it (you confirm or type the sale price).
    const button = el("button", { type: "button", class: "check-it mono", text: "Check its price" });
    button.addEventListener("click", () => checkOther(l.url));
    who.appendChild(button);
  }
  return el("li", best ? { class: "is-best" } : {},
    el("span", { class: "n", text: rank ? String(rank) : "–" }),
    tile(l.image || (l.is_this ? r.image_url : null), l.title || name),
    who, price);
}

function renderWhereToBuy(r) {
  const { ranked = [], unproven = [] } = r?.market?.where_to_buy ?? {};
  $("rBuyEmpty").textContent = !r
    ? "Paste a Daraz link to see the best sellers for that product."
    : ranked.length ? "" : unproven.length
      ? "No seller has enough reviews to recommend yet."
      : "We couldn't find other sellers of this exact product.";

  const list = $("rBuyList");
  list.textContent = "";
  ranked.forEach((l, i) => {
    if (showAllSellers || i < BUY_SHOWN || l.is_this) list.appendChild(sellerRow(r, l, { best: i === 0, rank: i + 1 }));
  });
  list.hidden = !ranked.length;

  const hiddenCount = ranked.length - list.children.length;
  const more = $("rBuyMore");
  more.hidden = hiddenCount <= 0;
  more.textContent = `Show ${plural(hiddenCount, "more seller")}`;

  const fold = $("rUnproven");
  const ulist = $("rUnprovenList");
  ulist.textContent = "";
  unproven.forEach((l) => ulist.appendChild(sellerRow(r, l)));
  fold.hidden = !unproven.length;
  fold.open = !ranked.length;
  $("rUnprovenSummary").textContent = `Not enough reviews yet (${unproven.length})`;
}

// ---------- price history ----------

function renderHistory(r) {
  const v = r.verdict;
  const enough = r.history.length >= 2;
  $("rChartWrap").hidden = !enough;
  $("rHistoryNote").textContent = enough
    ? `${plural(r.history.length, "check")} over ${plural(Math.max(v.tracked_days, 1), "day")}.`
    : "We've checked this product once so far. The chart starts after the next check. Prices are checked twice a day.";
  $("keyUsual").hidden = v.basis !== "history";
  $("sLow").textContent = money(v.lowest, r.currency);
  $("sUsual").textContent = money(v.basis === "history" ? v.usual_price : null, r.currency);
  $("sHigh").textContent = money(v.highest, r.currency);
  if (enough && $("rHistory").open) drawChart(r);
}

function niceStep(raw) {
  const power = 10 ** Math.floor(Math.log10(raw));
  const unit = raw / power;
  return (unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 2.5 ? 2.5 : unit <= 5 ? 5 : 10) * power;
}

function drawChart(r) {
  const box = $("rChart");
  box.textContent = "";
  const data = r.history.map((h) => ({ t: new Date(h.at).getTime(), price: h.price, original: h.original }));
  if (data.length < 2 || !box.clientWidth) return;

  const W = box.clientWidth, H = box.clientHeight || 240;
  const m = { top: 10, right: 8, bottom: 26, left: 54 };
  const iw = W - m.left - m.right, ih = H - m.top - m.bottom;
  const values = data.flatMap((d) => [d.price, d.original].filter(Boolean));
  let lo = Math.min(...values), hi = Math.max(...values);
  const step = niceStep(((hi - lo) || hi * 0.2) / 4);
  lo = Math.max(0, Math.floor(lo / step) * step);
  hi = Math.max(Math.ceil(hi / step) * step, lo + step);

  const t0 = data[0].t, t1 = data.at(-1).t;
  const x = (t) => m.left + (t1 === t0 ? iw / 2 : ((t - t0) / (t1 - t0)) * iw);
  const y = (v) => m.top + ih - ((v - lo) / (hi - lo)) * ih;

  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": `Price history: from ${money(data[0].price, r.currency)} to ${money(data.at(-1).price, r.currency)}` });

  for (let v = lo; v <= hi + step / 2; v += step) {
    root.appendChild(svg("line", { class: "grid", x1: m.left, x2: W - m.right, y1: y(v), y2: y(v) }));
    const label = svg("text", { x: m.left - 8, y: y(v) + 4, "text-anchor": "end" });
    label.textContent = money(v, r.currency);
    root.appendChild(label);
  }
  const fmt = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });
  for (let i = 0; i < 4; i++) {
    const t = t0 + ((t1 - t0) * i) / 3;
    const label = svg("text", { x: x(t), y: H - 6, "text-anchor": i === 0 ? "start" : i === 3 ? "end" : "middle" });
    label.textContent = fmt.format(t);
    root.appendChild(label);
  }

  const v = r.verdict;
  if (v.basis === "history" && v.usual_price) {
    root.appendChild(svg("rect", { class: "band", x: m.left, width: iw, y: y(v.usual_price) - 4, height: 8, rx: 2 }));
  }
  let d = "";
  data.forEach((p, i) => { d += i ? `H${x(p.t)}V${y(p.price)}` : `M${x(p.t)},${y(p.price)}`; });
  root.appendChild(svg("path", { class: "area", d: `${d}V${m.top + ih}H${x(t0)}Z` }));
  let old = "", on = false;
  data.forEach((p) => {
    if (p.original) { old += on ? `H${x(p.t)}V${y(p.original)}` : `M${x(p.t)},${y(p.original)}`; on = true; } else on = false;
  });
  if (old) root.appendChild(svg("path", { class: "old", d: old }));
  root.appendChild(svg("path", { class: "line", d }));
  root.appendChild(svg("circle", { class: "dot", cx: x(t1), cy: y(data.at(-1).price), r: 5 }));

  const hover = svg("line", { class: "hover-line", y1: m.top, y2: m.top + ih, visibility: "hidden" });
  root.appendChild(hover);
  box.appendChild(root);
  const tip = el("div", { class: "chart-tip" });
  tip.hidden = true;
  box.appendChild(tip);

  const dayFmt = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short" });
  const move = (event) => {
    const rect = root.getBoundingClientRect();
    const px = ((event.clientX - rect.left) / rect.width) * W;
    const p = data.reduce((a, b) => (Math.abs(x(b.t) - px) < Math.abs(x(a.t) - px) ? b : a));
    hover.setAttribute("x1", x(p.t)); hover.setAttribute("x2", x(p.t)); hover.setAttribute("visibility", "visible");
    tip.hidden = false;
    tip.textContent = "";
    tip.append(el("strong", { text: money(p.price, r.currency) }), dayFmt.format(p.t));
    tip.style.left = `${Math.min(Math.max((x(p.t) / W) * rect.width, 70), rect.width - 70)}px`;
    tip.style.top = `${(y(p.price) / H) * rect.height}px`;
  };
  root.addEventListener("pointermove", move);
  root.addEventListener("pointerdown", move);
  root.addEventListener("pointerleave", () => { hover.setAttribute("visibility", "hidden"); tip.hidden = true; });
}

// ---------- alerts ----------

function renderAlert(r) {
  $("rAlert").hidden = r.is_demo || !status.alerts_enabled;
  $("alertForm").hidden = false;
  $("alertDone").hidden = true;
  $("alertMessage").textContent = "";
  $("alertPrice").value = "";
  $("alertPrice").placeholder = r.verdict.price ? String(Math.round((r.verdict.price * 0.9) / 10) * 10) : "";
}

function setupAlerts() {
  $("alertForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!current) return;
    const raw = $("alertPrice").value.trim();
    const target = raw ? Number(raw) : null;
    const message = $("alertMessage");
    message.classList.remove("is-error");
    if (raw && !(target > 0)) {
      message.textContent = "Enter a price in taka, like 2250, or leave it empty.";
      message.classList.add("is-error");
      return;
    }
    const button = $("alertBtn");
    button.disabled = true;
    button.textContent = "Setting alert…";
    try {
      const body = await api(`/api/products/${current.id}/alerts`, { method: "POST", body: JSON.stringify({ target_price: target }) });
      $("alertLink").href = body.link;
      $("alertForm").hidden = true;
      $("alertDone").hidden = false;
      message.textContent = target
        ? `You'll get a message when it's ${money(target, current.currency)} or less.`
        : `You'll get a message when it drops 5% or more below ${money(body.baseline_price, current.currency)}.`;
    } catch (err) {
      message.textContent = err.message;
      message.classList.add("is-error");
    } finally {
      button.disabled = false;
      button.textContent = "Set alert";
    }
  });
}

// ---------- schedule line ----------

function clockTime(hhmm) {
  const [h, mm] = hhmm.split(":").map(Number);
  return `${h % 12 || 12}${mm ? ":" + String(mm).padStart(2, "0") : ""} ${h < 12 ? "AM" : "PM"}`;
}

function describeSchedule() {
  const s = status.scheduler || {};
  const times = (status.check_times || []).map(clockTime);
  $("scheduleShort").textContent = s.enabled && times.length
    ? `Checks ${times.join(" & ")}`
    : "";
}

async function loadStatus() {
  try { status = await api("/api/status"); } catch (e) { return; }
  describeSchedule();
}

// ---------- opening, checking ----------

async function openProduct(id, scroll = false) {
  try {
    renderResult(await api(`/api/products/${id}`));
    history.replaceState(null, "", `#p=${id}`);
    if (scroll) $("result").scrollIntoView({ behavior: reduceMotion() ? "auto" : "smooth" });
  } catch (err) {
    showMessage(err.message, true);
  }
}

function showMessage(text, isError = false) {
  $("formMessage").textContent = text;
  $("formMessage").classList.toggle("is-error", isError);
}

// Daraz's page shows each size's regular price, but not whether a sale price is running.
// Then we ask: one click if the listed price is right, or type the sale price you see.
let pendingUrl = null;
let pendingListed = null;

function askForPrice(url, body) {
  pendingUrl = url;
  pendingListed = body.old_price || null;
  $("priceAskText").textContent = body.detail;
  $("askYes").hidden = !pendingListed;
  $("askYes").textContent = pendingListed ? `Yes, it's ${money(pendingListed)}` : "";
  $("priceAsk").querySelector(".ask-or").textContent = pendingListed
    ? "No, Daraz shows a lower sale price:" : "Price you see on Daraz:";
  $("priceAsk").hidden = false;
  $("askPrice").value = "";
  showMessage("");
  $("priceAsk").scrollIntoView({ behavior: reduceMotion() ? "auto" : "smooth", block: "center" });
  (pendingListed ? $("askYes") : $("askPrice")).focus({ preventScroll: true });
}

async function submitPrice(price, button) {
  const label = button.textContent;
  $("askYes").disabled = $("askBtn").disabled = true;
  button.textContent = "Checking…";
  try {
    await checkLink(pendingUrl, price);
  } catch (err) {
    $("priceAskText").textContent = err.message;
  } finally {
    $("askYes").disabled = $("askBtn").disabled = false;
    button.textContent = label;
  }
}

async function checkOther(url) {
  $("url").value = url;
  $("checkForm").scrollIntoView({ behavior: reduceMotion() ? "auto" : "smooth", block: "center" });
  $("checkForm").requestSubmit();
}

async function checkLink(url, price = null) {
  const r = await api("/api/track", { method: "POST", body: JSON.stringify(price ? { url, price } : { url }) });
  $("priceAsk").hidden = true;
  pendingUrl = null;
  pendingListed = null;
  showMessage("");
  $("url").value = "";
  await loadList();
  renderResult(r);
  history.replaceState(null, "", `#p=${r.id}`);
  $("result").scrollIntoView({ behavior: reduceMotion() ? "auto" : "smooth" });
}

function setupForm() {
  $("checkForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const url = $("url").value.trim();
    if (!url) { showMessage("Paste a Daraz product link first.", true); $("url").focus(); return; }
    if (!/daraz\./i.test(url)) {
      showMessage("That isn't a Daraz link. Copy the link from the Daraz app or website and paste it here.", true);
      $("url").focus();
      return;
    }
    const button = $("checkBtn");
    button.disabled = true;
    button.textContent = "Checking…";
    showMessage("Reading the price and comparing sellers on Daraz…");
    $("priceAsk").hidden = true;
    // Sizes' sale prices are read by opening sellers' pages, which takes a little longer.
    const slow = setTimeout(() => showMessage("Reading the price of your size from Daraz…"), 4000);
    try {
      await checkLink(url);
    } catch (err) {
      if (err.body?.need_price) askForPrice(url, err.body);
      else showMessage(err.message, true);
    } finally {
      clearTimeout(slow);
      button.disabled = false;
      button.textContent = "Check";
    }
  });

  $("priceAsk").addEventListener("submit", (event) => {
    event.preventDefault();
    const price = Number($("askPrice").value);
    if (!(price > 0) || !pendingUrl) { $("askPrice").focus(); return; }
    submitPrice(price, $("askBtn"));
  });
  $("askYes").addEventListener("click", () => {
    if (pendingUrl && pendingListed) submitPrice(pendingListed, $("askYes"));
  });

  $("rRemove").addEventListener("click", async () => {
    if (!current || current.is_demo) return;
    if (!confirm(`Remove “${current.title.slice(0, 60)}” from your list?`)) return;
    try {
      await api(`/api/products/${current.id}`, { method: "DELETE" });
      current = null;
      $("result").hidden = true;
      $("emptySlip").hidden = false;
      renderWhereToBuy(null);
      history.replaceState(null, "", location.pathname);
      await loadList();
    } catch (err) {
      $("rChecked").textContent = err.message;
    }
  });

  $("rRefresh").addEventListener("click", async () => {
    if (!current) return;
    const button = $("rRefresh");
    button.disabled = true;
    button.textContent = "Checking…";
    try {
      renderResult(await api(`/api/products/${current.id}/refresh`, { method: "POST" }), { fresh: false });
      await loadList();
    } catch (err) {
      if (err.body?.need_price) askForPrice(current.url, err.body);
      else $("rChecked").textContent = err.message;
    } finally {
      button.disabled = false;
      button.textContent = "Check again";
    }
  });

  $("rBuyMore").addEventListener("click", () => { showAllSellers = true; renderWhereToBuy(current); });
  $("rHistory").addEventListener("toggle", () => { if ($("rHistory").open && current) drawChart(current); });
}

async function start() {
  showCountdown();
  showToday();
  renderWhereToBuy(null);
  setupTheme();
  setupForm();
  setupFilters();
  setupAlerts();
  await loadStatus();
  setInterval(loadStatus, 5 * 60 * 1000);

  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => current && $("rHistory").open && drawChart(current), 150);
  });

  try {
    await loadList();
  } catch (err) {
    showMessage("Couldn't load products. Is the server running?", true);
    return;
  }
  const fromHash = Number((location.hash.match(/p=(\d+)/) || [])[1]);
  const first = products.find((p) => p.id === fromHash) ?? products.find((p) => !p.is_demo) ?? products[0];
  if (first) openProduct(first.id);
}

start();
