import { useState, useEffect, useCallback, useRef } from 'react';
import { getChannels } from './lib/directus.js';
import AdminDashboard from './components/AdminDashboard.jsx';
import AppHeader from './components/AppHeader.jsx';
import { useAppStatus } from './lib/useAppStatus.js';
import { I18nProvider, useT } from './lib/i18n.jsx';

function sameData(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

function keepIfSame(prev, next) {
  return sameData(prev, next) ? prev : next;
}

function AdminAppInner() {
  const { t, lang, setLanguage } = useT();
  const [theme, setTheme] = useState(() => localStorage.getItem('yt_theme') || 'dark');
  const [channels, setChannels] = useState([]);
  const [selectedChannel, setSelectedChannel] = useState(null);
  const [toasts, setToasts] = useState([]);
  const tRef = useRef(t);
  tRef.current = t;

  const {
    fetcherStatus, whisperStatus, fetcherRunning, whisperRunning,
    handleStop, handleWhisperStart, handleWhisperStop, loadStatus,
  } = useAppStatus(tRef);

  function addToast(text) {
    const id = Date.now();
    setToasts(prev => [...prev, { id, text }]);
    setTimeout(() => setToasts(prev => prev.filter(x => x.id !== id)), 5000);
  }

  function handleThemeToggle() {
    const next = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    localStorage.setItem('yt_theme', next);
    if (next === 'light') document.documentElement.setAttribute('data-theme', 'light');
    else document.documentElement.removeAttribute('data-theme');
  }

  const loadChannels = useCallback(async () => {
    try {
      const data = await getChannels();
      setChannels(prev => keepIfSame(prev, data));
      setSelectedChannel(prev => {
        if (!prev) return prev;
        const next = data.find(ch => ch.id === prev.id) || null;
        if (!next) return null;
        return sameData(prev, next) ? prev : next;
      });
    } catch (e) {
      console.error('Failed to load channels', e);
    }
  }, []);

  useEffect(() => {
    loadChannels();
    const interval = setInterval(loadChannels, 10000);
    return () => clearInterval(interval);
  }, [loadChannels]);

  return (
    <div className="app-layout">
      <AppHeader
        fetcherStatus={fetcherStatus}
        whisperStatus={whisperStatus}
        fetcherRunning={fetcherRunning}
        whisperRunning={whisperRunning}
        handleStop={handleStop}
        handleWhisperStart={handleWhisperStart}
        handleWhisperStop={handleWhisperStop}
        theme={theme}
        onThemeToggle={handleThemeToggle}
        t={t}
        lang={lang}
        setLanguage={setLanguage}
      />

      <div className="app-content">
        <AdminDashboard
          channels={channels}
          selectedChannel={selectedChannel}
          fetcherStatus={fetcherStatus}
          whisperStatus={whisperStatus}
          onStatusChanged={loadStatus}
          onChannelsChanged={loadChannels}
        />
      </div>

      {toasts.length > 0 && (
        <div style={{ position: 'fixed', bottom: '4.75rem', right: '1.25rem', display: 'flex', flexDirection: 'column', gap: '0.4rem', zIndex: 2000 }}>
          {toasts.map(toast => (
            <div key={toast.id} style={{ background: 'rgba(76,175,80,0.9)', color: '#fff', padding: '0.55rem 0.9rem', borderRadius: '7px', fontSize: '0.88rem', fontWeight: 600, boxShadow: '0 2px 8px rgba(0,0,0,0.4)', cursor: 'pointer' }} onClick={() => setToasts(prev => prev.filter(x => x.id !== toast.id))}>
              {toast.text}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function AdminApp() {
  return (
    <I18nProvider>
      <AdminAppInner />
    </I18nProvider>
  );
}
