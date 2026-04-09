import { Component, type ReactNode } from "react";
import { useAppStore } from "../store";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: { componentStack: string }): void {
    useAppStore.getState().pushDebug({
      category: "error",
      level: "error",
      message: `React error: ${error.message}`,
      details: info.componentStack,
    });
  }

  reset = (): void => {
    this.setState({ hasError: false, error: null });
  };

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div className="absolute inset-0 flex items-center justify-center bg-black/80 text-red-300 p-8 z-50">
          <div className="max-w-xl">
            <h2 className="text-xl font-bold mb-2">Something broke</h2>
            <pre className="text-xs whitespace-pre-wrap mb-4">
              {this.state.error?.message}
            </pre>
            <button
              onClick={this.reset}
              className="px-4 py-2 bg-red-700 hover:bg-red-600 rounded"
            >
              Reset
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
