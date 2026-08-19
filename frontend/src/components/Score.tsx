import type { ScoreRecord } from "../types";

const STOP_REASON: Record<string, string> = {
  threshold: "the score reached the threshold",
  ceiling: "the score reached what your record can reach for this posting",
  plateau: "another rewrite stopped buying anything",
  exhausted: "the iteration budget ran out",
  ungrounded: "no draft survived the grounding gate",
  cancelled: "the run was cancelled",
};

/**
 * The score, as a breakdown and never as a bare number.
 *
 * No employer computes this. Greenhouse and Lever do not rank by keyword at all; Taleo and
 * iCIMS keyword search happens recruiter-side. It is a stopping rule for the rewrite loop,
 * and printing it alone would invite exactly the misreading the caveat exists to prevent.
 */
export function ScorePanel({ score }: { score: ScoreRecord }) {
  // `?? null` rather than a bare read: a run.json written before the ceiling existed has no
  // such key, and `undefined` slipped past every `=== null` guard below straight into
  // `.toFixed`, which blanked the whole run view for every historical run.
  const ceiling = score.ceiling ?? null;
  const unreachable = score.unreachable ?? [];
  // "Below the threshold" is the wrong headline when the threshold was never available to
  // this record. Which of the three it is changes what the reader should do next, so the
  // pill says which rather than making them work it out from the number.
  const reachable = ceiling === null || ceiling >= score.threshold;
  const verdict = score.met
    ? { tone: "pill-ok", text: "met the threshold" }
    : !reachable
      ? { tone: "pill-ok", text: `all this record could reach — ${ceiling!.toFixed(1)} max here` }
      : (score.at_ceiling ?? false)
        ? { tone: "pill-warn", text: "at this record's ceiling" }
        : { tone: "pill-warn", text: `below the threshold of ${score.threshold}` };

  return (
    <section class="card">
      <header class="score-head">
        <div>
          <span class="score-total">{score.total.toFixed(1)}</span>
          <span class="score-outof">/ {ceiling === null ? 100 : ceiling.toFixed(1)} reachable</span>
        </div>
        <span class={`pill ${verdict.tone}`}>{verdict.text}</span>
      </header>

      <p class="caveat">
        A <strong>local proxy</strong>, not a metric any employer computes. Because the grounding
        gate blocks invention, the loop cannot raise this by making things up — so a low ceiling
        means the role wants things your record does not have.
      </p>

      {ceiling !== null && !reachable && (
        <p class="field-hint">
          The threshold of {score.threshold} was never reachable here: this posting caps at{" "}
          {ceiling.toFixed(1)} for your record
          {unreachable.length > 0 && <> because of {unreachable.slice(0, 8).join(", ")}</>}
          . That is the answer to the question, not a failure to answer it.
        </p>
      )}
      {ceiling !== null && reachable && !score.met && (
        <p class="field-hint">
          {ceiling.toFixed(1)} was reachable for your record, so this shortfall is tailoring rather
          than experience — look at the unsurfaced keywords below.
        </p>
      )}
      {score.stop_reason && (
        <p class="field-hint">
          The loop stopped because <strong>{STOP_REASON[score.stop_reason] ?? score.stop_reason}</strong>.
        </p>
      )}

      <table class="components">
        <thead>
          <tr>
            <th>Component</th>
            <th class="num">Weight</th>
            <th class="num">Score</th>
            <th class="num">Points</th>
          </tr>
        </thead>
        <tbody>
          {score.components.map((component) => (
            <tr key={component.name}>
              <td>
                {component.label}
                <small>{component.detail}</small>
              </td>
              <td class="num">{component.weight.toFixed(2)}</td>
              <td class="num">
                <span class="bar" style={{ "--fill": `${Math.round(component.raw * 100)}%` }}>
                  {Math.round(component.raw * 100)}%
                </span>
              </td>
              <td class="num">{component.points.toFixed(1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

/**
 * The gaps, split into the two kinds that mean different things. This distinction is the
 * most useful thing the tool produces and report.md buries it in prose.
 */
export function GapPanel({ score }: { score: ScoreRecord }) {
  const { gaps_absent: absent, gaps_unsurfaced: unsurfaced } = score;
  if (!absent.length && !unsurfaced.length) {
    return (
      <section class="card">
        <h2>Gaps</h2>
        <p class="field-hint">Every keyword the posting named appears on the résumé.</p>
      </section>
    );
  }

  return (
    <section class="card">
      <h2>Gaps</h2>

      {absent.length > 0 && (
        <div class="gap-group">
          <h3>Not in your record at all</h3>
          <p class="field-hint">
            The posting asks for these and nothing in <code>profile.yaml</code> or the evidence
            corpus supports them. They were deliberately left out. This is what the role would need
            you to go and do.
          </p>
          <ul class="chips">
            {absent.map((gap) => (
              <li class="chip chip-bad" key={gap.keyword}>
                {gap.keyword}
              </li>
            ))}
          </ul>
        </div>
      )}

      {unsurfaced.length > 0 && (
        <div class="gap-group">
          <h3>In your record, but not on this résumé</h3>
          <p class="field-hint">
            These you have. Fixable by editing the record or rerunning — unlike the list above.
          </p>
          <ul class="gap-list">
            {unsurfaced.map((gap) => (
              <li key={gap.keyword}>
                <strong>{gap.keyword}</strong>
                {gap.where && <span class="field-hint"> recorded in: {gap.where}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {score.unaddressed_qualifications.length > 0 && (
        <div class="gap-group">
          <h3>Qualifications the résumé does not answer</h3>
          <ul class="gap-list">
            {score.unaddressed_qualifications.map((qualification) => (
              <li key={qualification}>{qualification}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
