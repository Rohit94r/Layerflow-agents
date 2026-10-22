"use client";

import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { errorMessage, get } from "./api";
import { useToast } from "./toast";
import type { Health, Me, Playbook } from "./types";

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => get<Me>("/auth/me"), staleTime: 60_000, retry: false });
}

export function useHealth() {
  return useQuery({ queryKey: ["health"], queryFn: () => get<Health>("/health"), refetchInterval: 30_000, retry: false });
}

export function usePlaybooks() {
  return useQuery({
    queryKey: ["playbooks"],
    queryFn: () => get<{ items: Playbook[] }>("/playbooks"),
    staleTime: Infinity,
    select: (d) => d.items,
  });
}

export function usePlaybookMap() {
  const { data } = usePlaybooks();
  const map: Record<string, Playbook> = {};
  for (const p of data ?? []) map[p.key] = p;
  return map;
}

/** Mutation with pending state, toast on success/failure and query invalidation. */
export function useAction<TVars, TResult>(
  fn: (vars: TVars) => Promise<TResult>,
  opts: {
    success?: string | ((r: TResult, v: TVars) => string | undefined);
    error?: string;
    invalidate?: QueryKey[];
    onSuccess?: (r: TResult, v: TVars) => void;
    onError?: (e: unknown, v: TVars) => void;
    silent?: boolean;
  } = {},
) {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: fn,
    onSuccess: (r, v) => {
      for (const key of opts.invalidate ?? []) qc.invalidateQueries({ queryKey: key });
      const msg = typeof opts.success === "function" ? opts.success(r, v) : opts.success;
      if (msg && !opts.silent) toast.success(msg);
      opts.onSuccess?.(r, v);
    },
    onError: (e, v) => {
      if (!opts.silent) toast.error(opts.error ?? "Action failed", errorMessage(e));
      opts.onError?.(e, v);
    },
  });
}

export function useDebounced<T>(value: T, delay = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return v;
}

/** Keyboard shortcut that ignores typing in inputs/textareas/selects and contenteditable. */
export function useHotkey(key: string, handler: (e: KeyboardEvent) => void, enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (document.querySelector("[role=dialog][data-open=true]")) return;
      if (e.key.toLowerCase() === key.toLowerCase()) {
        e.preventDefault();
        handler(e);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [key, handler, enabled]);
}
