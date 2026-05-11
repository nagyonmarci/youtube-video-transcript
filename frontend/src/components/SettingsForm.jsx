import { useT } from '../lib/i18n.jsx';

export default function SettingsForm({ appSettings, settingsDraft, settingsDirty, busy, onChange, onSubmit, onCancel }) {
  const { t } = useT();
  return (
    <section className="admin-section">
      <div className="admin-section-header">
        <div>
          <h3>{t('header.setup')}</h3>
          <span>
            {appSettings.ai_notes_auto ? t('label.aiAutoOn') : t('label.aiManualOnly')}
            {' · '}
            {appSettings.ollama_chat_model}
          </span>
        </div>
      </div>
      <form className="settings-form" onSubmit={onSubmit}>
        <label>
          {t('label.ollamaBaseUrl')}
          <input
            value={settingsDraft.ollama_base_url}
            onChange={e => onChange('ollama_base_url', e.target.value)}
            placeholder="http://host.docker.internal:11434"
          />
        </label>
        <label>
          {t('label.ollamaModel')}
          <input
            value={settingsDraft.ollama_chat_model}
            onChange={e => onChange('ollama_chat_model', e.target.value)}
            placeholder="gemma4:31b-mlx-bf16"
          />
        </label>
        <label>
          {t('label.ollamaTimeout')}
          <input
            type="number"
            min="30"
            value={settingsDraft.ollama_timeout}
            onChange={e => onChange('ollama_timeout', Number(e.target.value))}
          />
        </label>
        <label>
          {t('label.aiMaxChars')}
          <input
            type="number"
            min="1000"
            step="1000"
            value={settingsDraft.ai_notes_max_chars}
            onChange={e => onChange('ai_notes_max_chars', Number(e.target.value))}
          />
        </label>
        <label>
          {t('label.aiBatchLimit')}
          <input
            type="number"
            min="1"
            value={settingsDraft.ai_notes_batch_limit}
            onChange={e => onChange('ai_notes_batch_limit', Number(e.target.value))}
          />
        </label>
        <label>
          {t('label.aiMaxBatchLimit')}
          <input
            type="number"
            min="1"
            value={settingsDraft.ai_notes_max_batch_limit}
            onChange={e => onChange('ai_notes_max_batch_limit', Number(e.target.value))}
          />
        </label>
        <label>
          {t('label.aiBackfillYear')}
          <input
            type="number"
            min="2005"
            value={settingsDraft.ai_notes_year_backfill_year}
            onChange={e => onChange('ai_notes_year_backfill_year', Number(e.target.value))}
          />
        </label>
        <label>
          {t('label.aiBackfillBatch')}
          <input
            type="number"
            min="1"
            value={settingsDraft.ai_notes_year_backfill_batch_limit}
            onChange={e => onChange('ai_notes_year_backfill_batch_limit', Number(e.target.value))}
          />
        </label>
        <label>
          {t('label.aiBackfillTarget')}
          <input
            type="number"
            min="1"
            value={settingsDraft.ai_notes_year_backfill_target_active}
            onChange={e => onChange('ai_notes_year_backfill_target_active', Number(e.target.value))}
          />
        </label>
        <label>
          {t('label.aiBackfillInterval')}
          <input
            type="number"
            min="30"
            value={settingsDraft.ai_notes_year_backfill_interval_seconds}
            onChange={e => onChange('ai_notes_year_backfill_interval_seconds', Number(e.target.value))}
          />
        </label>
        <label>
          {t('label.aiJobCooldown')}
          <input
            type="number"
            min="0"
            max="3600"
            value={settingsDraft.ai_notes_job_cooldown_seconds}
            onChange={e => onChange('ai_notes_job_cooldown_seconds', Number(e.target.value))}
          />
        </label>
        <label className="settings-check">
          <input
            type="checkbox"
            checked={settingsDraft.ai_notes_worker_enabled}
            onChange={e => onChange('ai_notes_worker_enabled', e.target.checked)}
          />
          {t('label.aiWorkerEnabled')}
        </label>
        <label className="settings-check">
          <input
            type="checkbox"
            checked={settingsDraft.ai_notes_auto}
            onChange={e => onChange('ai_notes_auto', e.target.checked)}
          />
          {t('label.aiAutoAfterTranscript')}
        </label>
        <label className="settings-check">
          <input
            type="checkbox"
            checked={settingsDraft.ai_notes_year_backfill_enabled}
            onChange={e => onChange('ai_notes_year_backfill_enabled', e.target.checked)}
          />
          {t('label.aiYearBackfill')}
        </label>
        <div className="settings-actions">
          <button type="submit" disabled={busy || !settingsDirty}>{t('btn.save')}</button>
          <button type="button" disabled={busy || !settingsDirty} onClick={onCancel}>{t('btn.cancel')}</button>
        </div>
      </form>
    </section>
  );
}
