import { useEffect, useState } from 'react';
import { getAdminStats, getChannelCoverage, getMonthlyVideoCounts, getErrorVideos } from '../lib/directus.js';
import {
  deleteJob,
  generateAiNotes,
  getJobs,
  getSchedule,
  moveJob,
  pauseJob,
  refreshDates,
  refreshThumbnails,
  resumeJob,
  startJob,
  stopProcessing,
  stopWhisper,
  updateSchedule,
} from '../lib/fetcher.js';
import ChannelAdminPanel from './ChannelAdminPanel.jsx';
import TopActions from './TopActions.jsx';
import { useT } from '../lib/i18n.jsx';

function sameData(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

function keepIfSame(prev, next) {
  return sameData(prev, next) ? prev : next;
}

function formatProgress(current, total) {
  const cur = Number(current || 0);
  const max = Number(total || 0);
  if (!cur || !max) return '';
  return `${cur}/${max} (${Math.round((cur / max) * 100)}%)`;
}

function cronToDailyTime(cron) {
  const parts = (cron || '').trim().split(/\s+/);
  if (parts.length !== 5 || parts[2] !== '*' || parts[3] !== '*' || parts[4] !== '*') return '07:00';
  const [minute, hour] = parts;
  if (!/^\d+$/.test(minute) || !/^\d+$/.test(hour)) return '07:00';
  return `${String(Math.min(23, Number(hour))).padStart(2, '0')}:${String(Math.min(59, Number(minute))).padStart(2, '0')}`;
}

function dailyTimeToCron(time) {
  const [hour = '7', minute = '0'] = (time || '07:00').split(':');
  return `${Number(minute)} ${Number(hour)} * * *`;
}

function StatusLine({ title, queueSize, current, onStop }) {
  const { t } = useT();
  const active = queueSize > 0 || Boolean(current?.type);
  const progressText = formatProgress(current?.progress_current, current?.progress_total);
  return (
    <div className="process-line">
      <div>
        <h4>{title}</h4>
        <p>
          {active ? (
            <>
              <span>{t('label.queueSize', { count: queueSize })}</span>
              {current?.phase && <span> · {current.phase}</span>}
              {current?.video && <span> · {current.video}</span>}
              {current?.video_id && !current?.video && <span> · {current.video_id}</span>}
              {progressText && <span> · {progressText}</span>}
            </>
          ) : (
            <span>{t('state.noRunning')}</span>
          )}
        </p>
        {progressText && (
          <progress
            className="job-progress"
            value={Number(current.progress_current || 0)}
            max={Number(current.progress_total || 1)}
          />
        )}
      </div>
      <div className="process-actions">
        <span className={`badge ${active ? 'badge-processing' : 'badge-done'}`}>
          {active ? t('status.running') : t('status.empty')}
        </span>
        {active && onStop && <button className="danger" onClick={onStop}>{t('btn.stop')}</button>}
      </div>
    </div>
  );
}

function formatJobTime(value) {
  if (!value) return '';
  return new Date(value).toLocaleString('hu-HU', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function JobQueuePanel({ jobs, onAction, busy }) {
  const { t } = useT();
  const [showCompleted, setShowCompleted] = useState(false);

  const JOB_STATUS_LABELS = {
    queued: t('status.queued'),
    running: t('status.running'),
    paused: t('status.paused'),
    done: t('status.done'),
    error: t('status.error'),
    cancelled: t('status.cancelled'),
  };

  const activeJobs = jobs.filter(job => job.status !== 'done' && job.status !== 'cancelled');
  const completedJobs = jobs.filter(job => job.status === 'done' || job.status === 'cancelled');
  const visibleJobs = showCompleted ? jobs.slice(0, 100) : activeJobs.slice(0, 80);
  return (
    <>
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.4rem', alignItems: 'center' }}>
        <span style={{ fontSize: '0.78rem', color: 'var(--text2)' }}>{t('label.activeJobs', { count: activeJobs.length })}</span>
        {completedJobs.length > 0 && (
          <button style={{ fontSize: '0.75rem', padding: '0.15rem 0.45rem' }} onClick={() => setShowCompleted(v => !v)}>
            {showCompleted ? t('label.activeOnly') : t('label.plusCompleted', { count: completedJobs.length })}
          </button>
        )}
      </div>
      <div className="job-table-wrap">
        <table className="job-table">
          <thead>
            <tr>
              <th>{t('label.queue')}</th>
              <th>{t('label.task')}</th>
              <th>{t('label.status')}</th>
              <th>{t('label.createdAt')}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {visibleJobs.map(job => {
              const running = job.status === 'running';
              const paused = job.status === 'paused';
              const reorderable = ['queued', 'paused'].includes(job.status);
              const progressText = formatProgress(job.progress_current, job.progress_total);
              return (
                <tr key={job.id}>
                  <td>
                    <span className={`badge ${job.queue === 'ai' ? 'badge-whisper' : 'badge-processing'}`}>
                      {job.queue}
                    </span>
                  </td>
                  <td>
                    <div className="job-label">{job.label || job.type}</div>
                    {progressText && <div className="job-progress-text">{progressText}</div>}
                    {progressText && (
                      <progress
                        className="job-progress"
                        value={Number(job.progress_current || 0)}
                        max={Number(job.progress_total || 1)}
                      />
                    )}
                    {job.error_message && <div className="job-error">{job.error_message}</div>}
                  </td>
                  <td>
                    <span className={`badge badge-${job.status}`}>
                      {JOB_STATUS_LABELS[job.status] || job.status}
                    </span>
                    {Number(job.attempts || 0) > 0 && (
                      <div className="job-progress-text">
                        {t('label.attempts', { current: job.attempts, max: job.max_attempts || 3 })}
                      </div>
                    )}
                  </td>
                  <td>{formatJobTime(job.created_at)}</td>
                  <td>
                    <div className="job-actions">
                      <button disabled={busy || !reorderable} onClick={() => onAction(() => moveJob(job.id, 'up'))}>{t('btn.up')}</button>
                      <button disabled={busy || !reorderable} onClick={() => onAction(() => moveJob(job.id, 'down'))}>{t('btn.down')}</button>
                      {paused ? (
                        <button disabled={busy} onClick={() => onAction(() => resumeJob(job.id))}>{t('btn.resume')}</button>
                      ) : (
                        <button disabled={busy || running || ['done', 'cancelled'].includes(job.status)} onClick={() => onAction(() => pauseJob(job.id))}>{t('btn.pause')}</button>
                      )}
                      <button disabled={busy || running} onClick={() => onAction(() => startJob(job.id))}>{t('btn.start')}</button>
                      <button className="danger" disabled={busy} onClick={() => onAction(() => deleteJob(job.id))}>{t('btn.delete')}</button>
                    </div>
                  </td>
                </tr>
              );
            })}
            {visibleJobs.length === 0 && (
              <tr>
                <td colSpan="5" className="admin-empty">{t('state.noJobs')}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

export default function AdminDashboard({
  channels,
  selectedChannel,
  fetcherStatus,
  whisperStatus,
  onChannelsChanged,
  onStatusChanged,
}) {
  const { t } = useT();
  const [stats, setStats] = useState(null);
  const [coverage, setCoverage] = useState(null);
  const [monthlyData, setMonthlyData] = useState([]);
  const [errorVideos, setErrorVideos] = useState(null);
  const [showErrorVideos, setShowErrorVideos] = useState(false);
  const [scheduleCron, setScheduleCron] = useState('0 7 * * *');
  const [scheduleTime, setScheduleTime] = useState('07:00');
  const [scheduleTimezone, setScheduleTimezone] = useState('Europe/Budapest');
  const [jobs, setJobs] = useState([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  async function loadAdminData() {
    try {
      const [nextStats, schedule, jobData, cov, monthly] = await Promise.all([
        getAdminStats(),
        getSchedule(),
        getJobs(),
        getChannelCoverage(),
        getMonthlyVideoCounts(),
      ]);
      const nextCron = schedule.cron || '0 7 * * *';
      const nextTime = cronToDailyTime(nextCron);
      const nextTimezone = schedule.timezone || 'Europe/Budapest';
      setStats(prev => keepIfSame(prev, nextStats));
      setJobs(prev => keepIfSame(prev, jobData.jobs || []));
      setCoverage(cov);
      setMonthlyData(monthly);
      setScheduleCron(prev => (prev === nextCron ? prev : nextCron));
      setScheduleTime(prev => (prev === nextTime ? prev : nextTime));
      setScheduleTimezone(prev => (prev === nextTimezone ? prev : nextTimezone));
    } catch (e) {
      setMsg({ text: t('msg.errAdmin', { error: e.message }), isError: true });
    }
  }

  useEffect(() => {
    loadAdminData();
    const interval = setInterval(loadAdminData, 10000);
    return () => clearInterval(interval);
  }, []);

  function showMsg(text, isError = false) {
    setMsg({ text, isError });
    setTimeout(() => setMsg(null), 4000);
  }

  async function runAction(action, successText) {
    setBusy(true);
    try {
      const result = await action();
      showMsg(typeof successText === 'function' ? successText(result) : successText);
      await Promise.all([loadAdminData(), onStatusChanged?.()]);
    } catch (e) {
      showMsg(t('msg.errGeneric', { error: e.message }), true);
    } finally {
      setBusy(false);
    }
  }

  async function runJobAction(action) {
    await runAction(action, t('msg.queueRefreshed'));
  }

  async function saveSchedule(e) {
    e.preventDefault();
    await runAction(
      () => updateSchedule(dailyTimeToCron(scheduleTime), scheduleTimezone),
      t('msg.scheduleUpdated')
    );
  }

  const channelCount = channels.length;
  const totalChannelVideos = channels.reduce((sum, ch) => sum + (ch.video_count || 0), 0);
  const displayedTotalVideos = stats?.totalVideos ?? totalChannelVideos;

  return (
    <section className="admin-dashboard">
      <div className="view-header">
        <div>
          <h2>{t('header.admin')}</h2>
          <p>{t('header.adminSub', { channels: channelCount, videos: displayedTotalVideos })}</p>
        </div>
      </div>

      {msg && <div className={`status-msg ${msg.isError ? 'status-error' : 'status-success'}`}>{msg.text}</div>}

      <div className="metric-grid">
        <div className="metric-card">
          <span>{t('metric.todayVideos')}</span>
          <strong>{stats?.todayVideos ?? '-'}</strong>
        </div>
        <div className="metric-card">
          <span>{t('metric.totalVideos')}</span>
          <strong>{displayedTotalVideos}</strong>
        </div>
        <div className="metric-card">
          <span>{t('metric.missingTranscripts')}</span>
          <strong>{stats?.missingTranscripts ?? '-'}</strong>
        </div>
        <div className="metric-card">
          <span>{t('metric.missingAi')}</span>
          <strong>{stats?.missingAiNotes ?? '-'}</strong>
        </div>
        <div className="metric-card">
          <span>{t('metric.errorVideos')}</span>
          <strong>{stats?.errorVideos ?? '-'}</strong>
        </div>
      </div>

      <section className="admin-section">
        <div className="admin-section-header">
          <h3>{t('header.statistics')}</h3>
        </div>

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
      </section>

      <section className="admin-section">
        <div className="admin-section-header">
          <h3>{t('header.processing')}</h3>
          <div className="admin-section-actions">
            <button disabled={busy} onClick={() => runAction(refreshDates, t('msg.dateRefreshQueued'))}>
              {t('header.missingDates')}
            </button>
            <button disabled={busy} onClick={() => runAction(refreshThumbnails, t('msg.thumbnailRefreshQueued'))}>
              {t('header.missingImages')}
            </button>
            <button
              disabled={busy}
              onClick={() => runAction(
                () => generateAiNotes(stats?.missingAiNotes || 20000),
                result => result?.existing
                  ? t('msg.aiBatchRunning', { jobId: result.job_id?.slice(0, 8) })
                  : t('msg.aiQueued', { count: result?.limit ?? stats?.missingAiNotes ?? '' })
              )}
            >
              {t('header.aiNotes')}
            </button>
          </div>
        </div>
        <div className="process-panel">
          <StatusLine
            title={t('label.fetcher')}
            queueSize={fetcherStatus?.fetch_active_size ?? fetcherStatus?.queue_size ?? 0}
            current={fetcherStatus?.current_task}
            onStop={() => runAction(() => stopProcessing('fetch'), t('msg.queueRefreshed'))}
          />
          <StatusLine
            title={t('label.aiWorker')}
            queueSize={fetcherStatus?.ai_active_size ?? fetcherStatus?.ai_queue_size ?? 0}
            current={fetcherStatus?.current_ai_task}
            onStop={() => runAction(() => stopProcessing('ai'), t('msg.queueRefreshed'))}
          />
          <StatusLine
            title={t('label.whisper')}
            queueSize={whisperStatus?.queue_size ?? 0}
            current={whisperStatus?.current_task}
            onStop={() => runAction(stopWhisper, t('msg.queueRefreshed'))}
          />
        </div>
        <JobQueuePanel jobs={jobs} busy={busy} onAction={runJobAction} />
      </section>

      <section className="admin-section">
        <div className="admin-section-header">
          <h3>{t('header.schedule')}</h3>
          <span>{scheduleCron} · {scheduleTimezone}</span>
        </div>
        <form className="schedule-form" onSubmit={saveSchedule}>
          <label>
            {t('label.dailyRefresh')}
            <input type="time" value={scheduleTime} onChange={e => setScheduleTime(e.target.value)} />
          </label>
          <label>
            {t('label.timezone')}
            <select value={scheduleTimezone} onChange={e => setScheduleTimezone(e.target.value)}>
              <option value="Europe/Budapest">Europe/Budapest</option>
              <option value="UTC">UTC</option>
              <option value="Europe/London">Europe/London</option>
              <option value="Europe/Berlin">Europe/Berlin</option>
              <option value="America/New_York">America/New_York</option>
            </select>
          </label>
          <button type="submit" disabled={busy}>{t('btn.save')}</button>
        </form>
      </section>

      <section className="admin-section">
        <div className="admin-section-header">
          <h3>{t('header.quickActions')}</h3>
        </div>
        <TopActions
          channels={channels}
          selectedChannel={selectedChannel}
          onChannelsChanged={onChannelsChanged}
        />
      </section>

      <ChannelAdminPanel
        channels={channels}
        onChanged={async () => {
          await onChannelsChanged();
          await loadAdminData();
        }}
      />
    </section>
  );
}
