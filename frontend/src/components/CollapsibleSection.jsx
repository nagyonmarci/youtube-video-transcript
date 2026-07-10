export default function CollapsibleSection({
  id, title, subtitle, headerExtra, open, onToggle,
  isDragging, isDragOver, onDragStart, onDragEnd, onDragOver, onDragLeave, onDrop,
  children,
}) {
  return (
    <section className="admin-section">
      <div
        className={`admin-section-header${isDragOver ? ' admin-section-drag-over' : ''}`}
        onDragOver={isDragging ? (e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; onDragOver(id); } : undefined}
        onDragLeave={isDragging ? (e) => { if (!e.currentTarget.contains(e.relatedTarget)) onDragLeave(); } : undefined}
        onDrop={isDragging ? (e) => { e.preventDefault(); onDrop(id); } : undefined}
      >
        <div className="admin-section-header-main">
          <span
            className="admin-section-handle"
            draggable
            aria-hidden="true"
            onDragStart={(e) => { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', id); onDragStart(id); }}
            onDragEnd={onDragEnd}
          >⠿</span>
          <button type="button" className="admin-section-toggle" onClick={() => onToggle(id)} aria-expanded={open}>
            <span className={`admin-section-chevron${open ? ' admin-section-chevron-open' : ''}`} aria-hidden="true">▸</span>
            <span className="admin-section-title">{title}</span>
          </button>
          {subtitle && <span className="admin-section-subtitle">{subtitle}</span>}
        </div>
        {headerExtra && <div className="admin-section-actions">{headerExtra}</div>}
      </div>
      {open && <div className="admin-section-body">{children}</div>}
    </section>
  );
}
