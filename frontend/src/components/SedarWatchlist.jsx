import { useCallback, useEffect, useMemo, useState } from "react";
import { createWatchlistClient } from "../api/watchlistClient.js";
import SedarSearch from "./SedarSearch.jsx";
import FilingsFeed from "./FilingsFeed.jsx";

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
  const [loading, setLoading] = useState(false);
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

  const addFromSedar = async (hit) => {
    setError(null);
    try {
      const created = await client.addWatchlistEntry({
        user_id: config.userId,
        sedar_profile_id: hit.sedar_profile_id,
        name: hit.name,
        ticker: hit.ticker ?? null,
        exchange: hit.exchange ?? null,
        jurisdiction: hit.jurisdiction ?? null,
      });
      setEntries((prev) => [created, ...prev]);
    } catch (err) {
      setError(err.message);
    }
  };

  const addManually = async (rawQuery) => {
    const trimmed = (rawQuery ?? "").trim();
    if (!trimmed) return;
    setError(null);
    // Convention: "TICKER - Company Name" or just a name.
    const [first, ...rest] = trimmed.split(/[-–:]/);
    const head = first.trim();
    const tail = rest.join(" ").trim();
    const ticker = tail ? head.toUpperCase() : null;
    const name = tail || head;
    try {
      const created = await client.addWatchlistEntry({
        user_id: config.userId,
        ticker,
        name,
      });
      setEntries((prev) => [created, ...prev]);
    } catch (err) {
      setError(err.message);
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
      <SedarSearch
        client={client}
        onPick={addFromSedar}
        onManualAdd={addManually}
      />

      {error && <div className="sw-error" role="alert">{error}</div>}

      {loading && entries.length === 0 ? (
        <p className="sw-empty">Loading watchlist…</p>
      ) : entries.length === 0 ? (
        <p className="sw-empty">
          No companies on your watchlist yet. Search SEDAR+ above to add one.
        </p>
      ) : (
        <div className="sw-grid">
          {entries.map((entry) => (
            <article key={entry.id} className="sw-card">
              <div className="sw-card-header">
                <span className="sw-card-ticker">{entry.ticker ?? "—"}</span>
                <span className="sw-card-meta">
                  {entry.exchange ?? entry.jurisdiction ?? ""}
                </span>
              </div>
              <div className="sw-card-name">{entry.name}</div>
              <div className="sw-card-meta">
                Sector: {entry.sector ?? "Unclassified"}
              </div>
              <div className="sw-card-meta">
                Market cap: {formatMarketCap(entry.market_cap)}
              </div>
              {entry.sedar_profile_id && (
                <div className="sw-card-meta">
                  SEDAR+ id: {entry.sedar_profile_id}
                </div>
              )}
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

      <FilingsFeed client={client} />
    </section>
  );
}
