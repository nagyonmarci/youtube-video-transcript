import { useT } from '../lib/i18n.jsx';

export default function ScheduleForm({ scheduleTime, scheduleTimezone, busy, onTimeChange, onTimezoneChange, onSubmit }) {
  const { t } = useT();
  return (
    <form className="schedule-form" onSubmit={onSubmit}>
      <label>
        {t('label.dailyRefresh')}
        <input type="time" value={scheduleTime} onChange={e => onTimeChange(e.target.value)} />
      </label>
      <label>
        {t('label.timezone')}
        <select value={scheduleTimezone} onChange={e => onTimezoneChange(e.target.value)}>
          <option value="Europe/Budapest">Europe/Budapest</option>
          <option value="UTC">UTC</option>
          <option value="Europe/London">Europe/London</option>
          <option value="Europe/Berlin">Europe/Berlin</option>
          <option value="America/New_York">America/New_York</option>
        </select>
      </label>
      <button type="submit" disabled={busy}>{t('btn.save')}</button>
    </form>
  );
}
