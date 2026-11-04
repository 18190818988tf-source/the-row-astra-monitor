import manifest from "../../products.json" with { type: "json" };

const STATE_KEY = "monitor-state-v1";
const USER_AGENT = "Mozilla/5.0 (compatible; PersonalInventoryMonitor/2.0)";

function cleanUrl(url) {
  const parsed = new URL(url);
  parsed.search = "";
  parsed.hash = "";
  return parsed.toString().replace(/\/$/, "");
}

function productEndpoint(url) {
  return `${cleanUrl(url)}.js`;
}

async function fetchText(url, cache) {
  if (!cache.has(url)) {
    cache.set(url, fetch(url, {
      headers: { "User-Agent": USER_AGENT, Accept: "text/html", "Cache-Control": "no-store" },
    }).then(async (response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status} for ${new URL(url).hostname}`);
      return response.text();
    }));
  }
  return cache.get(url);
}

async function fetchJson(url, cache) {
  if (!cache.has(url)) {
    cache.set(url, fetch(url, {
      headers: { "User-Agent": USER_AGENT, Accept: "application/json", "Cache-Control": "no-store" },
    }).then(async (response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status} for ${new URL(url).hostname}`);
      return response.json();
    }));
  }
  return cache.get(url);
}

export function searchProductUrls(searchUrl, html, excluded = []) {
  const source = new URL(searchUrl);
  const blocked = new Set(excluded.map((value) => String(value).trim().toLowerCase()));
  const found = new Set();
  const hrefPattern = /<a\b[^>]*\bhref\s*=\s*["']([^"']+)["'][^>]*>/gi;
  for (const match of html.matchAll(hrefPattern)) {
    let parsed;
    try { parsed = new URL(match[1], searchUrl); } catch { continue; }
    const parts = parsed.pathname.split("/").filter(Boolean);
    if (parsed.hostname !== source.hostname || parts.length !== 2 || parts[0] !== "products") continue;
    if (blocked.has(parts[1].toLowerCase())) continue;
    found.add(`${source.protocol}//${source.host}/products/${parts[1]}`);
  }
  return [...found];
}

export function expandShopifyProduct(source, productUrl, data) {
  const handle = new URL(productUrl).pathname.split("/").filter(Boolean).at(-1);
  if (!data || data.handle !== handle || !Array.isArray(data.variants)) throw new Error("Invalid Shopify product");
  return data.variants.filter((variant) => variant && variant.id != null).map((variant) => ({
    id: `${source.id}:${handle}:${variant.id}`,
    brand: source.brand,
    name: String(data.title || source.name),
    url: `${productUrl}?variant=${variant.id}`,
    adapter: "shopify",
    variant_id: String(variant.id),
    sku: String(variant.sku || "").trim(),
    color: String(variant.option1 || "").toLowerCase() === "default title" ? "" : String(variant.option1 || ""),
    size: String(variant.option2 || ""),
    available: variant.available,
  }));
}

export function evaluateShopify(item) {
  if (typeof item.available !== "boolean") return ["unknown", "Variant availability missing"];
  return [item.available ? "in_stock" : "out_of_stock",
    `Official Shopify JSON ${item.sku ? `SKU ${item.sku}` : `variant ${item.variant_id}`} available=${item.available}`];
}

