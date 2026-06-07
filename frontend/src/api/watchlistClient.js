export function createWatchlistClient({ apiBaseUrl }) {
  if (!apiBaseUrl) {
    throw new Error("createWatchlistClient requires apiBaseUrl");
  }

  const base = apiBaseUrl.replace(/\/$/, "");

  async function request(path, options = {}) {
    const response = await fetch(`${base}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });

    if (!response.ok) {
      let detail = response.statusText;
      try {
        const body = await response.json();
        if (body?.detail) detail = body.detail;
      } catch {
        // body wasn't JSON; fall back to statusText
      }
      throw new Error(`${response.status} ${detail}`);
    }

    if (response.status === 204) return null;
    return response.json();
  }

  return {
    listWatchlist: () => request("/api/watchlist"),
    addWatchlistEntry: (entry) =>
      request("/api/watchlist", {
        method: "POST",
        body: JSON.stringify(entry),
      }),
    removeWatchlistEntry: (id) =>
      request(`/api/watchlist/${encodeURIComponent(id)}`, {
        method: "DELETE",
      }),
    listFilings: () => request("/api/filings"),
    searchCompanies: (q) =>
      request(`/api/search?q=${encodeURIComponent(q)}`),
  };
}
