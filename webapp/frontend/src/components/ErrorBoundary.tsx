import React, { Component, ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  onError?: (error: Error, errorInfo: React.ErrorInfo) => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * Error Boundary component to catch React errors and prevent app crash.
 * Wrap critical routes/components with this to isolate failures.
 *
 * Usage:
 *   <ErrorBoundary fallback={<ErrorFallback />}>
 *     <Player />
 *   </ErrorBoundary>
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error("ErrorBoundary caught:", error, errorInfo);
    this.props.onError?.(error, errorInfo);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            minHeight: "200px",
            padding: "24px",
            textAlign: "center",
            color: "#fff",
          }}
        >
          <div style={{ fontSize: "48px", marginBottom: "16px" }}>😵</div>
          <h2 style={{ margin: "0 0 8px", fontSize: "18px" }}>Что-то пошло не так</h2>
          <p style={{ margin: "0 0 16px", opacity: 0.7, fontSize: "14px" }}>
            Произошла ошибка. Попробуйте обновить страницу.
          </p>
          <button
            onClick={this.handleRetry}
            style={{
              padding: "10px 20px",
              borderRadius: "8px",
              border: "none",
              background: "#7c4dff",
              color: "#fff",
              fontSize: "14px",
              cursor: "pointer",
            }}
          >
            Попробовать снова
          </button>
          {this.state.error && (
            <pre
              style={{
                marginTop: "16px",
                padding: "12px",
                background: "rgba(255,0,0,0.1)",
                borderRadius: "8px",
                fontSize: "12px",
                textAlign: "left",
                maxWidth: "100%",
                overflow: "auto",
              }}
            >
              {this.state.error.toString()}
            </pre>
          )}
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
