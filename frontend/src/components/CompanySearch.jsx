import { useEffect, useRef, useState } from "react";

const DEBOUNCE_MS = 250;

export default function CompanySearch({ client, onPick }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(null);
  const rootRef = useRef(null);

  useEffect(() => {
    if (query.trim().length < 2) {
      setResults([]);
      setError(null);
      return undefined;
    }
    const handle = setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const hits = await client.searchCompanies(query.trim());
        setResults(hits);
        setOpen(true);
      } catch (err) {
        setError(err.message);
        setResults([]);
        setOpen(true);
      } finally {
        setLoading(false);
      }
    }, DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [query, client]);

  useEffect(() => {
    function handleClick(event) {
      if (rootRef.current && !rootRef.current.contains(event.target)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const pick = async (hit) => {
    setAdding(hit.ticker);
    try {
      await onPick(hit);
      setQuery("");
      setResults([]);
      setOpen(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setAdding(null);
    }
  };

  return (
    <div className="sw-search-wrap" ref={rootRef}>
      <input
        type="text"
        className="sw-search-input"
        placeholder="Search a company by name or ticker…"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onFocus={() => results.length && setOpen(true)}
        aria-label="Search a Canadian company"
      />
      {open && (loading || results.length > 0 || error) && (
        <div className="sw-search-dropdown" role="listbox">
          {loading && <div className="sw-search-loading">Searching…</div>}
          {error && <div className="sw-search-empty">{error}</div>}
          {!loading && !error && results.length === 0 && query.trim().length >= 2 && (
            <div className="sw-search-empty">
              No Canadian listings found for &ldquo;{query.trim()}&rdquo;.
            </div>
          )}
          {results.map((hit) => (
            <button
              type="button"
              key={hit.ticker}
              className="sw-search-row"
              onClick={() => pick(hit)}
              disabled={adding === hit.ticker}
            >
              <span className="sw-search-row-name">
                <span className="sw-search-row-ticker">{hit.ticker}</span>
                {hit.name}
              </span>
              <span className="sw-search-row-meta">
                {[hit.exchange, hit.sector || hit.industry]
                  .filter(Boolean)
                  .join(" · ") || "Canadian equity"}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
