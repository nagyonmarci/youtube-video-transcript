import { useState, useEffect, useCallback } from "react";
import { getChannels, logout } from "./api/client";
import ChannelForm from "./components/ChannelForm";
import ChannelList from "./components/ChannelList";
import VideoList from "./components/VideoList";
import TranscriptModal from "./components/TranscriptModal";

export default function App() {
  const [channels, setChannels] = useState([]);
  const [selectedChannel, setSelectedChannel] = useState(null);
  const [selectedVideo, setSelectedVideo] = useState(null);
  const [user, setUser] = useState(null);

  useEffect(() => {
    const savedUser = localStorage.getItem("yt_user");
    if (savedUser) setUser(JSON.parse(savedUser));
  }, []);

  const loadChannels = useCallback(() => {
    getChannels().then(setChannels).catch(err => {
      if (err.message.includes("401")) logout();
    });
  }, []);

  const handleStopTasks = async () => {
    try {
      const res = await fetch(`${import.meta.env.VITE_API_URL || "http://localhost:8000"}/channels/stop-tasks`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${localStorage.getItem("yt_token")}` }
      });
      if (res.ok) {
        const data = await res.json();
        alert(data.message);
      } else {
        alert("Failed to stop tasks.");
      }
    } catch (err) {
      alert("Error stopping tasks.");
    }
  };

  const handleAggregatedExport = async (format) => {
    const fmt = confirm("Use Markdown format? (Cancel for TXT)") ? "md" : "txt";
    // @ts-ignore
    const client = google.accounts.oauth2.initTokenClient({
      client_id: import.meta.env.VITE_GOOGLE_CLIENT_ID || '',
      scope: 'https://www.googleapis.com/auth/drive.file',
      callback: async (tokenResponse) => {
        if (tokenResponse.error) return;
        try {
          const res = await fetch(`${import.meta.env.VITE_API_URL || "http://localhost:8000"}/export-all/save-to-drive`, {
            method: "POST",
            headers: { 
              "Content-Type": "application/json",
              "Authorization": `Bearer ${localStorage.getItem("yt_token")}`
            },
            body: JSON.stringify({ access_token: tokenResponse.access_token, format: fmt }),
          });
          if (!res.ok) throw new Error();
          alert("Success! All transcripts saved to Drive.");
        } catch (err) {
          alert("Failed to save to Drive.");
        }
      },
    });
    client.requestAccessToken();
  };

  useEffect(() => {
    loadChannels();
    const interval = setInterval(loadChannels, 30000); // refresh every 30s
    return () => clearInterval(interval);
  }, [loadChannels]);

  return (
    <div className="app">
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '1rem 2rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <h1 style={{ margin: 0 }}>🎬 YouTube Transcript Manager</h1>
        </div>
        
        {user && (
          <div className="user-profile" style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontWeight: 'bold', fontSize: '0.9rem' }}>{user.name}</div>
              <button 
                className="secondary" 
                style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem', marginTop: '0.25rem' }}
                onClick={logout}
              >
                Sign Out
              </button>
            </div>
            {user.picture && (
              <img 
                src={user.picture} 
                alt={user.name} 
                style={{ width: '40px', height: '40px', borderRadius: '50%', border: '2px solid var(--primary)' }} 
              />
            )}
          </div>
        )}
      </header>
      <main>
        <aside>
          <ChannelForm onAdded={loadChannels} />
          
          <div className="card" style={{ marginBottom: '1rem' }}>
            <h3>📦 Global Actions</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginTop: '0.5rem' }}>
              <button 
                className="secondary" 
                onClick={() => {
                  const fmt = confirm("Use Markdown format? (Cancel for TXT)") ? "md" : "txt";
                  const token = localStorage.getItem("yt_token");
                  window.open(`${import.meta.env.VITE_API_URL || "http://localhost:8000"}/export-all?format=${fmt}&token=${token}`, "_blank");
                }}
              >
                📥 Download All (Aggregated)
              </button>
              <button 
                className="secondary"
                style={{ background: 'rgba(66, 133, 244, 0.2)', border: '1px solid rgba(66, 133, 244, 0.4)' }}
                onClick={() => handleAggregatedExport()}
              >
                📁 Save All to Google Drive
              </button>
              <button 
                className="secondary"
                style={{ background: 'rgba(244, 67, 54, 0.2)', border: '1px solid rgba(244, 67, 54, 0.4)' }}
                onClick={() => handleStopTasks()}
              >
                🛑 Stop All Background Tasks
              </button>
              <button 
                className="secondary"
                style={{ background: 'rgba(255, 193, 7, 0.2)', border: '1px solid rgba(255, 193, 7, 0.4)' }}
                onClick={() => document.getElementById('cookie-upload').click()}
              >
                🍪 Upload YouTube Cookies (.txt)
              </button>
              <input 
                id="cookie-upload"
                type="file"
                accept=".txt"
                style={{ display: 'none' }}
                onChange={(e) => {
                  const file = e.target.files[0];
                  if (!file) return;
                  const formData = new FormData();
                  formData.append("file", file);
                  fetch(`${import.meta.env.VITE_API_URL || "http://localhost:8000"}/auth/cookies`, {
                    method: "POST",
                    headers: { 
                      "Authorization": `Bearer ${localStorage.getItem("yt_token")}`
                    },
                    body: formData,
                  }).then(res => {
                    if (res.ok) alert("Success! Cookies uploaded.");
                    else alert("Failed to upload cookies.");
                  }).catch(() => alert("Error uploading cookies."));
                }}
              />
            </div>
          </div>

          <ChannelList
            channels={channels}
            selected={selectedChannel}
            onSelect={setSelectedChannel}
            onDeleted={loadChannels}
          />
        </aside>
        <section>
          <VideoList
            channel={selectedChannel}
            onSelectVideo={setSelectedVideo}
          />
        </section>
      </main>
      <TranscriptModal
        videoId={selectedVideo}
        onClose={() => setSelectedVideo(null)}
      />
    </div>
  );
}
