// Helpers for the few places that must hand an HTML *string* to a third-party
// API — today only google.maps.InfoWindow.setContent in the web planner.
// Everything interpolated into such a string that isn't a literal in our own
// source (GBFS station names, Google's step text and stop names, saved stop
// names, API-supplied colors) goes through these first, so markup in a feed
// or a saved itinerary renders as text instead of executing in the page.

const ENTITIES: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
};

/** Escape a value for use in HTML text or a double-quoted attribute. */
export function escapeHtml(value: unknown): string {
  if (value == null) return '';
  return String(value).replace(/[&<>"']/g, (ch) => ENTITIES[ch]);
}

/** A hex color safe to place inside a style attribute, or the fallback. */
export function safeHexColor(value: unknown, fallback: string): string {
  return typeof value === 'string' && /^#[0-9a-fA-F]{3,8}$/.test(value) ? value : fallback;
}
