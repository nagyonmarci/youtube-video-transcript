export function readUrlFilters() {
  const p = new URLSearchParams(window.location.search);
  return {
    search: p.get('q') || '',
    statusFilter: p.get('status') || 'all',
    aiFilter: p.get('ai') || 'all',
    membersFilter: p.get('members') || 'hide',
  };
}
