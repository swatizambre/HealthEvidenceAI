/** Draws a QR matrix from the server (rows of "0"/"1") as crisp SVG with a quiet zone. */
export function QrCode({
  modules,
  size = 176,
  label,
}: {
  modules: string[];
  size?: number;
  label: string;
}) {
  const count = modules.length;
  if (count === 0) return null;
  const border = 4;
  const total = count + border * 2;
  let path = "";
  modules.forEach((row, y) => {
    for (let x = 0; x < row.length; x += 1) {
      if (row[x] === "1") path += `M${x + border} ${y + border}h1v1h-1z`;
    }
  });
  return (
    <svg
      className="qr-code"
      width={size}
      height={size}
      viewBox={`0 0 ${total} ${total}`}
      shapeRendering="crispEdges"
      role="img"
      aria-label={label}
    >
      <rect width={total} height={total} fill="#ffffff" />
      <path d={path} fill="#000000" />
    </svg>
  );
}
