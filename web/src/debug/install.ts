import { useAppStore } from "../store";

const originalConsole = {
  log: console.log.bind(console),
  info: console.info.bind(console),
  warn: console.warn.bind(console),
  error: console.error.bind(console),
};

function stringify(args: unknown[]): string {
  return args
    .map((a) => {
      if (a instanceof Error) return `${a.name}: ${a.message}`;
      if (typeof a === "object") {
        try {
          return JSON.stringify(a);
        } catch {
          return String(a);
        }
      }
      return String(a);
    })
    .join(" ");
}

export function installDebug(): void {
  // Console patches
  (["log", "info", "warn", "error"] as const).forEach((level) => {
    console[level] = (...args: unknown[]) => {
      originalConsole[level](...args);
      try {
        useAppStore.getState().pushDebug({
          category: level === "error" || level === "warn" ? "error" : "console",
          level,
          message: stringify(args),
        });
      } catch {
        /* avoid recursion */
      }
    };
  });

  // Uncaught errors
  window.addEventListener("error", (e) => {
    useAppStore.getState().pushDebug({
      category: "error",
      level: "error",
      message: `Uncaught: ${e.message}`,
      details: e.error?.stack,
    });
  });

  // Unhandled promise rejections
  window.addEventListener("unhandledrejection", (e) => {
    const reason = e.reason;
    useAppStore.getState().pushDebug({
      category: "error",
      level: "error",
      message: `Unhandled rejection: ${reason?.message ?? String(reason)}`,
      details: reason?.stack,
    });
  });

  // Fetch wrapper
  const originalFetch = window.fetch.bind(window);
  window.fetch = async (...args: Parameters<typeof fetch>) => {
    const url =
      typeof args[0] === "string"
        ? args[0]
        : args[0] instanceof URL
          ? args[0].toString()
          : (args[0] as Request).url;
    const method = (args[1]?.method ?? "GET").toUpperCase();
    const t0 = performance.now();
    try {
      const res = await originalFetch(...args);
      const duration = Math.round(performance.now() - t0);
      useAppStore.getState().pushDebug({
        category: "network",
        level: res.ok ? "info" : "warn",
        message: `${method} ${url} → ${res.status} (${duration}ms)`,
      });
      return res;
    } catch (err) {
      const duration = Math.round(performance.now() - t0);
      useAppStore.getState().pushDebug({
        category: "network",
        level: "error",
        message: `${method} ${url} → FAILED (${duration}ms)`,
        details: (err as Error).message,
      });
      throw err;
    }
  };
}
