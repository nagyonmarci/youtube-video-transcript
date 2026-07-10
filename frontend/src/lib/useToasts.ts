import { useState } from 'react';
import { TOAST_TIMEOUT_MS } from './constants.ts';

export interface Toast {
  id: number;
  text: string;
}

export function useToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  function addToast(text: string) {
    const id = Date.now();
    setToasts(prev => [...prev, { id, text }]);
    setTimeout(() => setToasts(prev => prev.filter(x => x.id !== id)), TOAST_TIMEOUT_MS);
  }

  function removeToast(id: number) {
    setToasts(prev => prev.filter(x => x.id !== id));
  }

  return { toasts, addToast, removeToast };
}
