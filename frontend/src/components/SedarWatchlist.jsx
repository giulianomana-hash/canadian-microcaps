import { useCallback, useEffect, useMemo, useState } from "react";
import { createWatchlistClient } from "../api/watchlistClient.js";
import CompanySearch from "./CompanySearch.jsx";
import FilingsFeed from "./FilingsFeed.jsx";

const DEFAULT_CONFIG = {
  apiBaseUrl: "http://localhost:8000",
  userId: "demo-user",
  marketCapCeiling: 50_000_000,
};

function SedarUrlEditor({ entry, client, onUpdated }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(entry.sedar_profile_url ?? "");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState(null);

  const save = async () => {
    setSaving(true);
    setErr(null);
    try {
      const updated = await client.updateWatchlistEntry(entry.id, {
        sedar_profile_url: value.trim() || null,
      });
      onUpdated(updated);
      setEditing(false);
    } catch (e) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  };

  if (!editing) {
    return (
      <div className="sw-card-meta">
        Filings:{" "}
        {entry.sedar_profile_url ? (
          <>
            <a
              href={entry.sedar_profile_url}
              target="_blank"
              rel="noopener noreferrer"
              className="sw-card-link"
            >
              SEDAR+ ↗
            </a>
            {" · "}
            <button
              type="button"
              className="sw-card-link-btn"
              onClick={() => { setValue(entry.sedar_profile_url); setEditing(true); }}
            >
              edit
            </button>
          </>
        ) : (
          <>
            <span className="sw-card-pending">no SEDAR URL</span>
            {" · "}
            <button
              type="button"
              className="sw-card-link-btn"
              onClick={() => { setValue(""); setEditing(true); }}
            >
              set URL
            </button>
          </>
        )}
      </div>
    );
  }

  return (
    <div className="sw-sedar-editor">
      <input
        className="sw-sedar-input"
        type="url"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="https://www.sedarplus.ca/csa-party/viewInstance/view.html?id=…"
        autoFocus
      />
      <div className="sw-sedar-actions">
        <button type="button" className="sw-btn-save" onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </button>
        <button type="button" className="sw-btn-cancel" onClick={() => { setEditing(false); setErr(null); }}>
          Cancel
        </button>
      </div>
      {err && <div className="sw-error">{err}</div>}
    </div>
  );
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

  const handlePick = async (hit) => {
    setError(null);
    const created = await client.addWatchlistEntry({
      user_id: config.userId,
      ticker: hit.ticker,
      name: hit.name,
      exchange: hit.exchange ?? null,
      sector: hit.sector ?? null,
    });
    setEntries((prev) => [created, ...prev]);
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

  const handleEntryUpdated = (updated) => {
    setEntries((prev) => prev.map((e) => (e.id === updated.id ? updated : e)));
  };

  return (
    <section className="sw-root">
      <CompanySearch client={client} onPick={handlePick} />

      {error && <div className="sw-error" role="alert">{error}</div>}

      {loading && entries.length === 0 ? (
        <p className="sw-empty">Loading watchlist…</p>
      ) : entries.length === 0 ? (
        <p className="sw-empty">
          No companies on your watchlist yet. Search above to add one.
        </p>
      ) : (
        <div className="sw-grid">
          {entries.map((entry) => (
            <article key={entry.id} className="sw-card">
              <div className="sw-card-header">
                <span className="sw-card-ticker">{entry.ticker ?? "—"}</span>
                <span className="sw-card-meta">{entry.exchange ?? ""}</span>
              </div>
              <div className="sw-card-name">{entry.name}</div>
              {entry.sector && (
                <div className="sw-card-meta">Sector: {entry.sector}</div>
              )}
              <SedarUrlEditor
                entry={entry}
                client={client}
                onUpdated={handleEntryUpdated}
              />
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
