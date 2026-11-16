// Hydration-safe wrappers around @expo/vector-icons.
//
// The static web export renders every page on the server, and the browser
// then hydrates that HTML. A vector icon decides what to render from
// Font.isLoaded(...), which is false on the server (an empty <Text/>) but can
// already be true on the client's first render (the full glyph with its font
// styles) — so every icon on every page was a hydration mismatch, and React
// threw the server HTML away (error #418).
//
// These render a same-sized empty placeholder on the server AND on the
// client's first (hydrating) render, then the real icon once hydrated. On
// native there is no server render, so the real icon shows immediately.
//
// Import icons from here, not from '@expo/vector-icons'.
import {
  Feather as FeatherIcon,
  MaterialCommunityIcons as MaterialCommunityIcon,
} from '@expo/vector-icons';
import React, { useSyncExternalStore } from 'react';
import { View } from 'react-native';

const subscribe = () => () => {};
const onClient = () => true;
const onServer = () => false;

/** false during server rendering and hydration, true afterwards. */
function useHydrated(): boolean {
  return useSyncExternalStore(subscribe, onClient, onServer);
}

function Placeholder({ size }: { size?: number }) {
  const side = size ?? 12;
  return <View style={{ width: side, height: side }} />;
}

export function Feather(props: React.ComponentProps<typeof FeatherIcon>) {
  return useHydrated() ? <FeatherIcon {...props} /> : <Placeholder size={props.size} />;
}

export function MaterialCommunityIcons(props: React.ComponentProps<typeof MaterialCommunityIcon>) {
  return useHydrated() ? <MaterialCommunityIcon {...props} /> : <Placeholder size={props.size} />;
}
