/**
 * usePlugins hook — discovers and loads dashboard plugins.
 *
 * 1. Fetches plugin manifests from GET /api/dashboard/plugins
 * 2. Injects CSS <link> tags for plugins that declare css
 * 3. Loads plugin JS bundles via <script> tags
 * 4. Waits for plugins to call register() and resolves them
 */

import { useState, useEffect, useRef } from "react";
import { api, HERMES_BASE_PATH } from "@/lib/api";
import type { PluginManifest, RegisteredPlugin } from "./types";
import {
  getPluginComponent,
  onPluginRegistered,
  notifyPluginRegistry,
  setPluginLoadError,
} from "./registry";

/** Survive React remounts / brief reload cycles without clearing the sidebar. */
let manifestsCache: PluginManifest[] | null = null;
let manifestsPromise: Promise<PluginManifest[]> | null = null;
const loadedScriptBases = new Set<string>();

function fetchManifestsOnce(): Promise<PluginManifest[]> {
  if (manifestsCache) {
    return Promise.resolve(manifestsCache);
  }
  if (!manifestsPromise) {
    manifestsPromise = api
      .getPlugins()
      .then((list) => {
        manifestsCache = list;
        return list;
      })
      .catch((err) => {
        manifestsPromise = null;
        throw err;
      });
  }
  return manifestsPromise;
}

export function usePlugins() {
  const [manifests, setManifests] = useState<PluginManifest[]>(
    () => manifestsCache ?? [],
  );
  const [plugins, setPlugins] = useState<RegisteredPlugin[]>([]);
  const [loading, setLoading] = useState(() => manifestsCache === null);
  const mountedRef = useRef(true);

  // Fetch manifests on mount (deduped across remounts).
  useEffect(() => {
    mountedRef.current = true;
    void fetchManifestsOnce()
      .then((list) => {
        if (!mountedRef.current) return;
        setManifests(list);
        if (list.length === 0) setLoading(false);
      })
      .catch(() => {
        if (!mountedRef.current) return;
        setLoading(false);
      });
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // Load plugin assets when manifests arrive.
  useEffect(() => {
    if (manifests.length === 0) return;

    const injectedScripts: HTMLScriptElement[] = [];

    for (const manifest of manifests) {
      // Inject CSS if specified.
      const assetVersion = encodeURIComponent(
        `${manifest.version || "0"}:${manifest.entry || ""}:${manifest.css || ""}`,
      );
      if (manifest.css) {
        const cssBaseUrl = `${HERMES_BASE_PATH}/dashboard-plugins/${manifest.name}/${manifest.css}`;
        const cssUrl = `${cssBaseUrl}?v=${assetVersion}`;
        if (!document.querySelector(`link[data-hermes-plugin-css="${manifest.name}"]`)) {
          const link = document.createElement("link");
          link.rel = "stylesheet";
          link.href = cssUrl;
          link.setAttribute("data-hermes-plugin-css", manifest.name);
          document.head.appendChild(link);
        }
      }

      // Load JS bundle. Always include the manifest version in the asset URL so
      // production browsers don't keep executing a stale dashboard plugin after
      // its dist/index.js changes. In dev, add a timestamp as well so Vite HMR
      // can clear the in-memory registry while the browser would otherwise
      // never re-execute a previously cached <script> URL.
      const baseUrl = `${HERMES_BASE_PATH}/dashboard-plugins/${manifest.name}/${manifest.entry}`;
      const scriptSrc = import.meta.env.DEV
        ? `${baseUrl}?v=${assetVersion}&hermes_dv=${Date.now()}`
        : `${baseUrl}?v=${assetVersion}`;
      if (!import.meta.env.DEV) {
        if (loadedScriptBases.has(baseUrl)) continue;
        loadedScriptBases.add(baseUrl);
      }

      const script = document.createElement("script");
      script.setAttribute("data-hermes-plugin", manifest.name);
      script.src = scriptSrc;
      script.async = true;
      if (manifest.integrity && typeof manifest.integrity === "string") {
        script.integrity = manifest.integrity;
        script.crossOrigin = "anonymous";
      }
      script.onerror = () => {
        setPluginLoadError(manifest.name, "LOAD_FAILED");
        console.warn(
          `[plugins] Failed to load ${manifest.name} from ${scriptSrc} (open Network tab)`,
        );
      };
      script.onload = () => {
        notifyPluginRegistry();
        queueMicrotask(() => {
          if (getPluginComponent(manifest.name)) return;
          setPluginLoadError(manifest.name, "NO_REGISTER");
        });
      };
      document.body.appendChild(script);
      injectedScripts.push(script);
    }

    const timeout = setTimeout(() => setLoading(false), 2000);
    return () => {
      clearTimeout(timeout);
      if (import.meta.env.DEV) {
        for (const el of injectedScripts) {
          el.remove();
        }
      }
    };
  }, [manifests]);

  // Listen for plugin registrations and resolve them against manifests.
  useEffect(() => {
    function resolvePlugins() {
      const resolved: RegisteredPlugin[] = [];
      for (const manifest of manifests) {
        const component = getPluginComponent(manifest.name);
        if (component) {
          resolved.push({ manifest, component });
        }
      }
      setPlugins(resolved);
      if (resolved.length === manifests.length && manifests.length > 0) {
        setLoading(false);
      }
    }

    resolvePlugins();
    const unsub = onPluginRegistered(resolvePlugins);
    return unsub;
  }, [manifests]);

  return { plugins, manifests, loading };
}
