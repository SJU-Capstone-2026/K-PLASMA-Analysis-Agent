// Skip elapsed slots after a slow response; never issue a backlog of catch-up requests.
export function requestSlot(nextSlot,elapsedMs,periodMs) {
  return Math.max(nextSlot,Math.floor(Math.max(0,elapsedMs)/periodMs));
}
