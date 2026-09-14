"use client";

/**
 * A small animated voice-waveform — the recurring visual motif for "Alina is
 * listening / thinking" moments (dashboard ask panel, login mark, the
 * meeting agent tab). Pure CSS animation, no library, themes with
 * currentColor so it always matches its surrounding context.
 */
export default function Waveform({
  size = 16,
  active = true,
  bars = 5,
}: {
  size?: number;
  active?: boolean;
  bars?: number;
}) {
  const heights = [0.45, 0.8, 1, 0.65, 0.9, 0.5, 0.75];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: Math.max(1, size / 10),
        height: size,
        width: size,
        justifyContent: "center",
      }}
      aria-hidden="true"
    >
      {Array.from({ length: bars }).map((_, i) => (
        <span
          key={i}
          style={{
            display: "block",
            width: Math.max(1.5, size / 7),
            height: `${(heights[i % heights.length]) * size}px`,
            background: "currentColor",
            borderRadius: 2,
            animation: active ? `waveform-bar 0.9s ease-in-out ${i * 0.11}s infinite` : "none",
            opacity: active ? 1 : 0.45,
            transformOrigin: "center",
          }}
        />
      ))}
    </span>
  );
}
