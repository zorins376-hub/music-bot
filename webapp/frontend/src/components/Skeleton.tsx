/**
 * Skeleton Loader Component - shimmer effect placeholders
 */

interface SkeletonProps {
  width?: string | number;
  height?: string | number;
  borderRadius?: string | number;
  style?: Record<string, string | number>;
}

export function Skeleton({ width = "100%", height = 16, borderRadius = 4, style = {} }: SkeletonProps) {
  return (
    <div
      style={{
        width,
        height,
        borderRadius,
        background: "linear-gradient(90deg, rgba(255,255,255,0.06) 25%, rgba(255,255,255,0.12) 50%, rgba(255,255,255,0.06) 75%)",
        backgroundSize: "200% 100%",
        animation: "shimmer 1.5s infinite linear",
        ...style,
      }}
    />
  );
}

export function SkeletonTrack() {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        padding: "10px 12px",
        borderRadius: 10,
        marginBottom: 6,
        background: "rgba(255,255,255,0.04)",
      }}
    >
      {/* Cover placeholder */}
      <Skeleton width={44} height={44} borderRadius={8} style={{ marginRight: 12, flexShrink: 0 }} />
      {/* Text placeholders */}
      <div style={{ flex: 1 }}>
        <Skeleton width="70%" height={14} style={{ marginBottom: 6 }} />
        <Skeleton width="40%" height={12} />
      </div>
      {/* Duration placeholder */}
      <Skeleton width={36} height={12} style={{ marginLeft: 8 }} />
    </div>
  );
}

export function SkeletonPlayer() {
  return (
    <div style={{ textAlign: "center", padding: "16px 0" }}>
      {/* Cover skeleton */}
      <Skeleton
        width={240}
        height={240}
        borderRadius={20}
        style={{ margin: "0 auto 24px" }}
      />
      {/* Title skeleton */}
      <Skeleton width="60%" height={18} style={{ margin: "0 auto 8px" }} />
      {/* Artist skeleton */}
      <Skeleton width="40%" height={14} style={{ margin: "0 auto 16px" }} />
      {/* Slider skeleton */}
      <Skeleton width="80%" height={6} borderRadius={3} style={{ margin: "0 auto 24px" }} />
      {/* Controls skeleton */}
      <div style={{ display: "flex", justifyContent: "center", gap: 16 }}>
        <Skeleton width={40} height={40} borderRadius={20} />
        <Skeleton width={64} height={64} borderRadius={32} />
        <Skeleton width={40} height={40} borderRadius={20} />
      </div>
      <style>{`
        @keyframes shimmer {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
      `}</style>
    </div>
  );
}

export function SkeletonLyrics() {
  return (
    <div style={{ padding: 12 }}>
      {[...Array(12)].map((_, i) => (
        <Skeleton
          key={i}
          width={`${60 + Math.random() * 35}%`}
          height={16}
          style={{ marginBottom: 12 }}
        />
      ))}
      <style>{`
        @keyframes shimmer {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
      `}</style>
    </div>
  );
}
