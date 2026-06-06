import { useEffect, useState } from "react";

function formatDate(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return value;
  }
}

export default function FilingsFeed({ client }) {
  const [filings, setFilings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      try {
        const data = await client.listFilings();
        if (alive) setFilings(data ?? []);
      } catch (err) {
        if (alive) setError(err.message);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [client]);

  return (
    <section className="sw-filings">
      <h2 className="sw-filings-title">Recent filings</h2>
      {loading && <p className="sw-empty">Loading filings…</p>}
      {error && <div className="sw-error">{error}</div>}
      {!loading && !error && filings.length === 0 && (
        <p className="sw-empty">
          No filings cached yet. The scheduled refresh runs twice a day; add a
          company to your watchlist and check back tomorrow.
        </p>
      )}
      {filings.length > 0 && (
        <ul className="sw-filings-list">
          {filings.map((f) => (
            <li key={f.id} className="sw-filing-row">
              <div className="sw-filing-head">
                <span className="sw-filing-ticker">{f.ticker ?? "—"}</span>
                <span className="sw-filing-date">{formatDate(f.filing_date)}</span>
              </div>
              <div className="sw-filing-type">{f.filing_type}</div>
              {f.title && <div className="sw-filing-title">{f.title}</div>}
              <a
                className="sw-filing-link"
                href={f.url}
                target="_blank"
                rel="noopener noreferrer"
              >
                Open on SEDAR+ ↗
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
