export default {
  async fetch(request, env) {
    const assetUrl = new URL(request.url);

    if (assetUrl.pathname === "/api" || assetUrl.pathname.startsWith("/api/")) {
      return env.API.fetch(request);
    }

    // The existing Python Worker serves assets from /web/*; Pages stores
    // these files at its root, so map that established URL prefix here.
    if (assetUrl.pathname.startsWith("/web/")) {
      assetUrl.pathname = assetUrl.pathname.slice("/web".length);
      return env.ASSETS.fetch(new Request(assetUrl, request));
    }

    return env.ASSETS.fetch(request);
  },
};
