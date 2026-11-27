// Render a link page from the HTML template and one profile record from KV.
// Every value is HTML-escaped and links must be https or mailto, so a profile can never inject markup or script.

export const SLUG = /^[a-z0-9][a-z0-9-]{0,62}$/;
const COLOR = /^#[0-9a-fA-F]{6}$/;
const DEFAULT_ACCENT = "#2f6fe4";
const MAX_LINKS = 30;

export const HEADERS = {
  "Content-Type": "text/html; charset=utf-8",
  "Cache-Control": "public, max-age=60",
  "Content-Security-Policy":
    "default-src 'none'; style-src 'unsafe-inline'; img-src https: data:; base-uri 'none'; form-action 'none'; " +
    "frame-ancestors 'none'",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "strict-origin-when-cross-origin",
};

export function escapeHtml(value) {
  const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return String(value ?? "").replace(/[&<>"']/g, (c) => map[c]);
}

export function safeUrl(value, protocols = ["https:", "mailto:"]) {
  try {
    const url = new URL(String(value ?? ""));
    return protocols.includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

function initials(name) {
  const parts = String(name ?? "").trim().split(/\s+/).filter(Boolean);
  return parts.slice(0, 2).map((p) => [...p][0].toUpperCase()).join("") || "?";
}

export function render(template, profile, pageUrl) {
  const name = String(profile.name ?? "").slice(0, 80);
  const links = (Array.isArray(profile.links) ? profile.links : [])
    .slice(0, MAX_LINKS)
    .map((link) => {
      const url = safeUrl(link && link.url);
      if (!url) return "";
      const label = String((link && link.label) || url).slice(0, 80);
      return `<li><a class="link" href="${escapeHtml(url)}" rel="noopener">${escapeHtml(label)}</a></li>`;
    })
    .filter(Boolean)
    .join("\n      ");
  const avatar = safeUrl(profile.avatar, ["https:"]);
  const values = {
    TITLE: escapeHtml(String(profile.title || name).slice(0, 120)),
    NAME: escapeHtml(name),
    BIO: escapeHtml(String(profile.bio ?? "").slice(0, 300)),
    AVATAR: avatar
      ? `<img class="avatar" src="${escapeHtml(avatar)}" alt="" width="96" height="96">`
      : `<span class="avatar initials" aria-hidden="true">${escapeHtml(initials(name))}</span>`,
    ACCENT: COLOR.test(profile.accent ?? "") ? profile.accent : DEFAULT_ACCENT,
    LINKS: links,
    PAGE_URL: escapeHtml(pageUrl),
  };
  return template.replace(/\{\{([A-Z_]+)\}\}/g, (match, key) => (key in values ? values[key] : ""));
}

export async function handle(request, env, slug) {
  const notFound = () =>
    new Response("Not found", { status: 404, headers: { "Content-Type": "text/plain; charset=utf-8" } });
  if (!SLUG.test(slug ?? "")) return notFound();
  const raw = await env.PROFILES.get(slug);
  if (!raw) return notFound();
  let profile;
  try {
    profile = JSON.parse(raw);
  } catch {
    profile = null;
  }
  if (!profile || typeof profile !== "object" || Array.isArray(profile)) {
    return new Response("This profile cannot be read", { status: 500 });
  }
  const template = await loadTemplate(env, request.url);
  if (template === null) return new Response("The page template is missing", { status: 500 });
  return new Response(render(template, profile, new URL("/" + slug, request.url).href), { headers: HEADERS });
}

// Pages serves public/_templates/profile.html at /_templates/profile and redirects the .html address there.
async function loadTemplate(env, base) {
  let response = await env.ASSETS.fetch(new URL("/_templates/profile", base));
  const location = response.headers.get("Location");
  if (response.status >= 300 && response.status < 400 && location) {
    response = await env.ASSETS.fetch(new URL(location, base));
  }
  return response.ok ? response.text() : null;
}
