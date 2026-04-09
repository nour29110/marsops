import { useAppStore } from "../store";

export function logUserAction(action: string, details?: string): void {
  useAppStore.getState().pushDebug({
    category: "user",
    level: "info",
    message: action,
    details,
  });
}
