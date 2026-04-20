import { useCallback, useEffect, useState } from 'react';

const STORAGE_KEY = 'monitor.oblibene.v1';

export type FavoriteType = 'clanek' | 'spolecnost' | 'produkt' | 'kampan' | 'mystery';

type FavoriteKey = `${FavoriteType}:${string}`;

function load(): Set<FavoriteKey> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw) as string[];
    return new Set(arr as FavoriteKey[]);
  } catch {
    return new Set();
  }
}

function save(set: Set<FavoriteKey>) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify([...set]));
}

// Simple global store + subscription so multiple components stay in sync.
let store: Set<FavoriteKey> = load();
const listeners = new Set<() => void>();

function notify() {
  listeners.forEach((l) => l());
}

export function useFavorites() {
  const [, tick] = useState(0);

  useEffect(() => {
    const listener = () => tick((v) => v + 1);
    listeners.add(listener);
    return () => { listeners.delete(listener); };
  }, []);

  const key = (type: FavoriteType, id: string): FavoriteKey => `${type}:${id}`;

  const isFavorite = useCallback(
    (type: FavoriteType, id: string) => store.has(key(type, id)),
    [],
  );

  const toggle = useCallback((type: FavoriteType, id: string) => {
    const k = key(type, id);
    if (store.has(k)) store.delete(k);
    else store.add(k);
    save(store);
    notify();
  }, []);

  const list = useCallback((type?: FavoriteType): string[] => {
    const arr = [...store];
    return type ? arr.filter((k) => k.startsWith(`${type}:`)).map((k) => k.split(':')[1]) : arr;
  }, []);

  const count = store.size;

  return { isFavorite, toggle, list, count };
}
