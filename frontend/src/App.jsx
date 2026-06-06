import SedarWatchlist from "./components/SedarWatchlist.jsx";

const pluginConfig = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000",
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
