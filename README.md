# cf-pages-linkinbio

Link-in-bio pages on Cloudflare Pages: one project serves any number of pages at `/<name>`. Each page comes from a
small JSON profile in this repository, is kept in Workers KV and rendered on request. There is no build step, no
JavaScript on the page and no tracking, and it stays within Cloudflare's free plan.

![A link page on a phone: initials, name, short bio and four link buttons](docs/screenshot.png)

## How it works

```text
profiles/jane-doe.json --sync.py--> Workers KV --functions/[slug].js--> https://links.example.com/jane-doe
                                                  + public/_templates/profile.html
```

- `profiles/*.json`: one file per page. The file name is the address.
- `sync.py` checks every profile and writes it into KV with one bulk request. `--prune` also removes pages whose
  file is gone; it deletes every key it does not know, so give the pages a KV namespace of their own. Python
  standard library only.
- `functions/[slug].js` is a Pages Function. It reads the profile from KV, fills the template and answers with a
  strict Content-Security-Policy. Unknown names get 404.
- `public/` holds the template, a plain index page, security headers for the static files (`_headers`) and the
  route list (`_routes.json`) that keeps static files away from the function.

Changing a page means editing its JSON and running `sync.py`. The site itself does not need a new deploy.

## Profile

```json
{
  "name": "Jane Doe",
  "title": "Jane Doe, illustrator",
  "bio": "Illustrations for books and games. Commissions open in spring.",
  "accent": "#d9480f",
  "avatar": "https://example.com/jane.jpg",
  "links": [
    {"label": "Portfolio", "url": "https://example.com/portfolio"},
    {"label": "Write to me", "url": "mailto:jane@example.com"}
  ]
}
```

| Field | Rule |
|---|---|
| `name` | required, at most 80 characters |
| `title` | page title for browsers and link previews, at most 120 characters (default: the name) |
| `bio` | at most 300 characters |
| `accent` | a color like `#d9480f` for buttons and the initials |
| `avatar` | an `https` picture; without one the page shows the initials |
| `links` | at most 30 entries, each with `url` (`https` or `mailto`) and `label` (at most 80 characters) |

`sync.py` refuses unknown fields, so a typo like `acent` does not go unnoticed.

## Setup

You need a Cloudflare account and Node.js for `wrangler`.

```sh
npx wrangler kv namespace create PROFILES          # prints the namespace id
cp wrangler.toml.example wrangler.toml             # put the id in
npx wrangler pages deploy                          # deploys public/ and functions/

export CLOUDFLARE_API_TOKEN=...                    # Account: Workers KV Storage Edit
export CLOUDFLARE_ACCOUNT_ID=... KV_NAMESPACE_ID=...
python3 sync.py --dry-run                          # check the profiles
python3 sync.py                                    # write them into KV
```

Attach your own domain to the Pages project in the dashboard, and the pages live at `https://your-domain/<name>`.

## Safety

- Every value from a profile is HTML-escaped before it goes into the page.
- Links must be `https` or `mailto`, the picture must be `https`. `javascript:` and `data:` links are dropped.
- The accent color must be a hex color, because it goes into the style sheet.
- The page has no scripts. The Content-Security-Policy forbids them, along with frames, forms and a `<base>`.
- Addresses outside the pattern `[a-z0-9-]` get 404 before KV is asked.

## Costs

Each page view is one Pages Function request and one KV read. Browsers keep a page for a minute
(`Cache-Control: max-age=60`). Cloudflare's free plan currently includes 100,000 Function requests and 100,000 KV
reads per day.

## Development

```sh
node --test tests/      # the renderer and the function, with a fake KV
pytest                  # sync.py: checks, bulk write, prune, error messages without the token
ruff check .
```

To try the whole site locally: `npx wrangler pages dev`, after writing a profile into the local KV with
`npx wrangler kv key put --local --binding PROFILES jane-doe "$(cat profiles/jane-doe.json)"`.

## License

MIT
