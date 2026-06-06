import { useCallback, useEffect, useMemo, useState } from "react";
import { createWatchlistClient } from "../api/watchlistClient.js";

const DEFAULT_CONFIG = {
  apiBaseUrl: "http://localhost:8000",
  userId: "demo-user",
  marketCapCeiling: 50_000_000,
};

function formatMarketCap(value) {
  if (value == null) return "—";
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `$${(value / 1_000).toFixed(1)}K`;
  return `$${value}`;
}

function parseQuery(query) {
  const trimmed = query.trim();
  if (!trimmed) return null;
  // Convention: "TICKER - Company Name" or just a ticker.
  const [tickerPart, ...nameParts] = trimmed.split(/[-–:]/);
  const ticker = tickerPart.trim().toUpperCase();
  const name = nameParts.join(" ").trim() || ticker;
  return { ticker, name };
}

export default function SedarWatchlist({ pluginConfig }) {
  const config = useMemo(
    () => ({ ...DEFAULT_CONFIG, ...(pluginConfig ?? {}) }),
    [pluginConfig],
  );

  const client = useMemo(
    () => createWatchlistClient({ apiBaseUrl: config.apiBaseUrl }),
    [config.apiBaseUrl],
  );

  const [entries, setEntries] = useState([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await client.listWatchlist();
      setEntries(data ?? []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [client]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleAdd = async (event) => {
    event.preventDefault();
    const parsed = parseQuery(query);
    if (!parsed) return;

    setSubmitting(true);
    setError(null);
    try {
      const created = await client.addWatchlistEntry({
        user_id: config.userId,
        ticker: parsed.ticker,
        name: parsed.name,
      });
      setEntries((prev) => [created, ...prev]);
      setQuery("");
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleRemove = async (id) => {
    setError(null);
    const snapshot = entries;
    setEntries((prev) => prev.filter((entry) => entry.id !== id));
    try {
      await client.removeWatchlistEntry(id);
    } catch (err) {
      setError(err.message);
      setEntries(snapshot);
    }
  };

  return (
    <section className="sw-root">
      <form className="sw-search" onSubmit={handleAdd}>
        <input
          type="text"
          placeholder="Add a company (e.g. ABC - Acme Mining Corp)"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          aria-label="Add a company by ticker or name"
        />
        <button type="submit" disabled={submitting || !query.trim()}>
          {submitting ? "Adding…" : "Add"}
        </button>
      </form>

      {error && <div className="sw-error" role="alert">{error}</div>}

      {loading && entries.length === 0 ? (
        <p className="sw-empty">Loading watchlist…</p>
      ) : entries.length === 0 ? (
        <p className="sw-empty">
          No companies on your watchlist yet. Add one above to get started.
        </p>
      ) : (
        <div className="sw-grid">
          {entries.map((entry) => (
            <article key={entry.id} className="sw-card">
              <div className="sw-card-header">
                <span className="sw-card-ticker">{entry.ticker}</span>
                <span className="sw-card-meta">{entry.exchange ?? "—"}</span>
              </div>
              <div className="sw-card-name">{entry.name}</div>
              <div className="sw-card-meta">
                Sector: {entry.sector ?? "Unclassified"}
              </div>
              <div className="sw-card-meta">
                Market cap: {formatMarketCap(entry.market_cap)}
              </div>
              <button
                type="button"
                className="sw-card-remove"
                onClick={() => handleRemove(entry.id)}
              >
                Remove
              </button>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
