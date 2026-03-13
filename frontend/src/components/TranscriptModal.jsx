import { useState, useEffect } from "react";
import { getTranscript } from "../api/client";

export default function TranscriptModal({ videoId, onClose }) {
  const [data, setData] = useState(null);

  useEffect(() => {
    if (!videoId) {
      setData(null);
      return;
    }
    getTranscript(videoId).then(setData);
  }, [videoId]);

  const copyToClipboard = () => {
    if (!data?.transcript) return;
    navigator.clipboard.writeText(data.transcript);
    alert("Transcript copied to clipboard!");
  };

  if (!videoId) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{data?.title ?? "Loading..."}</h3>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            {data && (
              <button className="secondary" onClick={copyToClipboard} title="Copy">
                📋 Copy
              </button>
            )}
            <button className="danger icon-btn" onClick={onClose} title="Close">✕</button>
          </div>
        </div>
        <div className="modal-body">
          {data ? (
            <>
              <div style={{ marginBottom: '1rem' }}>
                <a href={data.url} target="_blank" rel="noreferrer" className="muted" style={{ textDecoration: 'underline' }}>
                  📺 Open on YouTube
                </a>
              </div>
              <div className="transcript-text">
                {data.transcript}
              </div>
            </>
          ) : (
            <div style={{ textAlign: 'center', padding: '3rem' }}>
              <p className="muted">Loading...</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
