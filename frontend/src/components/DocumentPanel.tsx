import { useState } from "preact/hooks";

import { api } from "../api";
import { documentLabel } from "../run";
import type { Claim, DocumentRecord } from "../types";

export function DocumentPanel({ runId, document }: { runId: string; document: DocumentRecord }) {
  const verify = document.verify;
  return (
    <section class="card">
      <header class="run-head">
        <h2>{documentLabel(document.kind)}</h2>
        <span class={`pill ${document.ok ? "pill-ok" : "pill-bad"}`}>
          {document.ok ? "ready to send" : "did not pass"}
        </span>
      </header>

      <p class="field-hint">
        {document.iterations} iteration{document.iterations === 1 ? "" : "s"}
        {verify && ` · ${verify.page_count} page${verify.page_count === 1 ? "" : "s"}`}
        {verify &&
          (verify.ok
            ? " · every heading and bullet survived extraction"
            : " · the PDF did not survive its own parse check")}
      </p>

      {verify && !verify.ok && (
        <ul class="gap-list error">
          {verify.missing.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      )}

      {document.violations.length > 0 && (
        <div class="gap-group">
          <h3>Unresolved grounding violations</h3>
          <p class="field-hint">The loop ended with these outstanding. No PDF was written.</p>
          <ul class="gap-list error">
            {document.violations.map((violation) => (
              <li key={violation}>{violation}</li>
            ))}
          </ul>
        </div>
      )}

      {(document.removed ?? []).length > 0 && (
        <div class="gap-group">
          <h3>Removed so the rest could be kept</h3>
          <p class="field-hint">
            The draft claimed these and the record could not back them, so they were cut and what
            remained went back through the same gate. This document is shorter than the one the
            model wrote — that is the trade, and it is said here rather than absorbed silently.
          </p>
          <ul class="gap-list">
            {document.removed.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      {document.blocked_terms.length > 0 && (
        <div class="gap-group">
          <h3>Blocked by the grounding gate</h3>
          <p class="field-hint">
            The tailor tried to claim these and could not support them. They were removed rather
            than rephrased. If any is genuinely true of you, that is a hole in{" "}
            <code>profile.yaml</code>, not in the résumé.
          </p>
          <ul class="chips">
            {document.blocked_terms.map((term) => (
              <li class="chip chip-bad" key={term}>
                {term}
              </li>
            ))}
          </ul>
        </div>
      )}

      {document.pdf && <PdfPreview runId={runId} name={document.pdf} />}
      {document.claims.length > 0 && <CitationAudit claims={document.claims} />}
    </section>
  );
}

/** The thing a browser is unambiguously better at than a terminal: showing you the PDF. */
function PdfPreview({ runId, name }: { runId: string; name: string }) {
  const url = api.fileUrl(runId, name);
  return (
    <div class="pdf">
      <div class="pdf-bar">
        <code>{name}</code>
        <a href={url} download={name}>
          download
        </a>
      </div>
      <iframe src={url} title={name} />
    </div>
  );
}

/**
 * Claim by claim, with the source that licensed it.
 *
 * This is the receipt, and it is the one view the CLI structurally cannot give you —
 * report.md prints the same information as a flat list at the bottom that nobody reads.
 * The source text was snapshotted at generation time, so editing profile.yaml afterwards
 * cannot quietly change what a résumé you already sent appears to have stood on.
 */
function CitationAudit({ claims }: { claims: Claim[] }) {
  const [open, setOpen] = useState(false);
  const uncited = claims.filter((claim) => claim.sources.length === 0).length;

  return (
    <div class="gap-group">
      <button class="link" onClick={() => setOpen(!open)}>
        {open ? "▾" : "▸"} Audit all {claims.length} claim{claims.length === 1 ? "" : "s"}
        {uncited > 0 && ` — ${uncited} with no source`}
      </button>

      {open && (
        <ol class="claims">
          {claims.map((claim) => (
            <li key={claim.where}>
              <p class="claim-text">{claim.text}</p>
              {claim.sources.length === 0 ? (
                <p class="error">no source — the gate should have caught this</p>
              ) : (
                claim.sources.map((source) => (
                  <details key={source.id} class="source">
                    <summary>
                      <code>{source.id}</code> {source.label}
                    </summary>
                    <blockquote>{source.text}</blockquote>
                  </details>
                ))
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
