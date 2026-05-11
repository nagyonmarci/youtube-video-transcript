export function sameData(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function keepIfSame(prev, next) {
  return sameData(prev, next) ? prev : next;
}
