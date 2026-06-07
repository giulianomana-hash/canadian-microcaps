import { useState } from "react";

const SEDAR_SEARCH_URL = "https://www.sedarplus.ca/csa-party/search/";

export default function AddCompanyForm({ onAdd }) {
  const [name, setName] = useState("");
  const [ticker, setTicker] = useState("");
  const [exchange, setExchange] = useState("");
  const [profileUrl, setProfileUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const submit = async (event) => {
    event.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await onAdd({
        name: name.trim(),
        ticker: ticker.trim().toUpperCase() || null,
        exchange: exchange.trim() || null,
        sedar_profile_url: profileUrl.trim() || null,
      });
      setName("");
      setTicker("");
      setExchange("");
      setProfileUrl("");
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className="sw-add-form" onSubmit={submit}>
      <div className="sw-add-row">
        <input
          type="text"
          placeholder="Company name (required)"
          value={name}
          onChange={(event) => setName(event.target.value)}
          required
        />
        <input
          type="text"
          placeholder="Ticker"
          value={ticker}
          onChange={(event) => setTicker(event.target.value)}
        />
        <input
          type="text"
          placeholder="Exchange (TSX / TSXV / CSE)"
          value={exchange}
          onChange={(event) => setExchange(event.target.value)}
        />
      </div>
      <div className="sw-add-row">
        <input
          type="url"
          placeholder="SEDAR+ company profile URL (paste from sedarplus.ca)"
          value={profileUrl}
          onChange={(event) => setProfileUrl(event.target.value)}
          className="sw-add-url"
        />
        <a
          href={SEDAR_SEARCH_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="sw-add-help"
        >
          Find on SEDAR+ ↗
        </a>
        <button type="submit" disabled={submitting || !name.trim()}>
          {submitting ? "Adding…" : "Add"}
        </button>
      </div>
      <p className="sw-add-hint">
        To enable filings polling, click <strong>Find on SEDAR+</strong>, search
        the company there, open its profile, and paste the page URL above. A
        company added without a SEDAR+ URL still appears on your watchlist but
        will not be polled for new filings.
      </p>
      {error && <div className="sw-error">{error}</div>}
    </form>
  );
}
