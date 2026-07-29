import type { ScoreRecord } from "../types";

/**
 * The score, as a breakdown and never as a bare number.
 *
 * No employer computes this. Greenhouse and Lever do not rank by keyword at all; Taleo and
 * iCIMS keyword search happens recruiter-side. It is a stopping rule for the rewrite loop,
 * and printing it alone would invite exactly the misreading the caveat exists to prevent.
 */
export function ScorePanel({ score }: { score: ScoreRecord }) {
  return (
    <section class="card">
      <header class="score-head">
        <div>
          <span class="score-total">{score.total.toFixed(1)}</span>
          <span class="score-outof">/ 100</span>
        </div>
        <span class={`pill ${score.met ? "pill-ok" : "pill-warn"}`}>
          {score.met ? "met the threshold" : `below the threshold of ${score.threshold}`}
        </span>
      </header>

      <p class="caveat">
        A <strong>local proxy</strong>, not a metric any employer computes. Because the grounding
        gate blocks invention, the loop cannot raise this by making things up — so a low ceiling
        means the role wants things your record does not have.
      </p>

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
