import { useEffect, useRef, useState } from 'react';
import { getAdminStats, getChannelCoverage, getMonthlyVideoCounts } from '../lib/directus.js';
import {
  deleteJob,
  generateAiNotes,
  getAppSettings,
  getJobs,
  getResources,
  getSchedule,
  openResourceStream,
  moveJob,
  pauseJob,
  refreshDates,
  refreshThumbnails,
  resumeJob,
  startJob,
  resumeProcessing,
  stopProcessing,
  stopWhisper,
  updateAppSettings,
  updateSchedule,
} from '../lib/fetcher.js';
import ChannelAdminPanel from './ChannelAdminPanel.jsx';
import TopActions from './TopActions.jsx';
import ScheduleForm from './ScheduleForm.jsx';
import SettingsForm from './SettingsForm.jsx';
import StatisticsPanel from './StatisticsPanel.jsx';
import { useT } from '../lib/i18n.jsx';
import { keepIfSame } from '../lib/dataUtils.js';
import { cronToDailyTime, dailyTimeToCron } from '../lib/scheduleUtils.js';
import { useMessage } from '../lib/useMessage.js';
import { POLL_INTERVAL_MS, DEFAULT_CRON, DEFAULT_CRON_TIME, DEFAULT_TIMEZONE } from '../lib/constants.js';

function formatProgress(current, total) {
  const cur = Number(current || 0);
  const max = Number(total || 0);
  if (!cur || !max) return '';
  return `${cur}/${max} (${Math.round((cur / max) * 100)}%)`;
}

function normalizeSettings(settings = {}) {
  return {
    ollama_base_url: settings.ollama_base_url || 'http://host.docker.internal:11434',
    ollama_chat_model: settings.ollama_chat_model || 'gemma4:31b-mlx-bf16',
    ollama_timeout: Number(settings.ollama_timeout ?? 600),
    ai_notes_max_chars: Number(settings.ai_notes_max_chars ?? 45000),
    ai_notes_auto: Boolean(settings.ai_notes_auto),
    ai_notes_batch_limit: Number(settings.ai_notes_batch_limit ?? 10),
    ai_notes_max_batch_limit: Number(settings.ai_notes_max_batch_limit ?? 20000),
    ai_notes_year_backfill_enabled: Boolean(settings.ai_notes_year_backfill_enabled),
    ai_notes_year_backfill_year: Number(settings.ai_notes_year_backfill_year ?? new Date().getFullYear()),
    ai_notes_year_backfill_batch_limit: Number(settings.ai_notes_year_backfill_batch_limit ?? 50),
    ai_notes_year_backfill_target_active: Number(settings.ai_notes_year_backfill_target_active ?? 100),
    ai_notes_year_backfill_interval_seconds: Number(settings.ai_notes_year_backfill_interval_seconds ?? 300),
    ai_notes_year_backfill_idle_seconds: Number(settings.ai_notes_year_backfill_idle_seconds ?? 60),
    ai_notes_worker_enabled: settings.ai_notes_worker_enabled ?? true,
    ai_notes_job_cooldown_seconds: Number(settings.ai_notes_job_cooldown_seconds ?? 0),
    ai_notes_quick_enabled: settings.ai_notes_quick_enabled ?? true,
    ollama_quick_model: settings.ollama_quick_model || 'qwen3:4b',
    ollama_quick_timeout: Number(settings.ollama_quick_timeout ?? 120),
    ai_provider: settings.ai_provider || 'ollama',
    ai_cloud_model: settings.ai_cloud_model || 'claude-opus-4-7',
    anthropic_api_key: settings.anthropic_api_key || '',
    openai_api_key: settings.openai_api_key || '',
    openai_base_url: settings.openai_base_url || 'https://api.openai.com/v1',
  };
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!bytes) return '-';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / (1024 ** index)).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function getAiStatus({ appSettings, fetcherStatus, jobs, missingAiNotes, t }) {
  const aiQueue = fetcherStatus?.queues?.ai || {};
  const aiQueueSize = Number(aiQueue.queued ?? fetcherStatus?.ai_queue_size ?? 0);
  const actualRunning = Number(aiQueue.running ?? 0);
  const workerConcurrency = Number(fetcherStatus?.workers?.ai_concurrency ?? fetcherStatus?.resources?.ai_worker_concurrency ?? 0);
  const currentAiTask = fetcherStatus?.current_ai_task;
  const aiJobs = jobs.filter(job => job.queue === 'ai' && !['done', 'cancelled'].includes(job.status));
  const runningJobs = actualRunning || aiJobs.filter(job => job.status === 'running').length;
  const queuedJobs = aiQueueSize || aiJobs.filter(job => job.status === 'queued').length;
  const pausedJobs = aiJobs.filter(job => job.status === 'paused').length;
  const isActive = Boolean(currentAiTask?.type) || runningJobs > 0;
  const missingCount = Number(missingAiNotes || 0);

  if (isActive) {
    return {
      tone: 'running',
      title: t('aiStatus.runningTitle'),
      detail: t('aiStatus.runningDetail', {
        queued: queuedJobs,
        running: runningJobs,
        workers: workerConcurrency || 1,
        task: currentAiTask?.phase || currentAiTask?.video || currentAiTask?.video_id || t('aiStatus.currentTaskFallback'),
      }),
    };
  }

  if (!appSettings.ai_notes_worker_enabled) {
    return {
      tone: 'paused',
      title: t('aiStatus.workerOffTitle'),
      detail: t('aiStatus.workerOffDetail', { count: missingCount }),
    };
  }

  if (pausedJobs > 0) {
    return {
      tone: 'paused',
      title: t('aiStatus.pausedTitle'),
      detail: t('aiStatus.pausedDetail', { count: pausedJobs }),
    };
  }

  if (queuedJobs > 0) {
    return {
      tone: 'queued',
      title: t('aiStatus.queuedTitle'),
      detail: t('aiStatus.queuedDetail', { count: queuedJobs }),
    };
  }

  if (missingCount <= 0) {
    return {
      tone: 'idle',
      title: t('aiStatus.completeTitle'),
      detail: t('aiStatus.completeDetail'),
    };
  }

  if (!appSettings.ai_notes_auto && !appSettings.ai_notes_year_backfill_enabled) {
    return {
      tone: 'manual',
      title: t('aiStatus.manualTitle'),
      detail: t('aiStatus.manualDetail', { count: missingCount }),
    };
  }

  if (appSettings.ai_notes_year_backfill_enabled) {
    return {
      tone: 'waiting',
      title: t('aiStatus.backfillTitle'),
      detail: t('aiStatus.backfillDetail', {
        count: missingCount,
        interval: appSettings.ai_notes_year_backfill_interval_seconds,
      }),
    };
  }

  return {
    tone: 'waiting',
    title: t('aiStatus.autoTitle'),
    detail: t('aiStatus.autoDetail', { count: missingCount }),
  };
}

