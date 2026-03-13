export const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

function getAuthHeader() {
  const token = localStorage.getItem("yt_token");
  return token ? { "Authorization": `Bearer ${token}` } : {};
}

export async function getChannels() {
  const res = await fetch(`${BASE}/channels`, {
    headers: getAuthHeader()
  });
  if (res.status === 401) window.location.href = "/login";
  return res.json();
}

export async function addChannel(channel_name) {
  const res = await fetch(`${BASE}/channels`, {
    method: "POST",
    headers: { 
      "Content-Type": "application/json",
      ...getAuthHeader()
    },
    body: JSON.stringify({ channel_name }),
  });
  return res.json();
}

export async function deleteChannel(name) {
  return fetch(`${BASE}/channels/${name}`, { 
    method: "DELETE",
    headers: getAuthHeader()
  });
}

export async function getVideos(channel, status = "") {
  const q = status ? `?status=${status}` : "";
  const res = await fetch(`${BASE}/videos/${channel}${q}`, {
    headers: getAuthHeader()
  });
  return res.json();
}

export async function getTranscript(video_id) {
  const res = await fetch(`${BASE}/videos/transcript/${video_id}`, {
    headers: getAuthHeader()
  });
  return res.json();
}

export function logout() {
  localStorage.removeItem("yt_token");
  localStorage.removeItem("yt_user");
  window.location.href = "/login";
}
