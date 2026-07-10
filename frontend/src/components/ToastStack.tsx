import type { Toast } from '../lib/useToasts.ts';

export default function ToastStack({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: number) => void }) {
  if (toasts.length === 0) return null;
  return (
    <div style={{ position: 'fixed', bottom: '4.75rem', right: '1.25rem', display: 'flex', flexDirection: 'column', gap: '0.4rem', zIndex: 2000 }}>
      {toasts.map(toast => (
        <div key={toast.id} style={{ background: 'rgba(76,175,80,0.9)', color: '#fff', padding: '0.55rem 0.9rem', borderRadius: '7px', fontSize: '0.88rem', fontWeight: 600, boxShadow: '0 2px 8px rgba(0,0,0,0.4)', cursor: 'pointer' }} onClick={() => onDismiss(toast.id)}>
          {toast.text}
        </div>
      ))}
    </div>
  );
}
