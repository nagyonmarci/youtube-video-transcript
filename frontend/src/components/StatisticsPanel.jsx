import { useState } from 'react';
import { getErrorVideos } from '../lib/directus.js';
import { useT } from '../lib/i18n.jsx';

export default function StatisticsPanel({ stats, coverage, channels, monthlyData }) {
  const { t } = useT();
  const [errorVideos, setErrorVideos] = useState(null);
  const [showErrorVideos, setShowErrorVideos] = useState(false);

  return (
    <>
      {monthlyData.length > 0 && (() => {
        const max = Math.max(...monthlyData.map(d => d.count), 1);
        return (
          <div style={{ marginBottom: '1rem' }}>
            <div style={{ fontSize: '0.78rem', color: 'var(--text2)', marginBottom: '0.4rem' }}>{t('metric.monthlyChart')}</div>
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: '4px', height: '80px' }}>
              {monthlyData.map(({ month, count }) => (
                <div key={month} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '2px', height: '100%', justifyContent: 'flex-end' }} title={`${month}: ${count}`}>
                  <div style={{ width: '100%', background: 'rgba(100,181,246,0.7)', borderRadius: '3px 3px 0 0', height: `${Math.max(2, Math.round((count / max) * 72))}px` }} />
                  <span style={{ fontSize: '0.6rem', color: 'var(--text2)', transform: 'rotate(-45deg)', transformOrigin: 'top right', whiteSpace: 'nowrap', marginTop: '2px' }}>
                    {month.slice(5)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        );
      })()}

      {coverage && channels.length > 0 && (
        <div>
          <div style={{ fontSize: '0.78rem', color: 'var(--text2)', marginBottom: '0.4rem' }}>{t('header.coverage')}</div>
          <div style={{ border: '1px solid var(--border)', borderRadius: '8px', overflow: 'hidden', background: 'var(--bg2)' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
              <thead>
                <tr>
                  <th style={{ textAlign: 'left', padding: '0.4rem 0.6rem', color: 'var(--text2)', borderBottom: '1px solid var(--border)', fontWeight: 600 }}>{t('label.channel')}</th>
                  <th style={{ textAlign: 'right', padding: '0.4rem 0.6rem', color: 'var(--text2)', borderBottom: '1px solid var(--border)', fontWeight: 600, width: '60px' }}>{t('label.videos')}</th>
                  <th style={{ padding: '0.4rem 0.6rem', color: 'var(--text2)', borderBottom: '1px solid var(--border)', fontWeight: 600, width: '160px' }}>{t('label.transcript')}</th>
                  <th style={{ padding: '0.4rem 0.6rem', color: 'var(--text2)', borderBottom: '1px solid var(--border)', fontWeight: 600, width: '160px' }}>{t('label.aiNote')}</th>
                </tr>
              </thead>
              <tbody>
                {channels.map((ch, i) => {
                  const total = coverage.totalMap.get(ch.id) || ch.video_count || 0;
                  const tr = coverage.transcriptMap.get(ch.id) || 0;
                  const ai = coverage.aiMap.get(ch.id) || 0;
                  const trPct = total ? Math.round((tr / total) * 100) : 0;
                  const aiPct = total ? Math.round((ai / total) * 100) : 0;
                  return (
                    <tr key={ch.id} style={{ background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.02)' }}>
                      <td style={{ padding: '0.35rem 0.6rem' }}>{ch.name || ch.channel_handle}</td>
                      <td style={{ padding: '0.35rem 0.6rem', textAlign: 'right', color: 'var(--text2)' }}>{total}</td>
                      <td style={{ padding: '0.35rem 0.6rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                          <div style={{ flex: 1, height: '6px', background: 'var(--bg3)', borderRadius: '3px', overflow: 'hidden' }}>
                            <div style={{ width: `${trPct}%`, height: '100%', background: trPct === 100 ? '#4caf50' : 'rgba(100,181,246,0.8)', borderRadius: '3px' }} />
                          </div>
                          <span style={{ fontSize: '0.72rem', color: 'var(--text2)', width: '32px', textAlign: 'right' }}>{trPct}%</span>
                        </div>
                      </td>
                      <td style={{ padding: '0.35rem 0.6rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                          <div style={{ flex: 1, height: '6px', background: 'var(--bg3)', borderRadius: '3px', overflow: 'hidden' }}>
                            <div style={{ width: `${aiPct}%`, height: '100%', background: aiPct === 100 ? '#4caf50' : 'rgba(156,39,176,0.7)', borderRadius: '3px' }} />
                          </div>
                          <span style={{ fontSize: '0.72rem', color: 'var(--text2)', width: '32px', textAlign: 'right' }}>{aiPct}%</span>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {(stats?.errorVideos > 0) && (
        <div style={{ marginTop: '0.75rem' }}>
          <button
            style={{ fontSize: '0.8rem' }}
            onClick={async () => {
              if (!showErrorVideos) {
                const list = await getErrorVideos();
                setErrorVideos(list);
              }
              setShowErrorVideos(v => !v);
            }}
          >
            {showErrorVideos ? t('label.hideErrors') : t('label.showErrors', { count: stats.errorVideos })}
          </button>
          {showErrorVideos && errorVideos && (
            <div style={{ marginTop: '0.5rem', border: '1px solid var(--border)', borderRadius: '6px', overflow: 'hidden', background: 'var(--bg2)' }}>
              {errorVideos.map(v => (
                <div key={v.id} style={{ padding: '0.4rem 0.7rem', borderBottom: '1px solid rgba(255,255,255,0.05)', fontSize: '0.82rem', display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                  <span style={{ color: 'var(--text2)', fontSize: '0.75rem', whiteSpace: 'nowrap' }}>
                    {v.channel_id?.name || v.channel_id?.channel_handle || '—'}
                  </span>
                  <a href={v.url} target="_blank" rel="noopener noreferrer" style={{ color: '#f88', textDecoration: 'none', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {v.title || v.video_id}
                  </a>
                </div>
              ))}
              {errorVideos.length === 0 && <div style={{ padding: '0.5rem 0.7rem', color: 'var(--text2)', fontSize: '0.82rem' }}>{t('state.noErrorVideos')}</div>}
            </div>
          )}
        </div>
      )}
    </>
  );
}
