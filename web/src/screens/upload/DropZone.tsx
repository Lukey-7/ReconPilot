/**
 * Where the day's files go in: chosen or dropped, several at once. Files go up as soon as
 * they arrive; the server stores them, validates the whole set it holds for the day and
 * answers. A file whose name ReconPilot does not read is listed and not sent, so one stray
 * file does not hold up the rest.
 *
 * The upload's state lives in `useDropZone`, held by the screen, so it survives the drop
 * zone moving on the screen once the files are valid.
 */
import { type DragEvent, useId, useState } from "react";

import { ApiError } from "../../api/client";
import { useUploadFiles } from "../../api/queries";
import type { ExpectedFile } from "../../api/types";
import { Icon } from "../../components/Icon";
import { sizeText } from "./FileChecklist";

/** The file's own name, without any folder a browser may send. */
function baseName(name: string): string {
  return name.replace(/\\/g, "/").split("/").pop()?.trim() ?? name;
}

/** The upload and the names last left out: send files, keeping only those ReconPilot reads. */
export function useDropZone(fund: string, asOf: string, expected: ExpectedFile[] | null) {
  const upload = useUploadFiles(fund, asOf);
  const [skipped, setSkipped] = useState<string[]>([]);
  const known = expected ? new Set(expected.map((f) => f.filename.toLowerCase())) : null;

  function send(list: FileList | null) {
    const files = list ? Array.from(list) : [];
    if (!files.length) return;
    const wanted = known ? files.filter((f) => known.has(baseName(f.name).toLowerCase())) : files;
    setSkipped(files.filter((f) => !wanted.includes(f)).map((f) => baseName(f.name)));
    if (wanted.length) upload.mutate(wanted);
    else upload.reset();
  }

  return { upload, skipped, send };
}

export function DropZone({
  state,
  maxFileBytes,
}: {
  state: ReturnType<typeof useDropZone>;
  maxFileBytes: number | null;
}) {
  const { upload, skipped, send } = state;
  const [over, setOver] = useState(false);
  const inputId = useId();
  const hintId = useId();

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setOver(false);
    send(event.dataTransfer.files);
  }

  return (
    <div
      className={over ? "up-drop over" : "up-drop"}
      onDragOver={(event) => {
        event.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
    >
      <span className="tile-box up-drop-icon" aria-hidden="true">
        <Icon name="upload" />
      </span>
      <label htmlFor={inputId} className="up-drop-label">
        Choose the day&rsquo;s files
      </label>
      <p id={hintId} className="muted">
        Or drop them here, several at once. Send the whole set or only the files that changed; each upload replaces
        the files of the same name and the day is validated again.
        {maxFileBytes ? ` Up to ${sizeText(maxFileBytes)} a file.` : ""}
      </p>
      <input
        id={inputId}
        type="file"
        multiple
        accept=".csv,text/csv"
        aria-describedby={hintId}
        disabled={upload.isPending}
        onChange={(event) => {
          send(event.target.files);
          event.target.value = ""; // choosing the same files again uploads them again
        }}
      />
      {skipped.length > 0 && (
        <div className="state-line up-skipped" role="status">
          <Icon name="warn" />
          <span>
            Not sent: {skipped.join(", ")}. {skipped.length === 1 ? "It is not a file" : "They are not files"}{" "}
            ReconPilot reads for a day.
          </span>
        </div>
      )}
      {upload.isPending && (
        <p className="state-line" role="status">
          <span className="spinner" aria-hidden="true" />
          Uploading and validating…
        </p>
      )}
      {upload.isError && (
        <div className="state-line error" role="alert">
          <Icon name="warn" />
          <span>{upload.error instanceof ApiError ? upload.error.message : "The upload failed. Try again."}</span>
        </div>
      )}
    </div>
  );
}
