import QuickAddPopover from './QuickAddPopover.jsx';
import HeaderSearch from './HeaderSearch.jsx';

export default function AppHeader({
  fetcherStatus, whisperStatus, fetcherRunning, whisperRunning,
  handleStop, handleWhisperStart, handleWhisperStop,
  theme, onThemeToggle, t, lang, setLanguage,
}) {
  const path = window.location.pathname;

  return (
    <header className="app-header">
      <a href="/" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', textDecoration: 'none', color: 'inherit' }}>
        <span style={{ fontSize: '1.4rem' }}>▶</span>
        <h1 style={{ fontSize: '1.1rem', fontWeight: 700 }}>{t('header.appTitle')}</h1>
      </a>

      <nav className="main-nav">
        <a href="/daily" className={path === '/daily' ? 'active' : ''}>{t('nav.dailyUpdates')}</a>
        <a href="/admin" className={path === '/admin' ? 'active' : ''}>{t('nav.admin')}</a>
        <HeaderSearch />
        <QuickAddPopover />
      </nav>

      <div className="header-status">
        {fetcherRunning && (
          <span className="header-status-item">
            <span className="badge badge-processing status-chip">
              {t('label.processingBadge', { count: fetcherStatus.queue_size })}
            </span>
            {fetcherStatus.current_task?.phase && (
              <span className="badge badge-processing status-chip">
                {fetcherStatus.current_task.phase}
              </span>
            )}
            {fetcherStatus.current_task?.video && (
              <span className="badge badge-processing status-chip status-chip-video" title={fetcherStatus.current_task.video}>
                {fetcherStatus.current_task.video}
              </span>
            )}
            {(fetcherStatus.ai_active_size > 0 || fetcherStatus.ai_queue_size > 0) && (
              <span className="badge badge-processing status-chip">
                {t('label.aiChip', { count: fetcherStatus.ai_active_size ?? fetcherStatus.ai_queue_size })}
              </span>
            )}
            {fetcherStatus.current_ai_task?.phase && (
              <span className="badge badge-processing status-chip">
                {fetcherStatus.current_ai_task.phase}
              </span>
            )}
            {fetcherStatus.current_ai_task?.video && (
              <span className="badge badge-processing status-chip status-chip-video" title={fetcherStatus.current_ai_task.video}>
                {fetcherStatus.current_ai_task.video}
              </span>
            )}
            <button className="danger" onClick={handleStop} style={{ padding: '0.25rem 0.6rem' }}>
              {t('btn.stop')}
            </button>
          </span>
        )}

        <span className="header-status-item">
          {whisperRunning ? (
            <>
              <span className="badge badge-whisper">
                {t('label.whisperBadge', { count: whisperStatus.queue_size })}
                {whisperStatus.current_task?.video_id && ` • ${whisperStatus.current_task.video_id}`}
                {whisperStatus.current_task?.phase && ` (${whisperStatus.current_task.phase})`}
              </span>
              <button className="danger" onClick={handleWhisperStop} style={{ padding: '0.25rem 0.6rem' }}>
                {t('btn.stop')}
              </button>
            </>
          ) : (
            <button onClick={handleWhisperStart} className="whisper-btn" style={{ padding: '0.25rem 0.6rem' }}>
              {t('btn.whisperStart')}
            </button>
          )}
        </span>

        <button
          onClick={onThemeToggle}
          title={theme === 'dark' ? 'Váltás világos módra' : 'Váltás sötét módra'}
          style={{ padding: '0.25rem 0.55rem', fontSize: '1rem', opacity: 0.85 }}
        >
          {theme === 'dark' ? '☀' : '☾'}
        </button>
        <button
          onClick={() => setLanguage(lang === 'hu' ? 'en' : 'hu')}
          title={lang === 'hu' ? 'Switch to English' : 'Váltás magyarra'}
          style={{ padding: '0.25rem 0.55rem', fontWeight: 700, fontSize: '0.8rem', opacity: 0.85 }}
        >
          {lang === 'hu' ? 'EN' : 'HU'}
        </button>
      </div>
    </header>
  );
}