export function parseJsonLdVariant(source, html) {
  const scripts = html.match(/<script\b[^>]*>[\s\S]*?<\/script>/gi) || [];
  const groups = [];
  for (const script of scripts) {
    const opening = script.slice(0, script.indexOf(">") + 1);
    if (!/\btype\s*=\s*["']application\/ld\+json["']/i.test(opening)) continue;
    const raw = script.slice(script.indexOf(">") + 1, script.toLowerCase().lastIndexOf("</script>"));
    try {
      const doc = JSON.parse(raw);
      for (const node of (Array.isArray(doc) ? doc : [doc])) {
        if (node?.["@type"] === "ProductGroup" && String(node.productGroupID) === source.product_group_id) groups.push(node);
      }
    } catch { /* Ignore unrelated malformed structured data. */ }
  }
  const variants = groups.flatMap((group) => Array.isArray(group.hasVariant) ? group.hasVariant : []);
  const matches = variants.filter((variant) => String(variant?.sku || "").toUpperCase() === source.sku.toUpperCase());
  if (matches.length !== 1) return ["unknown", `Expected 1 matching JSON-LD SKU, got ${matches.length}`];
  const variant = matches[0];
  if (String(variant.size || "").toLowerCase() !== source.size.toLowerCase()) return ["unknown", "JSON-LD size mismatch"];
  if (source.color && String(variant.color || "").toLowerCase() !== source.color.toLowerCase()) return ["unknown", "JSON-LD color mismatch"];
  const availability = String(variant.offers?.availability || "").split("/").at(-1);
  if (["InStock", "LimitedAvailability"].includes(availability)) return ["in_stock", `Official JSON-LD SKU ${source.sku} availability=${availability}`];
  if (availability === "OutOfStock") return ["out_of_stock", `Official JSON-LD SKU ${source.sku} availability=OutOfStock`];
  return ["unknown", `Unrecognized JSON-LD availability=${availability || "missing"}`];
}

export function parseCatalog(pageUrl, html) {
  const script = (html.match(/<script\b[^>]*\bid\s*=\s*["']__NEXT_DATA__["'][^>]*>[\s\S]*?<\/script>/i) || [])[0];
  if (!script) throw new Error("Catalog Next.js data missing");
  const raw = script.slice(script.indexOf(">") + 1, script.toLowerCase().lastIndexOf("</script>"));
  const products = JSON.parse(raw)?.props?.pageProps?.initialProductList;
  if (!Array.isArray(products) || !products.length) throw new Error("Catalog list empty");
  const snapshot = {};
  for (const product of products) {
    const slug = String(product?.url || product?.slug || "").replace(/^\/+|\/+$/g, "");
    const name = String(product?.name || product?.marketingName || "").trim();
    if (!product?.id || !slug || !name || typeof product.price !== "number") continue;
    const normalized = slug.replace(/^us\/en\/shop\//, "");
    snapshot[slug.toLowerCase()] = {
      id: String(product.id), name,
      url: new URL(`/us/en/shop/${normalized}`, pageUrl).toString(),
      price: product.price,
      discount_price: typeof product.discountPrice === "number" ? product.discountPrice : product.price,
    };
  }
  if (!Object.keys(snapshot).length) throw new Error("Catalog contained no products");
  return snapshot;
}

export function compareCatalog(previous, current, threshold = 5) {
  if (!previous || !Object.keys(previous).length) return { newKeys: [], priceChanges: [] };
  const newKeys = Object.keys(current).filter((key) => !(key in previous)).sort();
  const priceChanges = Object.keys(current).filter((key) => key in previous &&
    (current[key].price !== previous[key].price || current[key].discount_price !== previous[key].discount_price))
    .sort().map((key) => ({ before: previous[key], after: current[key] }));
  return { newKeys: newKeys.length >= threshold ? newKeys : [], priceChanges };
}

async function sendBark(env, title, body, url, test = false) {
  if (!env.BARK_PUSH_URL || !/^https:\/\//.test(env.BARK_PUSH_URL)) throw new Error("BARK_PUSH_URL missing or invalid");
  const response = await fetch(env.BARK_PUSH_URL.replace(/\/$/, ""), {
    method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ title, body, group: "MultiBrandStockMonitor", url,
      level: test ? "active" : "timeSensitive", sound: test ? "minuet" : "alarm" }),
  });
  const result = await response.json();
  if (!response.ok || String(result.code) !== "200") throw new Error("Bark rejected notification");
}

function transition(item, previous, status, proof, now) {
  const next = { ...(previous || { last_reliable: null, notified_in_stock: false, unknown_streak: 0 }) };
  if (status === "unknown") { next.unknown_streak = Math.min(3, (next.unknown_streak || 0) + 1); return [next, false]; }
  next.unknown_streak = 0;
  if (status === "out_of_stock") { next.last_reliable = status; next.notified_in_stock = false; return [next, false]; }
  next.last_reliable = status;
  if (next.notified_in_stock) return [next, false];
  return [next, { title: `补货提醒：${item.brand} ${item.name}`,
    body: `商品标识: ${item.sku || item.variant_id || "未指定"}\n颜色/款式: ${item.color || "未指定"}\n尺码: ${item.size || "未指定"}\n时间(UTC): ${now}\n${proof}\n点击查看官网；未验证最终结账`, url: item.url }];
}

export async function runMonitor(env) {
  const now = new Date().toISOString();
  const previous = await env.MONITOR_STATE.get(STATE_KEY, "json");
  const firstRun = !previous;
  const state = previous || { schema_version: 1, products: {}, catalogs: {} };
  const textCache = new Map();
  const jsonCache = new Map();
  const items = [];
  const summary = { started_utc: now, products_checked: 0, unknown: 0, notifications: 0, catalog_items: 0, errors: [] };

  for (const source of manifest.products.filter((item) => item.enabled !== false)) {
    try {
      if (source.adapter === "shopify_search") {
        const html = await fetchText(source.url, textCache);
        const urls = searchProductUrls(source.url, html, source.exclude_handles || []);
        if (!urls.length) throw new Error("Shopify search returned no products");
        for (const url of urls) {
          try {
            items.push(...expandShopifyProduct(source, url, await fetchJson(productEndpoint(url), jsonCache)));
          } catch (error) {
            summary.errors.push(`${source.id}:${new URL(url).pathname}:${error.message}`);
          }
        }
      } else if (source.adapter === "jsonld_product") {
        const html = await fetchText(cleanUrl(source.url), textCache);
        const [status, proof] = parseJsonLdVariant(source, html);
        items.push({ ...source, status, proof });
      } else if (source.adapter === "arcteryx_catalog") {
        const snapshot = {};
        for (const url of source.catalog_urls) Object.assign(snapshot, parseCatalog(url, await fetchText(url, textCache)));
        const prior = state.catalogs?.[source.id]?.items || {};
        const changes = compareCatalog(prior, snapshot, source.bulk_threshold || 5);
        summary.catalog_items = Object.keys(snapshot).length;
        if (!firstRun && (changes.newKeys.length || changes.priceChanges.length)) {
          const lines = [];
          if (changes.newKeys.length) lines.push(`批量新增/重新上架: ${changes.newKeys.length} 件`,
            ...changes.newKeys.slice(0, 10).map((key) => `- ${snapshot[key].name}`));
          if (changes.priceChanges.length) lines.push(`折扣变化: ${changes.priceChanges.length} 件`,
            ...changes.priceChanges.slice(0, 10).map(({ before, after }) => `- ${after.name}: $${before.discount_price} → $${after.discount_price}`));
          await sendBark(env, "Arc'teryx Outlet 目录变化", lines.join("\n"), source.url);
          summary.notifications += 1;
        }
        state.catalogs ||= {};
        state.catalogs[source.id] = { items: snapshot, updated_utc: now };
      }
    } catch (error) {
      summary.errors.push(`${source.id}:${error.message}`);
      console.error(source.id, error);
    }
  }

  for (const item of items) {
    let status = item.status;
    let proof = item.proof;
    if (item.adapter === "shopify") [status, proof] = evaluateShopify(item);
    summary.products_checked += 1;
    if (status === "unknown") summary.unknown += 1;
    const oldState = state.products[item.id];
    if (firstRun) {
      state.products[item.id] = { last_reliable: status === "unknown" ? null : status,
        notified_in_stock: status === "in_stock", unknown_streak: status === "unknown" ? 1 : 0 };
      continue;
    }
    const [next, notification] = transition(item, oldState, status, proof, now);
    if (notification) {
      await sendBark(env, notification.title, notification.body, notification.url);
      next.notified_in_stock = true;
      next.last_notified_utc = now;
      summary.notifications += 1;
    }
    state.products[item.id] = next;
  }

  state.last_run = { ...summary, completed_utc: new Date().toISOString(), ok: summary.errors.length === 0 && summary.unknown < summary.products_checked };
  const nextJson = JSON.stringify(state);
  if (!previous || nextJson !== JSON.stringify(previous)) await env.MONITOR_STATE.put(STATE_KEY, nextJson);
  console.log(JSON.stringify(state.last_run));
  return state.last_run;
}

export default {
  async scheduled(_controller, env, ctx) { ctx.waitUntil(runMonitor(env)); },
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/health") {
      const state = await env.MONITOR_STATE.get(STATE_KEY, "json");
      return Response.json(state?.last_run || { ok: false, message: "Baseline not initialized" });
    }
    return new Response("Multi-brand stock monitor is running. See /health", { status: 200 });
  },
};
