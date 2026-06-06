import SedarWatchlist from "./components/SedarWatchlist.jsx";

const apiBaseUrl =
  import.meta.env.VITE_API_BASE_URL ||
  (import.meta.env.DEV ? "http://localhost:8000" : window.location.origin);

const pluginConfig = {
  apiBaseUrl,
  userId: "demo-user",
  marketCapCeiling: 50_000_000,
};

export default function App() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>SedarWatchlist</h1>
        <p>Canadian microcaps under $50M market cap.</p>
      </header>
      <main>
        <SedarWatchlist pluginConfig={pluginConfig} />
      </main>
    </div>
  );
}
