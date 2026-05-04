import { useEffect, useState } from 'react';
import { videoToTxt, videoToMd, videoToObsidianMd, obsidianFilename, downloadFile, sanitizeFilename } from '../lib/export.js';

function formatDuration(seconds) {
  if (!seconds) return '';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function formatDate(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleDateString('hu-HU');
}

function renderList(items) {
  if (!Array.isArray(items) || items.length === 0) return null;
  return (
    <ul style={{ margin: '0.35rem 0 0.8rem', paddingLeft: '1.2rem', color: '#ddd', lineHeight: 1.55 }}>
      {items.map((item, idx) => <li key={idx}>{item}</li>)}
    </ul>
  );
}

export default function TranscriptModal({ video, onClose }) {
  const [showTimed, setShowTimed] = useState(false);

  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  if (!video) return null;
  const visibleTranscript = showTimed && video.transcript_timed ? video.transcript_timed : video.transcript;
  const hasTimedTranscript = Boolean(video.transcript_timed);

  async function copyToClipboard() {
    try {
      await navigator.clipboard.writeText(visibleTranscript || '');
    } catch {
      const ta = document.createElement('textarea');
      ta.value = visibleTranscript || '';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    }
  }

  return (
    <div
      style={{
        position: 'fixed', inset: 0,
        background: 'rgba(0,0,0,0.75)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        zIndex: 1000, padding: '1rem',
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: 'var(--bg2)',
          border: '1px solid var(--border)',
          borderRadius: '10px',
          width: '100%', maxWidth: '800px',
          maxHeight: '90vh',
          display: 'flex', flexDirection: 'column',
          overflow: 'hidden',
        }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{ padding: '1rem 1.25rem', borderBottom: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem' }}>
            <div>
              <a
                href={video.url}
                target="_blank"
                rel="noopener noreferrer"
                style={{ color: '#64b5f6', textDecoration: 'none', fontWeight: 700, fontSize: '1rem' }}
              >
                {video.title || 'Ismeretlen cím'}
              </a>
              <div style={{ marginTop: '0.3rem', fontSize: '0.8rem', color: '#888', display: 'flex', gap: '1rem' }}>
                {video.uploaded_at && <span>Feltöltve: {formatDate(video.uploaded_at)}</span>}
                {video.duration_seconds && <span>Hossz: {formatDuration(video.duration_seconds)}</span>}
              </div>
            </div>
            <button onClick={onClose} style={{ fontSize: '1.2rem', padding: '0.1rem 0.5rem', flexShrink: 0 }}>✕</button>
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', gap: '0.25rem', marginRight: '0.25rem' }}>
              <button
                onClick={() => setShowTimed(false)}
                disabled={!showTimed}
                style={{ fontSize: '0.8rem' }}
              >
                Sima
              </button>
              <button
                onClick={() => setShowTimed(true)}
                disabled={!hasTimedTranscript || showTimed}
                title={hasTimedTranscript ? 'Időbélyeges transzkript' : 'Ehhez a transzkripthez még nincs időbélyeges változat'}
                style={{ fontSize: '0.8rem' }}
              >
                Idővel
              </button>
            </div>
            <button onClick={copyToClipboard} style={{ fontSize: '0.8rem' }}>Másolás</button>
            <button
              onClick={() => downloadFile(videoToTxt(video, { timed: showTimed }), `${sanitizeFilename(video.title)}${showTimed ? '_idovel' : ''}.txt`)}
              style={{ fontSize: '0.8rem' }}
            >
              Letöltés TXT
            </button>
            <button
              onClick={() => downloadFile(videoToMd(video, { timed: showTimed }), `${sanitizeFilename(video.title)}${showTimed ? '_idovel' : ''}.md`)}
              style={{ fontSize: '0.8rem' }}
            >
              Letöltés MD
            </button>
            <button
              onClick={() => downloadFile(videoToObsidianMd(video, { timed: true }), obsidianFilename(video))}
              style={{ fontSize: '0.8rem' }}
            >
              Obsidian MD
            </button>
          </div>
        </div>

        <div style={{ padding: '1rem 1.25rem', overflowY: 'auto', flex: 1 }}>
          {(video.summary || video.topics?.length || video.takeaways?.length || video.questions?.length) && (
            <div style={{ marginBottom: '1.2rem', paddingBottom: '1rem', borderBottom: '1px solid var(--border)' }}>
              <h3 style={{ fontSize: '0.9rem', marginBottom: '0.5rem', color: '#fff' }}>AI jegyzet</h3>
              {video.summary && (
                <p style={{ lineHeight: 1.65, fontSize: '0.9rem', color: '#ddd', marginBottom: '0.8rem' }}>
                  {video.summary}
                </p>
              )}
              {video.topics?.length > 0 && <h4 style={{ fontSize: '0.8rem', color: '#aaa' }}>Témák</h4>}
              {renderList(video.topics)}
              {video.takeaways?.length > 0 && <h4 style={{ fontSize: '0.8rem', color: '#aaa' }}>Tanulságok</h4>}
              {renderList(video.takeaways)}
              {video.questions?.length > 0 && <h4 style={{ fontSize: '0.8rem', color: '#aaa' }}>Kérdések</h4>}
              {renderList(video.questions)}
            </div>
          )}
          {visibleTranscript ? (
            <p style={{ lineHeight: 1.7, fontSize: '0.9rem', color: '#ddd', whiteSpace: 'pre-wrap' }}>
              {visibleTranscript}
            </p>
          ) : (
            <p style={{ color: '#888', fontStyle: 'italic' }}>Ehhez a videóhoz nincs elérhető transzkript.</p>
          )}
        </div>
      </div>
    </div>
  );
}
