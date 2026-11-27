import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { escapeHtml, handle, render, safeUrl } from "../lib/render.js";

const template = await readFile(new URL("../public/_templates/profile.html", import.meta.url), "utf8");

function env(records) {
  return {
    PROFILES: { get: async (key) => records[key] ?? null },
    ASSETS: {
      // like Pages: the extensionless address serves the file, the .html one redirects there
      fetch: async (url) => (new URL(url).pathname === "/_templates/profile"
        ? new Response(template) : new Response(null, { status: 404 })),
    },
  };
}

test("renders a profile with its links", async () => {
  const profile = JSON.parse(await readFile(new URL("../profiles/jane-doe.json", import.meta.url), "utf8"));
  const response = await handle(new Request("https://links.example.com/jane-doe"), env({ "jane-doe": JSON.stringify(profile) }), "jane-doe");
  const html = await response.text();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("Content-Security-Policy"), /default-src 'none'/);
  assert.match(html, /<h1>Jane Doe<\/h1>/);
  assert.match(html, /<a class="link" href="https:\/\/example.com\/shop" rel="noopener">Shop: prints and stickers<\/a>/);
  assert.match(html, /--accent: #d9480f;/);
  assert.match(html, /<link rel="canonical" href="https:\/\/links.example.com\/jane-doe">/);
  assert.doesNotMatch(html, /\{\{[A-Z_]+\}\}/);
});

test("values cannot inject markup, script links or styles", () => {
  const html = render(template, {
    name: '<script>alert(1)</script>',
    bio: '" onmouseover="x',
    accent: "red;}</style><script>",
    avatar: "javascript:alert(1)",
    links: [{ label: "<b>x</b>", url: "javascript:alert(1)" }, { label: "ok", url: "https://example.org/?a=1&b=<2>" },
      { url: "data:text/html,<script>" }],
  }, "https://links.example.com/x");
  for (const forbidden of ["<script", "javascript:", "data:text"]) assert.ok(!html.includes(forbidden), forbidden);
  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.match(html, /--accent: #2f6fe4;/);
  assert.match(html, /href="https:\/\/example.org\/\?a=1&amp;b=%3C2%3E"/);
  assert.equal((html.match(/class="link"/g) || []).length, 1);
});

test("initials stand in for a missing avatar", () => {
  const html = render(template, { name: "Ada Lovelace" }, "https://links.example.com/ada");
  assert.match(html, /<span class="avatar initials" aria-hidden="true">AL<\/span>/);
});

test("unknown or malformed addresses are 404", async () => {
  const e = env({ "jane-doe": "{}" });
  for (const slug of ["missing", "../etc", "Jane", "", "_templates"]) {
    const response = await handle(new Request("https://links.example.com/x"), e, slug);
    assert.equal(response.status, 404, slug);
  }
});

test("a broken record is an error page, not a crash", async () => {
  for (const raw of ["{", "null", "[1]", "42"]) {
    const response = await handle(new Request("https://links.example.com/x"), env({ x: raw }), "x");
    assert.equal(response.status, 500, raw);
  }
});

test("a redirect to the template is followed once, a missing template is a clear error", async () => {
  const redirecting = {
    PROFILES: { get: async () => '{"name": "Ada"}' },
    ASSETS: {
      fetch: async (url) => (new URL(url).pathname === "/_templates/profile"
        ? new Response(null, { status: 308, headers: { Location: "/_templates/profile-v2" } })
        : new Response(template)),
    },
  };
  const ok = await handle(new Request("https://links.example.com/ada"), redirecting, "ada");
  assert.equal(ok.status, 200);
  assert.match(await ok.text(), /<h1>Ada<\/h1>/);
  const missing = { PROFILES: redirecting.PROFILES, ASSETS: { fetch: async () => new Response("", { status: 404 }) } };
  assert.equal((await handle(new Request("https://links.example.com/ada"), missing, "ada")).status, 500);
});

test("helpers", () => {
  assert.equal(escapeHtml(`<a href="x">'&'</a>`), "&lt;a href=&quot;x&quot;&gt;&#39;&amp;&#39;&lt;/a&gt;");
  assert.equal(safeUrl("mailto:jane@example.com"), "mailto:jane@example.com");
  assert.equal(safeUrl("http://example.com"), null);
  assert.equal(safeUrl("not a url"), null);
});
