import { useEffect, useState } from 'react';
import { getAdminStats } from '../lib/directus.js';
import {
  deleteJob,
  generateAiNotes,
  getJobs,
  getSchedule,
  moveJob,
  pauseJob,
  refreshDates,
  resumeJob,
  startJob,
  stopProcessing,
  stopWhisper,
  updateSchedule,
} from '../lib/fetcher.js';
import ChannelAdminPanel from './ChannelAdminPanel.jsx';
import TopActions from './TopActions.jsx';

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
  const active = queueSize > 0 || Boolean(current?.type);
  return (
    <div className="process-line">
      <div>
        <h4>{title}</h4>
        <p>
          {active ? (
            <>
              <span>Sor: {queueSize}</span>
              {current?.phase && <span> · {current.phase}</span>}
              {current?.video && <span> · {current.video}</span>}
              {current?.video_id && !current?.video && <span> · {current.video_id}</span>}
            </>
          ) : (
            <span>Nincs futó feladat</span>
          )}
        </p>
      </div>
      <div className="process-actions">
        <span className={`badge ${active ? 'badge-processing' : 'badge-done'}`}>
          {active ? 'Fut' : 'Üres'}
        </span>
        {active && onStop && <button className="danger" onClick={onStop}>Stop</button>}
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

const JOB_STATUS_LABELS = {
  queued: 'Sorban',
  running: 'Fut',
  paused: 'Szünetel',
  done: 'Kész',
  error: 'Hiba',
  cancelled: 'Leállítva',
};

function JobQueuePanel({ jobs, onAction, busy }) {
  const visibleJobs = jobs.filter(job => job.status !== 'done').slice(0, 80);
  return (
    <div className="job-table-wrap">
      <table className="job-table">
        <thead>
          <tr>
            <th>Sor</th>
            <th>Feladat</th>
            <th>Állapot</th>
            <th>Létrehozva</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {visibleJobs.map(job => {
            const running = job.status === 'running';
            const paused = job.status === 'paused';
            const reorderable = ['queued', 'paused'].includes(job.status);
            return (
              <tr key={job.id}>
                <td>
                  <span className={`badge ${job.queue === 'ai' ? 'badge-whisper' : 'badge-processing'}`}>
                    {job.queue}
                  </span>
                </td>
                <td>
                  <div className="job-label">{job.label || job.type}</div>
                  {job.error_message && <div className="job-error">{job.error_message}</div>}
                </td>
                <td>
                  <span className={`badge badge-${job.status}`}>
                    {JOB_STATUS_LABELS[job.status] || job.status}
                  </span>
                </td>
                <td>{formatJobTime(job.created_at)}</td>
                <td>
                  <div className="job-actions">
                    <button disabled={busy || !reorderable} onClick={() => onAction(() => moveJob(job.id, 'up'))}>Fel</button>
                    <button disabled={busy || !reorderable} onClick={() => onAction(() => moveJob(job.id, 'down'))}>Le</button>
                    {paused ? (
                      <button disabled={busy} onClick={() => onAction(() => resumeJob(job.id))}>Folytat</button>
                    ) : (
                      <button disabled={busy || running || ['done', 'cancelled'].includes(job.status)} onClick={() => onAction(() => pauseJob(job.id))}>Pause</button>
                    )}
                    <button disabled={busy || running} onClick={() => onAction(() => startJob(job.id))}>Indít</button>
                    <button className="danger" disabled={busy} onClick={() => onAction(() => deleteJob(job.id))}>Töröl</button>
                  </div>
                </td>
              </tr>
            );
          })}
          {visibleJobs.length === 0 && (
            <tr>
              <td colSpan="5" className="admin-empty">A feldolgozási sor üres.</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
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
  const [stats, setStats] = useState(null);
  const [scheduleCron, setScheduleCron] = useState('0 7 * * *');
  const [scheduleTime, setScheduleTime] = useState('07:00');
  const [scheduleTimezone, setScheduleTimezone] = useState('Europe/Budapest');
  const [jobs, setJobs] = useState([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  async function loadAdminData() {
    try {
      const [nextStats, schedule, jobData] = await Promise.all([
        getAdminStats(),
        getSchedule(),
        getJobs(),
      ]);
      setStats(nextStats);
      setJobs(jobData.jobs || []);
      setScheduleCron(schedule.cron || '0 7 * * *');
      setScheduleTime(cronToDailyTime(schedule.cron || '0 7 * * *'));
      setScheduleTimezone(schedule.timezone || 'Europe/Budapest');
    } catch (e) {
      setMsg({ text: 'Admin adatok betöltési hiba: ' + e.message, isError: true });
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
      await action();
      showMsg(successText);
      await Promise.all([loadAdminData(), onStatusChanged?.()]);
    } catch (e) {
      showMsg('Hiba: ' + e.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function runJobAction(action) {
    await runAction(action, 'Sor frissítve');
  }

  async function saveSchedule(e) {
    e.preventDefault();
    await runAction(
      () => updateSchedule(dailyTimeToCron(scheduleTime), scheduleTimezone),
      'Ütemezés mentve'
    );
  }

  const channelCount = channels.length;
  const totalChannelVideos = channels.reduce((sum, ch) => sum + (ch.video_count || 0), 0);

  return (
    <section className="admin-dashboard">
      <div className="view-header">
        <div>
          <h2>Admin</h2>
          <p>{channelCount} csatorna · {totalChannelVideos} videó</p>
        </div>
      </div>

      {msg && <div className={`status-msg ${msg.isError ? 'status-error' : 'status-success'}`}>{msg.text}</div>}

      <div className="metric-grid">
        <div className="metric-card">
          <span>Mai videók</span>
          <strong>{stats?.todayVideos ?? '-'}</strong>
        </div>
        <div className="metric-card">
          <span>Összes videó</span>
          <strong>{stats?.totalVideos ?? totalChannelVideos}</strong>
        </div>
        <div className="metric-card">
          <span>Transzkript hiány</span>
          <strong>{stats?.missingTranscripts ?? '-'}</strong>
        </div>
        <div className="metric-card">
          <span>AI jegyzet hiány</span>
          <strong>{stats?.missingAiNotes ?? '-'}</strong>
        </div>
        <div className="metric-card">
          <span>Hibás videók</span>
          <strong>{stats?.errorVideos ?? '-'}</strong>
        </div>
      </div>

      <section className="admin-section">
        <div className="admin-section-header">
          <h3>Feldolgozás</h3>
          <div className="admin-section-actions">
            <button disabled={busy} onClick={() => runAction(refreshDates, 'Dátum frissítés sorba állítva')}>
              Hiányzó dátumok
            </button>
            <button disabled={busy} onClick={() => runAction(() => generateAiNotes(10), 'AI jegyzetek sorba állítva')}>
              Hiányzó AI
            </button>
          </div>
        </div>
        <div className="process-panel">
          <StatusLine
            title="Fetcher"
            queueSize={fetcherStatus?.queue_size ?? 0}
            current={fetcherStatus?.current_task}
            onStop={() => runAction(stopProcessing, 'Fetcher leállítva')}
          />
          <StatusLine
            title="AI jegyzetek"
            queueSize={fetcherStatus?.ai_queue_size ?? 0}
            current={fetcherStatus?.current_ai_task}
            onStop={() => runAction(stopProcessing, 'AI sor leállítva')}
          />
          <StatusLine
            title="Whisper"
            queueSize={whisperStatus?.queue_size ?? 0}
            current={whisperStatus?.current_task}
            onStop={() => runAction(stopWhisper, 'Whisper leállítva')}
          />
        </div>
        <JobQueuePanel jobs={jobs} busy={busy} onAction={runJobAction} />
      </section>

      <section className="admin-section">
        <div className="admin-section-header">
          <h3>Ütemezés</h3>
          <span>{scheduleCron} · {scheduleTimezone}</span>
        </div>
        <form className="schedule-form" onSubmit={saveSchedule}>
          <label>
            Napi frissítés
            <input type="time" value={scheduleTime} onChange={e => setScheduleTime(e.target.value)} />
          </label>
          <label>
            Időzóna
            <select value={scheduleTimezone} onChange={e => setScheduleTimezone(e.target.value)}>
              <option value="Europe/Budapest">Europe/Budapest</option>
              <option value="UTC">UTC</option>
              <option value="Europe/London">Europe/London</option>
              <option value="Europe/Berlin">Europe/Berlin</option>
              <option value="America/New_York">America/New_York</option>
            </select>
          </label>
          <button type="submit" disabled={busy}>Mentés</button>
        </form>
      </section>

      <section className="admin-section">
        <div className="admin-section-header">
          <h3>Gyors műveletek</h3>
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
