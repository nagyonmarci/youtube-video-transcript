import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import type { Markmap } from 'markmap-view';
import { videoToTxt, videoToMd, videoToObsidianMd, obsidianFilename, videoToMarkmapMd, markmapFilename, downloadFile, sanitizeFilename } from '../lib/export.ts';
import { updateVideoFields } from '../lib/directus.ts';
import { useT } from '../lib/i18n.tsx';
import { formatDuration, formatDate } from '../lib/formatUtils.ts';
import type { SelectedVideo } from '../types.ts';

function renderList(items: string[] | null | undefined) {
  if (!Array.isArray(items) || items.length === 0) return null;
  return (
    <ul style={{ margin: '0.35rem 0 0.8rem', paddingLeft: '1.2rem', color: '#ddd', lineHeight: 1.55 }}>
      {items.map((item, idx) => <li key={idx}>{item}</li>)}
    </ul>
  );
}

interface AiEditDraft {
  summary: string;
  topics: string;
  takeaways: string;
  questions: string;
}

interface TranscriptModalProps {
  video: SelectedVideo;
  onClose: () => void;
  onVideoUpdated?: () => void;
}

export default function TranscriptModal({ video, onClose, onVideoUpdated }: TranscriptModalProps) {
  const { t } = useT();
  const [showTimed, setShowTimed] = useState(false);
  const [activeTab, setActiveTab] = useState('transcript');
  const [localVideo, setLocalVideo] = useState<SelectedVideo | null>(video);
  const [editingQuick, setEditingQuick] = useState(false);
  const [quickEdit, setQuickEdit] = useState('');
  const [quickSaving, setQuickSaving] = useState(false);
  const [quickSaveMsg, setQuickSaveMsg] = useState<string | null>(null);
  const [editingAi, setEditingAi] = useState(false);
  const [aiEdit, setAiEdit] = useState<AiEditDraft>({ summary: '', topics: '', takeaways: '', questions: '' });
  const [aiSaving, setAiSaving] = useState(false);
  const [aiSaveMsg, setAiSaveMsg] = useState<string | null>(null);
  const [editingTranscript, setEditingTranscript] = useState(false);
  const [transcriptEdit, setTranscriptEdit] = useState('');
  const [transcriptSaving, setTranscriptSaving] = useState(false);
  const svgRef = useRef<SVGSVGElement>(null);
  const markmapRef = useRef<Markmap | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => { setLocalVideo(video); }, [video]);

  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null;
    closeButtonRef.current?.focus();
    return () => previousFocus?.focus();
  }, []);

  useEffect(() => {
    const handler = (e: globalThis.KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  function handleDialogKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key !== 'Tab') return;
    const focusable = dialogRef.current?.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
    );
    if (!focusable || focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.shiftKey) {
      if (document.activeElement === first) { e.preventDefault(); last.focus(); }
    } else {
      if (document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  }

  useEffect(() => {
    if (activeTab !== 'mindmap' || !svgRef.current || !localVideo) return;
    let cancelled = false;
    (async () => {
      const [{ Transformer }, { Markmap }] = await Promise.all([
        import('markmap-lib'),
        import('markmap-view'),
      ]);
      if (cancelled || !svgRef.current || !localVideo) return;
      const { root } = new Transformer().transform(videoToMarkmapMd(localVideo));
      svgRef.current.innerHTML = '';
      markmapRef.current = Markmap.create(svgRef.current, { duration: 0 }, root);
    })();
    return () => { cancelled = true; };
  }, [activeTab, video]);

  function startEditQuick() {
    if (!localVideo) return;
    setQuickEdit(localVideo.quick_summary || '');
    setEditingQuick(true);
    setQuickSaveMsg(null);
  }

  async function handleSaveQuick() {
    if (!localVideo) return;
    setQuickSaving(true);
    setQuickSaveMsg(null);
    try {
      const trimmed = quickEdit.trim();
      await updateVideoFields(localVideo.id, { quick_summary: trimmed });
      setLocalVideo(prev => prev && { ...prev, quick_summary: trimmed });
      setEditingQuick(false);
      setQuickSaveMsg(t('msg.saved'));
      setTimeout(() => setQuickSaveMsg(null), 2500);
      onVideoUpdated?.();
    } catch (err) {
      setQuickSaveMsg(t('msg.errGeneric', { error: (err as Error).message }));
    } finally {
      setQuickSaving(false);
    }
  }

  function startEditAi() {
    if (!localVideo) return;
    setAiEdit({
      summary: localVideo.summary || '',
      topics: Array.isArray(localVideo.topics) ? localVideo.topics.join('\n') : (localVideo.topics || ''),
      takeaways: Array.isArray(localVideo.takeaways) ? localVideo.takeaways.join('\n') : (localVideo.takeaways || ''),
      questions: Array.isArray(localVideo.questions) ? localVideo.questions.join('\n') : (localVideo.questions || ''),
    });
    setEditingAi(true);
    setAiSaveMsg(null);
  }

  async function handleSaveAi() {
    if (!localVideo) return;
    setAiSaving(true);
    setAiSaveMsg(null);
    const fields = {
      summary: aiEdit.summary.trim(),
      topics: aiEdit.topics.split('\n').map(s => s.trim()).filter(Boolean),
      takeaways: aiEdit.takeaways.split('\n').map(s => s.trim()).filter(Boolean),
      questions: aiEdit.questions.split('\n').map(s => s.trim()).filter(Boolean),
    };
    try {
      await updateVideoFields(localVideo.id, fields);
      setLocalVideo(prev => prev && { ...prev, ...fields });
      setEditingAi(false);
      setAiSaveMsg(t('msg.saved'));
      setTimeout(() => setAiSaveMsg(null), 2500);
      onVideoUpdated?.();
    } catch (err) {
      setAiSaveMsg(t('msg.errGeneric', { error: (err as Error).message }));
    } finally {
      setAiSaving(false);
    }
  }

  async function handleSaveTranscript() {
    if (!localVideo) return;
    setTranscriptSaving(true);
    try {
      const fields = showTimed
        ? { transcript_timed: transcriptEdit }
        : { transcript: transcriptEdit };
      await updateVideoFields(localVideo.id, fields);
      setLocalVideo(prev => prev && { ...prev, ...fields });
      setEditingTranscript(false);
      onVideoUpdated?.();
    } catch (err) {
      alert(t('msg.errSave', { error: (err as Error).message }));
    } finally {
      setTranscriptSaving(false);
    }
  }

  if (!localVideo) return null;
  const visibleTranscript = showTimed && localVideo.transcript_timed ? localVideo.transcript_timed : localVideo.transcript;
  const hasTimedTranscript = Boolean(localVideo.transcript_timed);
  const hasMindmap = Boolean(localVideo.obsidian_note || localVideo.summary || localVideo.critique);

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
      role="presentation"
      style={{
        position: 'fixed', inset: 0,
        background: 'rgba(0,0,0,0.75)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        zIndex: 1000, padding: '1rem',
      }}
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="transcript-modal-title"
        onKeyDown={handleDialogKeyDown}
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
            <div style={{ display: 'flex', gap: '0.8rem', minWidth: 0 }}>
              {video.thumbnail_url && (
                <img
                  src={video.thumbnail_url}
                  alt=""
                  style={{ width: '128px', aspectRatio: '16 / 9', objectFit: 'cover', borderRadius: '6px', flex: '0 0 auto', background: 'rgba(255,255,255,0.06)' }}
                />
              )}
              <div style={{ minWidth: 0 }}>
                <a
                  id="transcript-modal-title"
                  href={video.url ?? undefined}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: '#64b5f6', textDecoration: 'none', fontWeight: 700, fontSize: '1rem' }}
                >
                  {video.title || t('state.unknownTitle')}
                </a>
                <div style={{ marginTop: '0.3rem', fontSize: '0.8rem', color: '#888', display: 'flex', gap: '1rem' }}>
                  {video.uploaded_at && <span>{t('label.uploadedAtMeta', { date: formatDate(video.uploaded_at) })}</span>}
                  {video.duration_seconds && <span>{t('label.durationMeta', { duration: formatDuration(video.duration_seconds) })}</span>}
                </div>
              </div>
            </div>
            <button ref={closeButtonRef} onClick={onClose} aria-label={t('btn.close')} style={{ fontSize: '1.2rem', padding: '0.1rem 0.5rem', flexShrink: 0 }}>✕</button>
          </div>

          <div style={{ display: 'flex', gap: '0.25rem', marginTop: '0.75rem' }}>
            <button
              onClick={() => setActiveTab('transcript')}
              disabled={activeTab === 'transcript'}
              style={{ fontSize: '0.8rem' }}
            >
              {t('btn.transcript')}
            </button>
            {hasMindmap && (
              <button
                onClick={() => setActiveTab('mindmap')}
                disabled={activeTab === 'mindmap'}
                style={{ fontSize: '0.8rem' }}
              >
                {t('label.mindmap')}
              </button>
            )}
          </div>

          {activeTab === 'transcript' && (
            <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem', flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', gap: '0.25rem', marginRight: '0.25rem' }}>
                <button
                  onClick={() => setShowTimed(false)}
                  disabled={!showTimed}
                  style={{ fontSize: '0.8rem' }}
                >
                  {t('label.plain')}
                </button>
                <button
                  onClick={() => setShowTimed(true)}
                  disabled={!hasTimedTranscript || showTimed}
                  title={hasTimedTranscript ? t('tooltip.timedTranscript') : t('tooltip.noTimedTranscript')}
                  style={{ fontSize: '0.8rem' }}
                >
                  {t('label.timed')}
                </button>
              </div>
              <button onClick={copyToClipboard} style={{ fontSize: '0.8rem' }}>{t('btn.copy')}</button>
              <button
                onClick={() => downloadFile(videoToTxt(video, { timed: showTimed }), `${sanitizeFilename(video.title)}${showTimed ? '_timed' : ''}.txt`)}
                style={{ fontSize: '0.8rem' }}
              >
                {t('export.downloadTxt')}
              </button>
              <button
                onClick={() => downloadFile(videoToMd(video, { timed: showTimed }), `${sanitizeFilename(video.title)}${showTimed ? '_timed' : ''}.md`)}
                style={{ fontSize: '0.8rem' }}
              >
                {t('export.downloadMd')}
              </button>
              <button
                onClick={() => downloadFile(videoToObsidianMd(video, { timed: true }), obsidianFilename(video))}
                style={{ fontSize: '0.8rem' }}
              >
                {t('export.obsidianMd')}
              </button>
              {hasMindmap && (
                <button
                  onClick={() => downloadFile(videoToMarkmapMd(video), markmapFilename(video))}
                  style={{ fontSize: '0.8rem' }}
                  title={t('tooltip.mindmap')}
                >
                  {t('export.mindmapMd')}
                </button>
              )}
            </div>
          )}
        </div>

        <div style={{ padding: '1rem 1.25rem', overflowY: 'auto', flex: 1 }}>
          {activeTab === 'transcript' && (
            <>
              {localVideo.quick_summary && (
                <div style={{ marginBottom: '1rem', paddingBottom: '0.85rem', borderBottom: '1px solid var(--border)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.35rem' }}>
                    <h3 style={{ fontSize: '0.9rem', color: '#fff' }}>{t('label.quickSummary')}</h3>
                    {!editingQuick && (
                      <button onClick={startEditQuick} style={{ fontSize: '0.75rem', padding: '0.15rem 0.45rem' }}>
                        {t('btn.edit')}
                      </button>
                    )}
                  </div>
                  {quickSaveMsg && (
                    <div style={{ fontSize: '0.8rem', color: quickSaveMsg.startsWith('Hiba') || quickSaveMsg.startsWith('Error') ? '#f88' : '#6fcf73', marginBottom: '0.5rem' }}>
                      {quickSaveMsg}
                    </div>
                  )}
                  {editingQuick ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                      <textarea
                        value={quickEdit}
                        onChange={e => setQuickEdit(e.target.value)}
                        rows={5}
                        style={{ width: '100%', fontFamily: 'inherit', fontSize: '0.85rem', resize: 'vertical' }}
                      />
                      <div style={{ display: 'flex', gap: '0.4rem' }}>
                        <button onClick={handleSaveQuick} disabled={quickSaving} className="primary" style={{ fontSize: '0.8rem' }}>
                          {quickSaving ? t('btn.saving') : t('btn.save')}
                        </button>
                        <button onClick={() => setEditingQuick(false)} disabled={quickSaving} style={{ fontSize: '0.8rem' }}>
                          {t('btn.cancel')}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <p style={{ fontSize: '0.85rem', color: '#ccc', lineHeight: '1.55', margin: 0 }}>
                        {localVideo.quick_summary}
                      </p>
                      {localVideo.quick_summary_model && (
                        <span style={{ fontSize: '0.72rem', color: '#666', marginTop: '0.3rem', display: 'block' }}>
                          {localVideo.quick_summary_model}
                          {localVideo.quick_summary_generated_at ? ` · ${new Date(localVideo.quick_summary_generated_at).toLocaleString()}` : ''}
                        </span>
                      )}
                    </>
                  )}
                </div>
              )}
              {(localVideo.summary || localVideo.topics?.length || localVideo.takeaways?.length || localVideo.questions?.length || localVideo.study_guide || localVideo.critique) && (
                <div style={{ marginBottom: '1.2rem', paddingBottom: '1rem', borderBottom: '1px solid var(--border)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                    <h3 style={{ fontSize: '0.9rem', color: '#fff' }}>{t('label.aiNote')}</h3>
                    {!editingAi && (
                      <button onClick={startEditAi} style={{ fontSize: '0.75rem', padding: '0.15rem 0.45rem' }}>
                        {t('btn.edit')}
                      </button>
                    )}
                  </div>
                  {aiSaveMsg && (
                    <div style={{ fontSize: '0.8rem', color: aiSaveMsg.startsWith('Hiba') || aiSaveMsg.startsWith('Error') ? '#f88' : '#6fcf73', marginBottom: '0.5rem' }}>
                      {aiSaveMsg}
                    </div>
                  )}
                  {editingAi ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
                      <label style={{ fontSize: '0.8rem', color: '#aaa' }}>
                        {t('label.summary')}
                        <textarea
                          value={aiEdit.summary}
                          onChange={e => setAiEdit(p => ({ ...p, summary: e.target.value }))}
                          rows={4}
                          style={{ width: '100%', marginTop: '0.25rem', fontFamily: 'inherit', fontSize: '0.85rem', resize: 'vertical' }}
                        />
                      </label>
                      <label style={{ fontSize: '0.8rem', color: '#aaa' }}>
                        {t('label.topicsPerLine')}
                        <textarea
                          value={aiEdit.topics}
                          onChange={e => setAiEdit(p => ({ ...p, topics: e.target.value }))}
                          rows={4}
                          style={{ width: '100%', marginTop: '0.25rem', fontFamily: 'inherit', fontSize: '0.85rem', resize: 'vertical' }}
                        />
                      </label>
                      <label style={{ fontSize: '0.8rem', color: '#aaa' }}>
                        {t('label.takeawaysPerLine')}
                        <textarea
                          value={aiEdit.takeaways}
                          onChange={e => setAiEdit(p => ({ ...p, takeaways: e.target.value }))}
                          rows={4}
                          style={{ width: '100%', marginTop: '0.25rem', fontFamily: 'inherit', fontSize: '0.85rem', resize: 'vertical' }}
                        />
                      </label>
                      <label style={{ fontSize: '0.8rem', color: '#aaa' }}>
                        {t('label.questionsPerLine')}
                        <textarea
                          value={aiEdit.questions}
                          onChange={e => setAiEdit(p => ({ ...p, questions: e.target.value }))}
                          rows={3}
                          style={{ width: '100%', marginTop: '0.25rem', fontFamily: 'inherit', fontSize: '0.85rem', resize: 'vertical' }}
                        />
                      </label>
                      <div style={{ display: 'flex', gap: '0.4rem' }}>
                        <button onClick={handleSaveAi} disabled={aiSaving} className="primary" style={{ fontSize: '0.8rem' }}>
                          {aiSaving ? t('btn.saving') : t('btn.save')}
                        </button>
                        <button onClick={() => setEditingAi(false)} disabled={aiSaving} style={{ fontSize: '0.8rem' }}>
                          {t('btn.cancel')}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      {localVideo.summary && (
                        <p style={{ lineHeight: 1.65, fontSize: '0.9rem', color: '#ddd', marginBottom: '0.8rem' }}>
                          {localVideo.summary}
                        </p>
                      )}
                      {(localVideo.topics?.length ?? 0) > 0 && <h4 style={{ fontSize: '0.8rem', color: '#aaa' }}>{t('label.topics')}</h4>}
                      {renderList(localVideo.topics)}
                      {(localVideo.takeaways?.length ?? 0) > 0 && <h4 style={{ fontSize: '0.8rem', color: '#aaa' }}>{t('label.takeaways')}</h4>}
                      {renderList(localVideo.takeaways)}
                      {(localVideo.questions?.length ?? 0) > 0 && <h4 style={{ fontSize: '0.8rem', color: '#aaa' }}>{t('label.questions')}</h4>}
                      {renderList(localVideo.questions)}
                      {localVideo.study_guide && (
                        <>
                          <h4 style={{ fontSize: '0.8rem', color: '#aaa', marginTop: '0.5rem' }}>{t('label.studyGuide')}</h4>
                          <pre style={{ whiteSpace: 'pre-wrap', fontSize: '0.82rem', color: '#ddd', fontFamily: 'inherit', margin: '0.35rem 0 0.8rem', lineHeight: 1.6 }}>
                            {localVideo.study_guide}
                          </pre>
                        </>
                      )}
                      {localVideo.critique && (
                        <>
                          <h4 style={{ fontSize: '0.8rem', color: '#aaa', marginTop: '0.5rem' }}>{t('label.critique')}</h4>
                          <pre style={{ whiteSpace: 'pre-wrap', fontSize: '0.82rem', color: '#ddd', fontFamily: 'inherit', margin: '0.35rem 0 0.8rem', lineHeight: 1.6 }}>
                            {localVideo.critique}
                          </pre>
                        </>
                      )}
                    </>
                  )}
                </div>
              )}
              {visibleTranscript ? (
                <>
                  <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '0.3rem' }}>
                    {!editingTranscript ? (
                      <button style={{ fontSize: '0.75rem', padding: '0.15rem 0.45rem' }} onClick={() => { setTranscriptEdit(visibleTranscript); setEditingTranscript(true); }}>
                        {t('btn.editTranscript')}
                      </button>
                    ) : (
                      <div style={{ display: 'flex', gap: '0.35rem' }}>
                        <button className="primary" style={{ fontSize: '0.75rem', padding: '0.15rem 0.45rem' }} disabled={transcriptSaving} onClick={handleSaveTranscript}>
                          {transcriptSaving ? t('btn.saving') : t('btn.save')}
                        </button>
                        <button style={{ fontSize: '0.75rem', padding: '0.15rem 0.45rem' }} disabled={transcriptSaving} onClick={() => setEditingTranscript(false)}>
                          {t('btn.cancel')}
                        </button>
                      </div>
                    )}
                  </div>
                  {editingTranscript ? (
                    <textarea
                      value={transcriptEdit}
                      onChange={e => setTranscriptEdit(e.target.value)}
                      style={{ width: '100%', minHeight: '320px', fontFamily: 'inherit', fontSize: '0.88rem', lineHeight: 1.65, resize: 'vertical' }}
                    />
                  ) : (
                    <p style={{ lineHeight: 1.7, fontSize: '0.9rem', color: '#ddd', whiteSpace: 'pre-wrap' }}>
                      {visibleTranscript}
                    </p>
                  )}
                </>
              ) : (
                <p style={{ color: '#888', fontStyle: 'italic' }}>{t('state.noTranscript')}</p>
              )}
            </>
          )}

          {activeTab === 'mindmap' && (
            <div style={{ width: '100%', minHeight: '450px', background: '#fff', borderRadius: '6px', overflow: 'hidden' }}>
              <svg ref={svgRef} style={{ width: '100%', height: '450px', display: 'block' }} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
