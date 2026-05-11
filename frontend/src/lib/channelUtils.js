export function parseChannelFile(text) {
  const lines = text.split(/\r?\n/).map(l => l.trim()).filter(l => l && !l.startsWith('#'));
  return lines.map(line => {
    if (line.includes(',')) {
      const parts = line.split(',').map(p => p.trim().replace(/^["']|["']$/g, ''));
      return parts.find(p => p.includes('youtube') || p.startsWith('@') || p.startsWith('UC')) || parts[0];
    }
    return line;
  }).filter(Boolean);
}
