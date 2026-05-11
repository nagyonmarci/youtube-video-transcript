import { useState } from 'react';
import { MSG_TIMEOUT_MS } from './constants.js';

export function useMessage(timeout = MSG_TIMEOUT_MS) {
  const [msg, setMsg] = useState(null);

  function showMsg(text, isError = false) {
    setMsg({ text, isError });
    setTimeout(() => setMsg(null), timeout);
  }

  return { msg, showMsg };
}
