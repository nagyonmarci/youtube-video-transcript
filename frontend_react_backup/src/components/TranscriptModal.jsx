import { useState, useEffect } from "react";
import { getTranscript } from "../api/client";

export default function TranscriptModal({ videoId, onClose }) {
  const [data, setData] = useState(null);

  useEffect(() => {
    if (!videoId) return;
    getTranscript(videoId).then(setData);
  }, [videoId]);

  if (!videoId) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{data?.title ?? "Betöltés..."}</h3>
          <button onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          {data ? (
            <>
              <a href={data.url} target="_blank" rel="noreferrer">{data.url}</a>
              <p className="transcript-text">{data.transcript}</p>
            </>
          ) : (
            <p>Betöltés...</p>
          )}
        </div>
      </div>
    </div>
  );
}
