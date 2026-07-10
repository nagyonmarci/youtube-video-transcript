import { useState } from 'react';
import { MSG_TIMEOUT_MS } from './constants.ts';

interface Message {
  text: string;
  isError: boolean;
}

export function useMessage(timeout = MSG_TIMEOUT_MS) {
  const [msg, setMsg] = useState<Message | null>(null);

  function showMsg(text: string, isError = false) {
    setMsg({ text, isError });
    setTimeout(() => setMsg(null), timeout);
  }

  return { msg, showMsg };
}
