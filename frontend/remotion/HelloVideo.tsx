import { AbsoluteFill, Sequence, useCurrentFrame, useVideoConfig } from "remotion";

export const HelloVideo = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const seconds = (frame / fps).toFixed(1);

  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        background:
          "radial-gradient(circle at 20% 20%, #2a9d8f 0%, #264653 40%, #1b263b 100%)",
        color: "#f1faee",
        fontFamily: "Georgia, 'Times New Roman', serif",
      }}
    >
      <div style={{ textAlign: "center", padding: 32, border: "2px solid #f1faee", borderRadius: 16 }}>
        <h1 style={{ fontSize: 72, margin: 0, letterSpacing: 1.2 }}>TitanShift</h1>
        <p style={{ fontSize: 28, marginTop: 16, marginBottom: 0 }}>Remotion MP4 Smoke</p>
        <Sequence from={0}>
          <p style={{ fontSize: 20, opacity: 0.9, marginTop: 18 }}>t={seconds}s</p>
        </Sequence>
      </div>
    </AbsoluteFill>
  );
};
