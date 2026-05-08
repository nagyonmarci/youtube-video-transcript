import { useEffect, useRef, useState } from 'react';
import { Transformer } from 'markmap-lib';
import { Markmap } from 'markmap-view';
import { videoToTxt, videoToMd, videoToObsidianMd, obsidianFilename, videoToMarkmapMd, markmapFilename, downloadFile, sanitizeFilename } from '../lib/export.js';
import { updateVideoFields } from '../lib/directus.js';

const transformer = new Transformer();

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

export default function TranscriptModal({ video, onClose, onVideoUpdated }) {
  const [showTimed, setShowTimed] = useState(false);
  const [activeTab, setActiveTab] = useState('transcript');
  const [localVideo, setLocalVideo] = useState(video);
  const [editingAi, setEditingAi] = useState(false);
  const [aiEdit, setAiEdit] = useState({});
  const [aiSaving, setAiSaving] = useState(false);
  const [aiSaveMsg, setAiSaveMsg] = useState(null);
  const [editingTranscript, setEditingTranscript] = useState(false);
  const [transcriptEdit, setTranscriptEdit] = useState('');
  const [transcriptSaving, setTranscriptSaving] = useState(false);
  const svgRef = useRef(null);
  const markmapRef = useRef(null);

  useEffect(() => { setLocalVideo(video); }, [video]);

  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  useEffect(() => {
    if (activeTab !== 'mindmap' || !svgRef.current) return;
    const content = videoToMarkmapMd(localVideo);
    const { root } = transformer.transform(content);
    svgRef.current.innerHTML = '';
    markmapRef.current = Markmap.create(svgRef.current, { duration: 0 }, root);
  }, [activeTab, video]);

  function startEditAi() {
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
      setLocalVideo(prev => ({ ...prev, ...fields }));
      setEditingAi(false);
      setAiSaveMsg('Mentve.');
      setTimeout(() => setAiSaveMsg(null), 2500);
      onVideoUpdated?.();
    } catch (err) {
      setAiSaveMsg('Hiba: ' + err.message);
    } finally {
      setAiSaving(false);
    }
  }

  async function handleSaveTranscript() {
    setTranscriptSaving(true);
    try {
      const fields = showTimed
        ? { transcript_timed: transcriptEdit }
        : { transcript: transcriptEdit };
      await updateVideoFields(localVideo.id, fields);
      setLocalVideo(prev => ({ ...prev, ...fields }));
      setEditingTranscript(false);
      onVideoUpdated?.();
    } catch (err) {
      alert('Mentési hiba: ' + err.message);
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
            </div>
            <button onClick={onClose} style={{ fontSize: '1.2rem', padding: '0.1rem 0.5rem', flexShrink: 0 }}>✕</button>
          </div>

          {/* Tab sor */}
          <div style={{ display: 'flex', gap: '0.25rem', marginTop: '0.75rem' }}>
            <button
              onClick={() => setActiveTab('transcript')}
              disabled={activeTab === 'transcript'}
              style={{ fontSize: '0.8rem' }}
            >
              Transzkript
            </button>
            {hasMindmap && (
              <button
                onClick={() => setActiveTab('mindmap')}
                disabled={activeTab === 'mindmap'}
                style={{ fontSize: '0.8rem' }}
              >
                Gondolattérkép
              </button>
            )}
          </div>

          {/* Export gombok — csak transzkript tab alatt */}
          {activeTab === 'transcript' && (
            <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem', flexWrap: 'wrap' }}>
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
              {hasMindmap && (
                <button
                  onClick={() => downloadFile(videoToMarkmapMd(video), markmapFilename(video))}
                  style={{ fontSize: '0.8rem' }}
                  title="Markmap gondolattérkép letöltése (Obsidian markmap plugin szükséges)"
                >
                  Mindmap MD
                </button>
              )}
            </div>
          )}
        </div>

        <div style={{ padding: '1rem 1.25rem', overflowY: 'auto', flex: 1 }}>
          {activeTab === 'transcript' && (
            <>
              {(localVideo.summary || localVideo.topics?.length || localVideo.takeaways?.length || localVideo.questions?.length || localVideo.study_guide || localVideo.critique) && (
                <div style={{ marginBottom: '1.2rem', paddingBottom: '1rem', borderBottom: '1px solid var(--border)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                    <h3 style={{ fontSize: '0.9rem', color: '#fff' }}>AI jegyzet</h3>
                    {!editingAi && (
                      <button onClick={startEditAi} style={{ fontSize: '0.75rem', padding: '0.15rem 0.45rem' }}>
                        Szerkesztés
                      </button>
                    )}
                  </div>
                  {aiSaveMsg && (
                    <div style={{ fontSize: '0.8rem', color: aiSaveMsg.startsWith('Hiba') ? '#f88' : '#6fcf73', marginBottom: '0.5rem' }}>
                      {aiSaveMsg}
                    </div>
                  )}
                  {editingAi ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
                      <label style={{ fontSize: '0.8rem', color: '#aaa' }}>
                        Összefoglaló
                        <textarea
                          value={aiEdit.summary}
                          onChange={e => setAiEdit(p => ({ ...p, summary: e.target.value }))}
                          rows={4}
                          style={{ width: '100%', marginTop: '0.25rem', fontFamily: 'inherit', fontSize: '0.85rem', resize: 'vertical' }}
                        />
                      </label>
                      <label style={{ fontSize: '0.8rem', color: '#aaa' }}>
                        Témák (soronként egy)
                        <textarea
                          value={aiEdit.topics}
                          onChange={e => setAiEdit(p => ({ ...p, topics: e.target.value }))}
                          rows={4}
                          style={{ width: '100%', marginTop: '0.25rem', fontFamily: 'inherit', fontSize: '0.85rem', resize: 'vertical' }}
                        />
                      </label>
                      <label style={{ fontSize: '0.8rem', color: '#aaa' }}>
                        Tanulságok (soronként egy)
                        <textarea
                          value={aiEdit.takeaways}
                          onChange={e => setAiEdit(p => ({ ...p, takeaways: e.target.value }))}
                          rows={4}
                          style={{ width: '100%', marginTop: '0.25rem', fontFamily: 'inherit', fontSize: '0.85rem', resize: 'vertical' }}
                        />
                      </label>
                      <label style={{ fontSize: '0.8rem', color: '#aaa' }}>
                        Kérdések (soronként egy)
                        <textarea
                          value={aiEdit.questions}
                          onChange={e => setAiEdit(p => ({ ...p, questions: e.target.value }))}
                          rows={3}
                          style={{ width: '100%', marginTop: '0.25rem', fontFamily: 'inherit', fontSize: '0.85rem', resize: 'vertical' }}
                        />
                      </label>
                      <div style={{ display: 'flex', gap: '0.4rem' }}>
                        <button onClick={handleSaveAi} disabled={aiSaving} className="primary" style={{ fontSize: '0.8rem' }}>
                          {aiSaving ? 'Mentés...' : 'Mentés'}
                        </button>
                        <button onClick={() => setEditingAi(false)} disabled={aiSaving} style={{ fontSize: '0.8rem' }}>
                          Mégsem
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
                      {localVideo.topics?.length > 0 && <h4 style={{ fontSize: '0.8rem', color: '#aaa' }}>Témák</h4>}
                      {renderList(localVideo.topics)}
                      {localVideo.takeaways?.length > 0 && <h4 style={{ fontSize: '0.8rem', color: '#aaa' }}>Tanulságok</h4>}
                      {renderList(localVideo.takeaways)}
                      {localVideo.questions?.length > 0 && <h4 style={{ fontSize: '0.8rem', color: '#aaa' }}>Kérdések</h4>}
                      {renderList(localVideo.questions)}
                      {localVideo.study_guide && (
                        <>
                          <h4 style={{ fontSize: '0.8rem', color: '#aaa', marginTop: '0.5rem' }}>Tanulási útmutató</h4>
                          <pre style={{ whiteSpace: 'pre-wrap', fontSize: '0.82rem', color: '#ddd', fontFamily: 'inherit', margin: '0.35rem 0 0.8rem', lineHeight: 1.6 }}>
                            {localVideo.study_guide}
                          </pre>
                        </>
                      )}
                      {localVideo.critique && (
                        <>
                          <h4 style={{ fontSize: '0.8rem', color: '#aaa', marginTop: '0.5rem' }}>Kritikai jegyzetek</h4>
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
                        Transzkript szerkesztése
                      </button>
                    ) : (
                      <div style={{ display: 'flex', gap: '0.35rem' }}>
                        <button className="primary" style={{ fontSize: '0.75rem', padding: '0.15rem 0.45rem' }} disabled={transcriptSaving} onClick={handleSaveTranscript}>
                          {transcriptSaving ? 'Mentés...' : 'Mentés'}
                        </button>
                        <button style={{ fontSize: '0.75rem', padding: '0.15rem 0.45rem' }} disabled={transcriptSaving} onClick={() => setEditingTranscript(false)}>
                          Mégsem
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
                <p style={{ color: '#888', fontStyle: 'italic' }}>Ehhez a videóhoz nincs elérhető transzkript.</p>
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
