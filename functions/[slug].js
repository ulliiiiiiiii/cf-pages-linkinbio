// /<slug>: one link page per profile, rendered from KV on each request.
import { handle } from "../lib/render.js";

export const onRequestGet = ({ request, env, params }) => handle(request, env, params.slug);
