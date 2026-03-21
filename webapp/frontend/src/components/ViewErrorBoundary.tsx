import { Component, type ComponentChildren } from "preact";

interface Props {
  viewName: string;
  fallbackColor?: string;
  children: ComponentChildren;
}

interface State {
  error: string | null;
}

export class ViewErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(err: Error): State {
    return { error: err?.message || "render error" };
  }

  componentDidCatch(err: Error): void {
    console.error(`[ViewErrorBoundary:${this.props.viewName}]`, err);
  }

  private reset = () => {
    this.setState({ error: null });
  };

  render(): ComponentChildren {
    if (!this.state.error) {
      return this.props.children;
    }

    const hint = this.props.fallbackColor || "var(--tg-theme-hint-color, #aaa)";

    return (
      <div style={{
        margin: "16px auto",
        maxWidth: 420,
        padding: "16px 18px",
        borderRadius: 16,
        background: "rgba(220, 53, 69, 0.10)",
        border: "1px solid rgba(220, 53, 69, 0.35)",
        color: "var(--tg-theme-text-color, #eee)",
      }}>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>
          {this.props.viewName}: UI crash recovered
        </div>
        <div style={{ fontSize: 12, color: hint, marginBottom: 12 }}>
          {this.state.error}
        </div>
        <button
          onClick={this.reset}
          style={{
            padding: "8px 12px",
            borderRadius: 10,
            border: "1px solid rgba(220, 53, 69, 0.45)",
            background: "rgba(220, 53, 69, 0.22)",
            color: "#fff",
            fontSize: 12,
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          Retry View
        </button>
      </div>
    );
  }
}
