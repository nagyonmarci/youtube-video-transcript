import { useState } from 'react';
import { TOAST_TIMEOUT_MS } from './constants.js';

export function useToasts() {
  const [toasts, setToasts] = useState([]);

  function addToast(text) {
    const id = Date.now();
    setToasts(prev => [...prev, { id, text }]);
    setTimeout(() => setToasts(prev => prev.filter(x => x.id !== id)), TOAST_TIMEOUT_MS);
  }

  function removeToast(id) {
    setToasts(prev => prev.filter(x => x.id !== id));
  }

  return { toasts, addToast, removeToast };
}
