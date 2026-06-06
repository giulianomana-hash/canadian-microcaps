import { useEffect, useRef, useState } from "react";

const DEBOUNCE_MS = 350;

export default function SedarSearch({ client, onPick, onManualAdd }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(false);
  const containerRef = useRef(null);

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
      } finally {
        setLoading(false);
      }
    }, DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [query, client]);

  useEffect(() => {
    function handleClick(event) {
      if (containerRef.current && !containerRef.current.contains(event.target)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const pick = async (hit) => {
    setOpen(false);
    setQuery("");
    setResults([]);
    await onPick(hit);
  };

  const manual = async () => {
    setOpen(false);
    await onManualAdd(query);
    setQuery("");
  };

  return (
    <div className="sw-search-wrap" ref={containerRef}>
      <input
        type="text"
        placeholder="Search SEDAR+ by company name or ticker…"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onFocus={() => results.length && setOpen(true)}
        aria-label="Search SEDAR+ for a Canadian issuer"
        className="sw-search-input"
      />
      {open && (loading || results.length > 0 || query.trim().length >= 2) && (
        <div className="sw-search-dropdown" role="listbox">
          {loading && <div className="sw-search-loading">Searching SEDAR+…</div>}
          {!loading && results.length === 0 && query.trim().length >= 2 && (
            <div className="sw-search-empty">
              <div>No SEDAR+ matches for &ldquo;{query.trim()}&rdquo;.</div>
              <button type="button" className="sw-search-manual" onClick={manual}>
                Add &ldquo;{query.trim()}&rdquo; manually
              </button>
            </div>
          )}
          {results.map((hit) => (
            <button
              type="button"
              key={hit.sedar_profile_id}
              className="sw-search-row"
              onClick={() => pick(hit)}
            >
              <span className="sw-search-row-name">{hit.name}</span>
              <span className="sw-search-row-meta">
                {[hit.ticker, hit.exchange, hit.jurisdiction]
                  .filter(Boolean)
                  .join(" · ") || "Canadian reporting issuer"}
              </span>
            </button>
          ))}
        </div>
      )}
      {error && (
        <div className="sw-error" role="alert">
          Search failed: {error}
        </div>
      )}
    </div>
  );
}
