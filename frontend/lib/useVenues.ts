import { useEffect, useState } from 'react';

import { VENUES as STATIC_VENUES, VenueStub } from '@/constants/venues';
import { api, VenueListItem } from './api';

function toVenueStub(v: VenueListItem): VenueStub | null {
  // A venue with no coordinates can't be a map pin — GET /api/venues
  // already filters these out server-side, but a client-side check costs
  // nothing and doesn't depend on that staying true.
  if (v.lat == null || v.lng == null) return null;
  return { kind: 'venue', id: v.id, name: v.name, sport_use: v.sport_use ?? '', address: v.address ?? '', lat: v.lat, lng: v.lng };
}

/**
 * The live venue list from the backend — every registered venue, not just
 * the original 6 in constants/venues.ts. Starts from that static list (so
 * the map/pickers render immediately, not empty) and replaces it once the
 * fetch resolves; on failure (offline, backend down) it just keeps the
 * static fallback rather than showing nothing.
 */
export function useVenues(): VenueStub[] {
  const [venues, setVenues] = useState<VenueStub[]>(STATIC_VENUES);

  useEffect(() => {
    let cancelled = false;
    api.listVenues()
      .then((items) => {
        if (cancelled) return;
        const stubs = items.map(toVenueStub).filter((v): v is VenueStub => v !== null);
        if (stubs.length > 0) setVenues(stubs);
      })
      .catch(() => {
        // Keep the static fallback already in state.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return venues;
}
