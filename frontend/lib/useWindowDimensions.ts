// Hydration-safe replacement for react-native's useWindowDimensions.
//
// react-native-web's version starts from the live window size, so the client's
// first render sees the real viewport while the server rendered with a fixed
// 1024x768. Any layout branching on it (the phone layout, the landing hero)
// then mismatches the prerendered HTML and React discards that HTML (error
// #418). This returns the server's size during server rendering and
// hydration, and the real size from the next render on.
import { useSyncExternalStore } from 'react';
import { Dimensions, type ScaledSize } from 'react-native';

// What react-native-web assumes when there is no window.
const SERVER_WINDOW: ScaledSize = { width: 1024, height: 768, scale: 1, fontScale: 1 };

function subscribe(onChange: () => void): () => void {
  const subscription = Dimensions.addEventListener('change', onChange);
  return () => subscription.remove();
}

const getWindow = (): ScaledSize => Dimensions.get('window');
const getServerWindow = (): ScaledSize => SERVER_WINDOW;

export function useWindowDimensions(): ScaledSize {
  return useSyncExternalStore(subscribe, getWindow, getServerWindow);
}

// The live viewport height in CSS px (what BottomSheet sizes itself from),
// with the same server/hydration behaviour.
const SERVER_VIEWPORT_HEIGHT = 800;

function subscribeResize(onChange: () => void): () => void {
  window.addEventListener('resize', onChange);
  return () => window.removeEventListener('resize', onChange);
}

export function useViewportHeight(): number {
  return useSyncExternalStore(
    subscribeResize,
    () => window.innerHeight,
    () => SERVER_VIEWPORT_HEIGHT,
  );
}
