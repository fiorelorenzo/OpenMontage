import { AbsoluteFill, Img, staticFile } from "remotion";
import { loadFont } from "@remotion/google-fonts/Inter";

// Crisp, heavy type for thumbnails. The agent picks weights per layer.
const { fontFamily } = loadFont("normal", {
  weights: ["400", "700", "800", "900"],
  subsets: ["latin"],
});

// Resolve asset path — URLs pass through, absolute paths become file://, the
// rest resolve within public/ via staticFile (same rule as Explainer).
function resolveAsset(src: string): string {
  if (!src) return src;
  if (src.startsWith("http://") || src.startsWith("https://") || src.startsWith("data:")) {
    return src;
  }
  const clean = src.replace(/^file:\/\/\/?/, "");
  if (clean.startsWith("/") || /^[A-Za-z]:[\\/]/.test(clean)) {
    return `file://${clean.startsWith("/") ? "" : "/"}${clean.replace(/\\/g, "/")}`;
  }
  return staticFile(clean);
}

type Anchor = "tl" | "tc" | "tr" | "ml" | "mc" | "mr" | "bl" | "bc" | "br";

interface Layer {
  type?: "text" | "box" | "image";
  text?: string;
  src?: string; // for type "image"
  // Position as percent of the canvas; `anchor` is the point of the layer placed at (x,y).
  x: number;
  y: number;
  anchor?: Anchor;
  // Text styling
  fontSize?: number;
  fontWeight?: number | string;
  color?: string;
  align?: "left" | "center" | "right";
  uppercase?: boolean;
  italic?: boolean;
  letterSpacing?: number;
  lineHeight?: number;
  maxWidth?: number; // px — wraps text
  stroke?: { width: number; color: string };
  shadow?: boolean | string;
  // Box / pill / accent bar; also used as a highlight background behind text via `padding`.
  width?: number;
  height?: number;
  bg?: string;
  radius?: number;
  padding?: [number, number]; // [vertical, horizontal] — turns a text layer into a filled pill
  rotate?: number;
  opacity?: number;
}

interface Background {
  image?: string;
  color?: string;
  gradient?: string; // any CSS gradient
}

interface Scrim {
  color?: string; // default near-black
  direction?: "left" | "right" | "top" | "bottom" | "radial";
  opacity?: number; // 0-1 peak opacity
  coverage?: number; // 0-1 fraction of the canvas the scrim spans (default 0.6)
}

export interface ThumbnailProps {
  [key: string]: unknown;
  width?: number;
  height?: number;
  background?: Background;
  scrim?: Scrim;
  vignette?: boolean;
  layers: Layer[];
}

const ANCHOR_TRANSFORM: Record<Anchor, string> = {
  tl: "translate(0, 0)",
  tc: "translate(-50%, 0)",
  tr: "translate(-100%, 0)",
  ml: "translate(0, -50%)",
  mc: "translate(-50%, -50%)",
  mr: "translate(-100%, -50%)",
  bl: "translate(0, -100%)",
  bc: "translate(-50%, -100%)",
  br: "translate(-100%, -100%)",
};

function scrimGradient(s: Scrim): string {
  const color = s.color || "rgba(4, 8, 16, OPACITY)";
  const peak = s.opacity ?? 0.78;
  const cov = Math.max(0.05, Math.min(1, s.coverage ?? 0.6));
  const c = (o: number) =>
    color.includes("OPACITY") ? color.replace("OPACITY", String(o)) : color;
  const stops = `${c(peak)} 0%, ${c(peak * 0.6)} ${Math.round(cov * 55)}%, ${c(0)} ${Math.round(cov * 100)}%`;
  switch (s.direction || "left") {
    case "right":
      return `linear-gradient(to left, ${stops})`;
    case "top":
      return `linear-gradient(to bottom, ${stops})`;
    case "bottom":
      return `linear-gradient(to top, ${stops})`;
    case "radial":
      return `radial-gradient(ellipse at center, ${c(0)} ${Math.round((1 - cov) * 100)}%, ${c(peak)} 100%)`;
    default:
      return `linear-gradient(to right, ${stops})`;
  }
}

const LayerView: React.FC<{ layer: Layer }> = ({ layer }) => {
  const anchor = layer.anchor || "tl";
  const base: React.CSSProperties = {
    position: "absolute",
    left: `${layer.x}%`,
    top: `${layer.y}%`,
    transform: `${ANCHOR_TRANSFORM[anchor]}${layer.rotate ? ` rotate(${layer.rotate}deg)` : ""}`,
    opacity: layer.opacity ?? 1,
  };

  if (layer.type === "image" && layer.src) {
    return (
      <Img
        src={resolveAsset(layer.src)}
        style={{ ...base, width: layer.width, height: layer.height, borderRadius: layer.radius, objectFit: "contain" }}
      />
    );
  }

  if (layer.type === "box") {
    return (
      <div
        style={{
          ...base,
          width: layer.width ?? 100,
          height: layer.height ?? 12,
          background: layer.bg || "#22D3EE",
          borderRadius: layer.radius ?? 0,
        }}
      />
    );
  }

  // text (default)
  const shadow =
    layer.shadow === true
      ? "0 6px 28px rgba(0,0,0,0.65)"
      : typeof layer.shadow === "string"
        ? layer.shadow
        : undefined;
  const textStyle: React.CSSProperties = {
    ...base,
    margin: 0,
    fontFamily,
    fontWeight: (layer.fontWeight as any) ?? 800,
    fontStyle: layer.italic ? "italic" : "normal",
    fontSize: layer.fontSize ?? 96,
    lineHeight: layer.lineHeight ?? 1.02,
    color: layer.color || "#F8FAFC",
    textAlign: layer.align || "left",
    letterSpacing: layer.letterSpacing,
    textTransform: layer.uppercase ? "uppercase" : "none",
    maxWidth: layer.maxWidth,
    whiteSpace: layer.maxWidth ? "normal" : "pre",
    WebkitTextStroke: layer.stroke ? `${layer.stroke.width}px ${layer.stroke.color}` : undefined,
    textShadow: shadow,
    // padding turns the text into a filled highlight pill
    padding: layer.padding ? `${layer.padding[0]}px ${layer.padding[1]}px` : undefined,
    background: layer.bg,
    borderRadius: layer.radius,
  };
  return <div style={textStyle}>{layer.text}</div>;
};

export const Thumbnail: React.FC<ThumbnailProps> = ({ background, scrim, vignette, layers }) => {
  const bg = background || {};
  return (
    <AbsoluteFill style={{ background: bg.color || "#05070D", overflow: "hidden" }}>
      {bg.image && (
        <Img src={resolveAsset(bg.image)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      )}
      {bg.gradient && <AbsoluteFill style={{ background: bg.gradient }} />}
      {scrim && <AbsoluteFill style={{ background: scrimGradient(scrim) }} />}
      {vignette && (
        <AbsoluteFill
          style={{ background: "radial-gradient(ellipse at center, transparent 55%, rgba(0,0,0,0.55) 100%)" }}
        />
      )}
      {(layers || []).map((layer, i) => (
        <LayerView key={i} layer={layer} />
      ))}
    </AbsoluteFill>
  );
};
