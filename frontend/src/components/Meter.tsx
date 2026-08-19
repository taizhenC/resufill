/**
 * One number against the two lines that give it meaning: the threshold, and the ceiling.
 *
 * Shared by the preview and the score panel on purpose — they are the same scale before and
 * after a run, and drawing them differently would invite the reader to compare two pictures
 * instead of two numbers. The hatched tail is what this record cannot reach for this posting,
 * which is the part of the bar no rewrite can win.
 */
export function Meter({
  what,
  value,
  threshold,
  ceiling,
}: {
  what: string;
  value: number;
  threshold: number;
  ceiling?: number | null;
}) {
  const pct = (n: number) => `${Math.max(0, Math.min(100, n))}%`;
  const capped = ceiling !== undefined && ceiling !== null && ceiling < 100;
  const sameNumber = capped && Math.abs(ceiling! - value) < 0.05;

  return (
    <div
      class="meter"
      role="img"
      aria-label={`${what} ${value.toFixed(1)} of 100, threshold ${threshold}${
        capped && !sameNumber ? `, ceiling ${ceiling!.toFixed(1)}` : ""
      }`}
      style={{
        "--reach": pct(value),
        "--mark": pct(threshold),
        "--cap": capped ? pct(ceiling!) : "100%",
      }}
    >
      <span class="meter-fill" />
      {capped && <span class="meter-cap" />}
      <span class="meter-mark" />
    </div>
  );
}
