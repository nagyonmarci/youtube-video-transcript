import { useEffect } from 'react';
import { videoToTxt, videoToMd, downloadFile, sanitizeFilename } from '../lib/export.js';

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

export default function TranscriptModal({ video, onClose }) {
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  if (!video) return null;

  async function copyToClipboard() {
    try {
      await navigator.clipboard.writeText(video.transcript || '');
    } catch {
      const ta = document.createElement('textarea');
      ta.value = video.transcript || '';
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
            <button onClick={copyToClipboard} style={{ fontSize: '0.8rem' }}>Másolás</button>
            <button
              onClick={() => downloadFile(videoToTxt(video), `${sanitizeFilename(video.title)}.txt`)}
              style={{ fontSize: '0.8rem' }}
            >
              Letöltés TXT
            </button>
            <button
              onClick={() => downloadFile(videoToMd(video), `${sanitizeFilename(video.title)}.md`)}
              style={{ fontSize: '0.8rem' }}
            >
              Letöltés MD
            </button>
          </div>
        </div>

        <div style={{ padding: '1rem 1.25rem', overflowY: 'auto', flex: 1 }}>
          {video.transcript ? (
            <p style={{ lineHeight: 1.7, fontSize: '0.9rem', color: '#ddd', whiteSpace: 'pre-wrap' }}>
              {video.transcript}
            </p>
          ) : (
            <p style={{ color: '#888', fontStyle: 'italic' }}>Ehhez a videóhoz nincs elérhető transzkript.</p>
          )}
        </div>
      </div>
    </div>
  );
}