function StatusLine({ title, queueSize, queueStats, workerCount, current, onStop, onStart }) {
  const { t } = useT();
  const queued = Number(queueStats?.queued ?? queueSize ?? 0);
  const running = Number(queueStats?.running ?? (current?.type ? 1 : 0));
  const paused = Number(queueStats?.paused ?? 0);
  const active = queued > 0 || running > 0 || Boolean(current?.type);
  const progressText = formatProgress(current?.progress_current, current?.progress_total);
  const runtimeText = formatDuration(current?.duration_seconds);
  return (
    <div className="process-line">
      <div>
        <h4>{title}</h4>
        <p>
          {active ? (
            <>
              <span>{t('label.queueBreakdown', { queued, running, paused })}</span>
              {workerCount !== undefined && <span> · {t('label.workerSlots', { count: workerCount })}</span>}
              {current?.phase && <span> · {current.phase}</span>}
              {current?.video && <span> · {current.video}</span>}
              {current?.video_id && !current?.video && <span> · {current.video_id}</span>}
              {progressText && <span> · {progressText}</span>}
              {runtimeText && <span> · {t('label.runningFor', { duration: runtimeText })}</span>}
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
        {onStart && <button onClick={onStart}>{t('btn.start')}</button>}
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

function formatDuration(seconds) {
  const total = Number(seconds || 0);
  if (!total) return '';
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours) return `${hours}h ${minutes}m ${secs}s`;
  if (minutes) return `${minutes}m ${secs}s`;
  return `${secs}s`;
}

function jobRuntimeSeconds(job) {
  if (job.duration_seconds) return Number(job.duration_seconds);
  if (!job.started_at) return 0;
  const end = job.finished_at ? new Date(job.finished_at) : new Date();
  return Math.max(0, Math.round((end.getTime() - new Date(job.started_at).getTime()) / 1000));
}

function formatMetricSeconds(value) {
  if (value === null || value === undefined || value === '') return '-';
  const number = Number(value);
  if (!Number.isFinite(number)) return '-';
  return `${number.toFixed(number >= 10 ? 1 : 2)}s`;
}

function aiBottleneck(metrics) {
  if (!metrics) return '';
  const phases = [
    ['load', Number(metrics.ollama_load_seconds || 0)],
    ['firstToken', Number(metrics.first_token_seconds || 0)],
    ['prompt', Number(metrics.prompt_eval_seconds || 0)],
    ['generate', Number(metrics.eval_seconds || 0)],
    ['parse', Number(metrics.json_parse_seconds || 0)],
  ].filter(([, value]) => value > 0);
  if (!phases.length) return '';
  const [phase, seconds] = phases.sort((a, b) => b[1] - a[1])[0];
  return { phase, seconds };
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
              const runtimeText = formatDuration(jobRuntimeSeconds(job));
              const bottleneck = job.queue === 'ai' ? aiBottleneck(job.metrics) : null;
              return (
                <tr key={job.id}>
                  <td>
                    <span className={`badge ${job.queue === 'ai' ? 'badge-whisper' : 'badge-processing'}`}>
                      {job.queue}
                    </span>
                  </td>
                  <td>
                    <div className="job-label">{job.label || job.type}</div>
                    {runtimeText && (
                      <div className="job-progress-text">
                        {running ? t('label.runningFor', { duration: runtimeText }) : t('label.duration', { duration: runtimeText })}
                      </div>
                    )}
                    {bottleneck && (
                      <div className="job-progress-text">
                        {t('label.aiBottleneck', {
                          phase: t(`aiMetric.${bottleneck.phase}`),
                          duration: formatMetricSeconds(bottleneck.seconds),
                        })}
                      </div>
                    )}
                    {job.queue === 'ai' && job.metrics && (
                      <div className="job-progress-text">
                        {t('label.aiMetrics', {
                          first: formatMetricSeconds(job.metrics.first_token_seconds),
                          prompt: formatMetricSeconds(job.metrics.prompt_eval_seconds),
                          generate: formatMetricSeconds(job.metrics.eval_seconds),
                          rate: job.metrics.eval_tokens_per_second ? `${job.metrics.eval_tokens_per_second} tok/s` : '-',
                        })}
                      </div>
                    )}
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
  const [scheduleCron, setScheduleCron] = useState(DEFAULT_CRON);
  const [scheduleTime, setScheduleTime] = useState(DEFAULT_CRON_TIME);
  const [scheduleTimezone, setScheduleTimezone] = useState(DEFAULT_TIMEZONE);
  const [appSettings, setAppSettings] = useState(() => normalizeSettings());
  const [settingsDraft, setSettingsDraft] = useState(() => normalizeSettings());
  const [settingsDirty, setSettingsDirty] = useState(false);
  const settingsDirtyRef = useRef(false);
  const [jobs, setJobs] = useState([]);
  const [resourceSnapshot, setResourceSnapshot] = useState(null);
  const [busy, setBusy] = useState(false);
  const { msg, showMsg } = useMessage();

  async function loadAdminData() {
    try {
      const [nextStats, schedule, jobData, cov, monthly, settings] = await Promise.all([
        getAdminStats(),
        getSchedule(),
        getJobs(),
        getChannelCoverage(),
        getMonthlyVideoCounts(),
        getAppSettings(),
      ]);
      const nextCron = schedule.cron || DEFAULT_CRON;
      const nextTime = cronToDailyTime(nextCron);
      const nextTimezone = schedule.timezone || DEFAULT_TIMEZONE;
      setStats(prev => keepIfSame(prev, nextStats));
      setJobs(prev => keepIfSame(prev, jobData.jobs || []));
      setCoverage(cov);
      setMonthlyData(monthly);
      setScheduleCron(prev => (prev === nextCron ? prev : nextCron));
      setScheduleTime(prev => (prev === nextTime ? prev : nextTime));
      setScheduleTimezone(prev => (prev === nextTimezone ? prev : nextTimezone));
      const normalizedSettings = normalizeSettings(settings);
      setAppSettings(normalizedSettings);
      if (!settingsDirtyRef.current) setSettingsDraft(normalizedSettings);
    } catch (e) {
      showMsg(t('msg.errAdmin', { error: e.message }), true);
    }
  }

  useEffect(() => {
    loadAdminData();
    const interval = setInterval(loadAdminData, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    let alive = true;
    let fallbackInterval = null;
    let stream = null;

    async function loadResources() {
      try {
        const resources = await getResources();
        if (alive) setResourceSnapshot(resources);
      } catch {
        if (alive) setResourceSnapshot(prev => prev);
      }
    }

    function startFallbackPolling() {
      if (fallbackInterval) return;
      loadResources();
      fallbackInterval = setInterval(loadResources, 2000);
    }

    if (typeof EventSource === 'undefined') {
      startFallbackPolling();
    } else {
      stream = openResourceStream();
      stream.onmessage = event => {
        try {
          const resources = JSON.parse(event.data);
          if (alive) setResourceSnapshot(resources);
        } catch {
          if (alive) setResourceSnapshot(prev => prev);
        }
      };
      stream.onerror = () => {
        stream?.close();
        stream = null;
        startFallbackPolling();
      };
    }

    return () => {
      alive = false;
      stream?.close();
      if (fallbackInterval) clearInterval(fallbackInterval);
    };
  }, []);

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

  function updateSettingsDraft(field, value) {
    settingsDirtyRef.current = true;
    setSettingsDirty(true);
    setSettingsDraft(prev => ({ ...prev, [field]: value }));
  }

  async function saveAppSettings(e) {
    e.preventDefault();
    await runAction(
      () => updateAppSettings(settingsDraft),
      t('msg.settingsUpdated')
    );
    settingsDirtyRef.current = false;
    setSettingsDirty(false);
  }

  const channelCount = channels.length;
  const totalChannelVideos = channels.reduce((sum, ch) => sum + (ch.video_count || 0), 0);
  const displayedTotalVideos = stats?.totalVideos ?? totalChannelVideos;
  const missingAiNotes = Number(stats?.missingAiNotes || 0);
  const aiStatus = getAiStatus({ appSettings, fetcherStatus, jobs, missingAiNotes, t });
  const aiBatchLimit = Number(appSettings.ai_notes_batch_limit || 10);
  const aiCanStart = missingAiNotes > 0;
  const resourceStatus = resourceSnapshot || fetcherStatus?.resources || {};
  const ollamaStatus = resourceStatus.ollama || {};
  const ollamaModels = ollamaStatus.models || [];
  const primaryOllamaModel = ollamaModels[0];
  const processorPercent = primaryOllamaModel?.processor_percent;
  const sampledAt = ollamaStatus.sampled_at ? new Date(ollamaStatus.sampled_at).toLocaleTimeString('hu-HU') : '-';
  const fetchQueue = fetcherStatus?.queues?.fetch || {};
  const quickQueue = fetcherStatus?.queues?.quick || {};
  const aiQueue = fetcherStatus?.queues?.ai || resourceStatus.ai_queue || {};
  const fetchWorkers = fetcherStatus?.workers?.fetch_concurrency;
  const quickWorkers = fetcherStatus?.workers?.quick_concurrency;
  const aiWorkers = fetcherStatus?.workers?.ai_concurrency ?? resourceStatus.ai_worker_concurrency;

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

      <StatisticsPanel
        stats={stats}
        coverage={coverage}
        channels={channels}
        monthlyData={monthlyData}
      />

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
                () => generateAiNotes(),
                result => result?.existing
                  ? t('msg.aiBatchRunning', { jobId: result.job_id?.slice(0, 8) })
                  : t('msg.aiQueued', { count: result?.limit ?? aiBatchLimit })
              )}
            >
              {t('header.aiNotes')}
            </button>
          </div>
        </div>

        {/* Fetch queue */}
        <div className="queue-section">
          <StatusLine
            title={t('label.fetcher')}
            queueSize={fetcherStatus?.queue_size ?? 0}
            queueStats={fetchQueue}
            workerCount={fetchWorkers}
            current={fetcherStatus?.current_task}
            onStop={() => runAction(() => stopProcessing('fetch'), t('msg.queueRefreshed'))}
            onStart={() => runAction(() => resumeProcessing('fetch'), t('msg.queueRefreshed'))}
          />
          <JobQueuePanel jobs={jobs.filter(j => j.queue === 'fetch')} busy={busy} onAction={runJobAction} />
        </div>

        {/* Quick Notes queue */}
        <div className="queue-section">
          <StatusLine
            title={t('label.quickWorker')}
            queueSize={fetcherStatus?.quick_queue_size ?? 0}
            queueStats={quickQueue}
            workerCount={quickWorkers}
            current={fetcherStatus?.current_quick_task}
            onStop={() => runAction(() => stopProcessing('quick'), t('msg.queueRefreshed'))}
            onStart={() => runAction(() => resumeProcessing('quick'), t('msg.queueRefreshed'))}
          />
          <JobQueuePanel jobs={jobs.filter(j => j.queue === 'quick')} busy={busy} onAction={runJobAction} />
        </div>

        {/* AI Notes queue */}
        <div className="queue-section">
          <StatusLine
            title={t('label.aiWorker')}
            queueSize={fetcherStatus?.ai_queue_size ?? 0}
            queueStats={aiQueue}
            workerCount={aiWorkers}
            current={fetcherStatus?.current_ai_task}
            onStop={() => runAction(() => stopProcessing('ai'), t('msg.queueRefreshed'))}
            onStart={() => runAction(() => resumeProcessing('ai'), t('msg.queueRefreshed'))}
          />
          <div className={`ai-status-panel ai-status-${aiStatus.tone}`}>
            <div className="ai-status-main">
              <div className="ai-status-kicker">{t('header.aiStatus')}</div>
              <strong>{aiStatus.title}</strong>
              <p>{aiStatus.detail}</p>
            </div>
            <div className="ai-status-side">
              <span className="ai-status-pill">{t('metric.missingAi')}: {missingAiNotes}</span>
              <span className="ai-status-pill">{t('label.queueBreakdown', {
                queued: Number(aiQueue.queued ?? 0),
                running: Number(aiQueue.running ?? 0),
                paused: Number(aiQueue.paused ?? 0),
              })}</span>
              <span className="ai-status-pill">{t('label.aiBatchLimit')}: {aiBatchLimit}</span>
              <button
                disabled={busy || !aiCanStart}
                onClick={() => runAction(
                  () => generateAiNotes(),
                  result => result?.existing
                    ? t('msg.aiBatchRunning', { jobId: result.job_id?.slice(0, 8) })
                    : t('msg.aiQueued', { count: result?.limit ?? aiBatchLimit })
                )}
              >
                {t('btn.generateMissing')}
              </button>
            </div>
          </div>
          <JobQueuePanel jobs={jobs.filter(j => j.queue === 'ai')} busy={busy} onAction={runJobAction} />
        </div>

        {/* Whisper + Resource cards */}
        <div className="queue-section">
          <StatusLine
            title={t('label.whisper')}
            queueSize={whisperStatus?.queue_size ?? 0}
            current={whisperStatus?.current_task}
            onStop={() => runAction(stopWhisper, t('msg.queueRefreshed'))}
          />
        </div>
        <div className="resource-panel">
          <div className="resource-card">
            <span>{t('resource.ollama')}</span>
            <strong>{ollamaStatus.online ? t('status.running') : t('status.empty')}</strong>
            <p>{ollamaStatus.online ? (primaryOllamaModel?.name || t('resource.noLoadedModel')) : (ollamaStatus.error || t('resource.notAvailable'))}</p>
            <small>{t('resource.refreshedAt', { time: sampledAt })}</small>
          </div>
          <div className="resource-card">
            <span>{t('resource.gpu')}</span>
            <strong>{processorPercent == null ? '-' : `${processorPercent}%`}</strong>
            <p>{primaryOllamaModel ? t('resource.vramUsage', {
              used: formatBytes(primaryOllamaModel.size_vram),
              total: formatBytes(primaryOllamaModel.size),
            }) : t('resource.noLoadedModel')}</p>
            <small>{t('resource.realtimeHint')}</small>
          </div>
          <div className="resource-card">
            <span>{t('resource.aiWorker')}</span>
            <strong>{resourceStatus.ai_worker_enabled ? t('status.running') : t('status.paused')}</strong>
            <p>{t('resource.workerDetails', {
              workers: aiWorkers ?? 0,
              queued: Number(aiQueue.queued ?? 0),
              running: Number(aiQueue.running ?? 0),
            })}</p>
            <small>{t('resource.cooldown', { seconds: resourceStatus.ai_job_cooldown_seconds ?? appSettings.ai_notes_job_cooldown_seconds })}</small>
          </div>
        </div>
      </section>

      <ScheduleForm
        scheduleCron={scheduleCron}
        scheduleTime={scheduleTime}
        scheduleTimezone={scheduleTimezone}
        busy={busy}
        onTimeChange={setScheduleTime}
        onTimezoneChange={setScheduleTimezone}
        onSubmit={saveSchedule}
      />

      <SettingsForm
        appSettings={appSettings}
        settingsDraft={settingsDraft}
        settingsDirty={settingsDirty}
        busy={busy}
        onChange={updateSettingsDraft}
        onSubmit={saveAppSettings}
        onCancel={() => {
          settingsDirtyRef.current = false;
          setSettingsDirty(false);
          setSettingsDraft(appSettings);
        }}
      />

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
