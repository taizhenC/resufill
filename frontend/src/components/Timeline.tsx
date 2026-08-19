import { documentLabel, stageLabel } from "../run";
import type { AttemptGroup, TimelineItem } from "../run";
import type { StageEvent } from "../types";

/**
 * The run as attempts rather than as stages.
 *
 * Both things a reader needs from the log are per-attempt facts — what this draft scored, and
 * what the grounding gate did to it — and both used to scroll past as one line among fifty.
 * `live` is what separates "still working" from "stopped here", which the events cannot say
 * on their own: an attempt with no `scored` is either in flight or was cut off.
 */
export function Timeline({ items, live }: { items: TimelineItem[]; live: boolean }) {
  const lastAttempt = items.reduce(
    (found, item) => (item.kind === "attempt" ? item.key : found),
    "",
  );

  return (
    <ol class="timeline">
      {items.map((item) =>
        item.kind === "milestone" ? (
          <Milestone key={item.key} event={item.event} />
        ) : (
          <Attempt
            key={item.key}
            group={item.group}
            live={live && item.key === lastAttempt && item.group.outcome === "open"}
          />
        ),
      )}
    </ol>
  );
}

function Milestone({ event }: { event: StageEvent }) {
  return (
    <li class="tl tl-milestone">
      <span class="tl-dot" aria-hidden="true" />
      <span class="tl-title">{stageLabel(event.stage)}</span>
    </li>
  );
}

function Attempt({ group, live }: { group: AttemptGroup; live: boolean }) {
  // The pill is about the grounding gate, which is the only thing that can throw a draft away.
  // Whether the PDF parsed is a separate check and stays in the facts line, so an attempt that
  // passed the gate and then failed extraction reads as the two different results it is.
  const verdict = live
    ? { tone: "tl-open", pill: "", say: `${stageLabel(group.stage)}…` }
    : group.outcome === "rejected"
      ? { tone: "tl-rejected", pill: "thrown away", say: "" }
      : group.outcome === "finished"
        ? group.repaired
          ? { tone: "tl-repaired", pill: "trimmed, then passed", say: "" }
          : { tone: "tl-kept", pill: "passed the gate", say: "" }
        : { tone: "tl-open", pill: "did not finish", say: `stopped at ${stageLabel(group.stage).toLowerCase()}` };

  return (
    <li class={`tl tl-attempt ${verdict.tone} ${live ? "tl-live" : ""}`}>
      <span class="tl-dot" aria-hidden="true" />
      <div class="tl-body">
        <div class="tl-line">
          <span class="tl-title">
            {documentLabel(group.document)}
            <span class="tl-count">
              {" "}
              attempt {group.attempt} of {group.attempts}
            </span>
          </span>
          {verdict.pill && (
            <span class={`pill ${PILL_TONE[verdict.tone] ?? "pill-muted"}`}>{verdict.pill}</span>
          )}
        </div>

        {verdict.say && <p class="tl-say">{verdict.say}</p>}
        <Facts group={group} />

        {group.outcome === "rejected" && (
          <p class="tl-note">
            The gate could not cut the failing parts out and leave a document behind, so this draft
            was thrown away whole and the next attempt was told exactly what failed.
            {group.reason && (
              <>
                {" "}
                <code>{group.reason}</code>
              </>
            )}
          </p>
        )}

        {group.repaired && group.outcome !== "rejected" && (
          // Not an error, and must not be dressed as one: this document shipped. It is simply
          // shorter than the model wrote, and saying so is the honest half of the result.
          <p class="tl-note">
            {group.dropped || "Some"} claim{group.dropped === 1 ? "" : "s"} the record could not back{" "}
            {group.dropped === 1 ? "was" : "were"} cut out; what remained passed the same gate and
            was rendered.
            {group.reason && (
              <>
                {" "}
                <code>{group.reason}</code>
              </>
            )}
          </p>
        )}
      </div>
    </li>
  );
}

const PILL_TONE: Record<string, string> = {
  "tl-rejected": "pill-bad",
  "tl-repaired": "pill-note",
  "tl-kept": "pill-ok",
  "tl-open": "pill-muted",
};

function Facts({ group }: { group: AttemptGroup }) {
  const facts: string[] = [];
  if (group.score !== undefined) facts.push(`score ${group.score.toFixed(1)}`);
  if (group.pages !== undefined) facts.push(`${group.pages} page${group.pages === 1 ? "" : "s"}`);
  if (group.words !== undefined) facts.push(`${group.words} words`);
  if (!facts.length && group.parses === undefined) return null;

  return (
    <p class="tl-facts">
      {facts.join(" · ")}
      {group.parses !== undefined && (
        <>
          {facts.length > 0 && " · "}
          {/* The check that actually matters: the text was extracted back out of the PDF and
              every heading and bullet was still there. */}
          <span class={group.parses ? "" : "tl-fail"}>
            {group.parses ? "PDF parses" : "PDF failed its parse check"}
          </span>
        </>
      )}
    </p>
  );
}
