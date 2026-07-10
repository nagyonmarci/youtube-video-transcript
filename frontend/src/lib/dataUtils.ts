export function sameData(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function keepIfSame<T>(prev: T, next: T): T {
  return sameData(prev, next) ? prev : next;
}
