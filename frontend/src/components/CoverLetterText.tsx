import { useEffect, useRef, useState } from "preact/hooks";

import { api, ApiError } from "../api";
import type { CoverLetterFile, LetterParagraph } from "../types";

/** Addressee, paragraphs, signoff — blank line between, which is what a form field expects. */
function plainText(letter: CoverLetterFile): string {
  return [letter.addressee, ...paragraphsOf(letter).map((p) => p.text), letter.signoff]
    .filter((part) => part?.trim())
    .join("\n\n");
}

/** Read off disk, so an older or half-written file must not take the run view down with it. */
function paragraphsOf(letter: CoverLetterFile): LetterParagraph[] {
  return Array.isArray(letter.paragraphs) ? letter.paragraphs : [];
}

/**
 * The cover letter as text you can paste.
 *
 * A cover letter goes into a textarea on an application form far more often than it goes up
 * as a PDF, and a PDF preview is useless for that. The text lives in a real textarea rather
 * than a styled block so that the fallback is the same control as the happy path: this page
 * is served over plain HTTP on localhost, `navigator.clipboard` is not guaranteed to exist
 * there, and when it does not the user can still select the text and copy it themselves.
 */
export function CoverLetterText({ runId }: { runId: string }) {
  const [letter, setLetter] = useState<CoverLetterFile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [clipboardFailed, setClipboardFailed] = useState(false);
  const box = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    let current = true;
    api
      .coverLetter(runId)
      .then((body) => current && setLetter(body))
      .catch((reason: unknown) =>
        current
          ? setError(
              reason instanceof ApiError
                ? reason.message
                : "could not read cover_letter.json from this run",
            )
          : undefined,
      );
    return () => {
      current = false;
    };
  }, [runId]);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2400);
    return () => clearTimeout(timer);
  }, [copied]);

  if (error) return <p class="error">{error}</p>;
  if (!letter) return <p class="field-hint">Reading the letter…</p>;

  const text = plainText(letter);
  const count = paragraphsOf(letter).length;

  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setClipboardFailed(false);
    } catch {
      // Focus selects the whole letter, so the fallback costs one keystroke rather than a drag.
      setClipboardFailed(true);
      box.current?.focus();
    }
  }

  return (
    <div class="letter">
      <div class="letter-bar">
        <button type="button" class="secondary" onClick={() => void copy()}>
          {copied ? "Copied" : "Copy"}
        </button>
        <span class="field-hint">
          {clipboardFailed
            ? "the browser would not hand over the clipboard — select the text and copy it"
            : `${count} paragraph${count === 1 ? "" : "s"}, ready to paste`}
        </span>
      </div>
      <textarea
        ref={box}
        class="letter-text"
        readOnly
        rows={16}
        value={text}
        aria-label="Cover letter, plain text"
        onFocus={(event) => (event.currentTarget as HTMLTextAreaElement).select()}
      />
    </div>
  );
}
