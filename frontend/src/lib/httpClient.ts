export function createRequester(baseUrl: string) {
  return async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
    const res = await fetch(`${baseUrl}${path}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      let detail = '';
      try {
        const data = await res.json();
        detail = data.detail ? `: ${data.detail}` : '';
      } catch {}
      throw new Error(`${method} ${path} → ${res.status}${detail}`);
    }
    return res.status === 204 ? (null as T) : res.json();
  };
}
