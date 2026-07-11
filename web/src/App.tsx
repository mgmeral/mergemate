import { useState, useEffect } from 'react';
import { Dashboard } from './components/Dashboard';
import { RunDetail } from './components/RunDetail';

type Page = 'dashboard' | 'run-detail';
type Theme = 'light' | 'dark';

const THEME_KEY = 'mergemate-theme';

function getInitialTheme(): Theme {
  try {
    const stored = localStorage.getItem(THEME_KEY);
    if (stored === 'light' || stored === 'dark') return stored;
  } catch {
    // localStorage unavailable (e.g. SSR / private browsing)
  }
  return 'dark';
}

export default function App() {
  const [theme, setTheme] = useState<Theme>(getInitialTheme);
  const [page, setPage] = useState<Page>('dashboard');
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  // Apply theme to <html> element
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      // ignore
    }
  }, [theme]);

  function toggleTheme() {
    setTheme((t) => (t === 'dark' ? 'light' : 'dark'));
  }

  function handleSelectRun(runId: string) {
    setSelectedRunId(runId);
    setPage('run-detail');
  }

  function handleBack() {
    setPage('dashboard');
    setSelectedRunId(null);
  }

  return (
    <>
      <header className="app-header">
        <div className="app-header__title">
          <span className="app-header__logo">M</span>
          MergeMate
        </div>
        <button
          type="button"
          className="theme-toggle"
          onClick={toggleTheme}
          aria-label="Toggle colour theme"
        >
          {theme === 'dark' ? '☀ Light' : '🌙 Dark'}
        </button>
      </header>

      <main>
        {page === 'dashboard' && (
          <Dashboard onSelectRun={handleSelectRun} />
        )}
        {page === 'run-detail' && selectedRunId !== null && (
          <RunDetail runId={selectedRunId} onBack={handleBack} />
        )}
      </main>
    </>
  );
}
