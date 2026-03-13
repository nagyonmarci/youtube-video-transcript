const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export async function getChannels() {
  const res = await fetch(`${BASE}/channels`);
  return res.json();
}

export async function addChannel(channel_name) {
  const res = await fetch(`${BASE}/channels`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ channel_name }),
  });
  return res.json();
}

export async function deleteChannel(name) {
  return fetch(`${BASE}/channels/${name}`, { method: "DELETE" });
}

export async function getVideos(channel, status = "") {
  const q = status ? `?status=${status}` : "";
  const res = await fetch(`${BASE}/videos/${channel}${q}`);
  return res.json();
}

export async function getTranscript(video_id) {
  const res = await fetch(`${BASE}/videos/transcript/${video_id}`);
  return res.json();
}
