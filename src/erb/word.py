"""Finalize a report with Microsoft Word (macOS): refresh TOC/page fields, save, export PDF.

Uses AppleScript. The first run may make Word ask for file-access permission to
this folder; approve it once. If Word isn't available the .docx still works: it
asks to update fields when opened.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = '''
set docPath to POSIX file "{docx}"
set pdfPath to "{pdf}"
tell application "Microsoft Word"
    -- close any copy already open (a stale copy would be saved over the fresh build)
    repeat with dd in (get documents)
        if (full name of dd) ends with "{name}" then close dd saving no
    end repeat
    open docPath
    set d to active document
    repeat with i from 1 to (count of tables of contents of d)
        update (table of contents i of d)
    end repeat
    save d
    save as d file name pdfPath file format format PDF
    close d saving no
end tell
'''


def finalize(docx: Path, log=print) -> Path | None:
    docx = Path(docx).resolve()
    pdf = docx.with_suffix(".pdf")
    script = SCRIPT.format(docx=str(docx), pdf=str(pdf), name=docx.name)
    try:
        subprocess.run(["osascript", "-e", script], check=True, capture_output=True, text=True, timeout=180)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        msg = getattr(exc, "stderr", "") or str(exc)
        log(f"NOTE: Word finalization skipped ({msg.strip()[:200]}). The .docx asks to update fields on open.")
        return None
    (docx.parent / ".last_build").touch()  # Word's save is ours, not an edit
    log(f"Word refreshed the TOC and exported {pdf.name}")
    return pdf
