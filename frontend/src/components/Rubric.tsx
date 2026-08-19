import { useState } from "preact/hooks";

import type { RubricCheck } from "../types";

/**
 * The machine-readability rubric for a résumé, and the reads-it-well rubric for a letter.
 *
 * Both come back in the same shape from `ats.py` and `letter_review.py`, and both split
 * their checks the same way — a hard half about whether the document works at all, and an
 * advisory half about whether it is any good. The split is the thing worth rendering: a
 * failed advisory check is not an error, and showing it as one would push people to rewrite
 * documents that are fine.
 *
 * Passing checks are collapsed by default. The list of what was checked matters — it is how
 * you know the tool is not claiming more than it tested — but not as much as the failures.
 */
export function Rubric({ checks, kind }: { checks: RubricCheck[]; kind: string }) {
  const [showPassing, setShowPassing] = useState(false);
  if (!checks.length) return null;

  const failed = checks.filter((check) => !check.ok);
  const passed = checks.filter((check) => check.ok);
  // "parsing" is ats.py's word, "blocking" is letter_review.py's. Same meaning either side:
  // this one is not a matter of taste.
  const hard = (check: RubricCheck) => check.kind === "parsing" || check.kind === "blocking";

  return (
    <div class="gap-group">
      <h3>
        {kind === "cover_letter" ? "How it reads" : "Machine-readability"}{" "}
        <span class="count">
          {passed.length}/{checks.length}
        </span>
      </h3>
      <p class="field-hint">
        {kind === "cover_letter"
          ? "Whether the letter is worth reading, which is a different question from whether it is true — the grounding gate above owns that one."
          : "What a parser does with the document, and what a reader does with it. Nothing here is a score an employer computes."}
      </p>

      {failed.length > 0 && (
        <ul class="rubric">
          {failed.map((check) => (
            <li class={hard(check) ? "rubric-hard" : "rubric-soft"} key={check.name}>
              <span class="rubric-mark" aria-hidden="true">
                {hard(check) ? "✗" : "!"}
              </span>
              <div>
                <p class="rubric-name">
                  {check.name}
                  <span class="rubric-tag">{hard(check) ? "affects parsing" : "advisory"}</span>
                </p>
                <p class="field-hint">{check.detail}</p>
                {check.fix && <p class="rubric-fix">{check.fix}</p>}
              </div>
            </li>
          ))}
        </ul>
      )}

      {passed.length > 0 && (
        <>
          <button
            type="button"
            class="link"
            onClick={() => setShowPassing(!showPassing)}
            aria-expanded={showPassing}
          >
            {showPassing ? "▾" : "▸"} {passed.length} check{passed.length === 1 ? "" : "s"} passed
          </button>
          {showPassing && (
            <ul class="rubric rubric-quiet">
              {passed.map((check) => (
                <li key={check.name}>
                  <span class="rubric-mark" aria-hidden="true">
                    ✓
                  </span>
                  <div>
                    <p class="rubric-name">{check.name}</p>
                    <p class="field-hint">{check.detail}</p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
