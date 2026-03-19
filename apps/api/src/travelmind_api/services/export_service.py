from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, urljoin

from travelmind_api.agents.base import ExportDraft
from travelmind_api.core.config import Settings


EXPORT_FILES_ROUTE = "/exports/files"


def _escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _build_pdf(lines: list[str]) -> bytes:
    # Keep the PDF writer deliberately tiny and deterministic for MVP exports
    # and tests. A richer renderer can replace this without changing the API.
    trimmed = lines[:30]
    commands = ["BT", "/F1 12 Tf", "50 770 Td"]
    first = True
    for line in trimmed:
        if not first:
            commands.append("0 -18 Td")
        commands.append(f"({_escape_pdf_text(line)}) Tj")
        first = False
    commands.append("ET")
    stream = "\n".join(commands).encode("utf-8")

    objects = [
        b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n",
        b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n",
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>endobj\n",
        b"4 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n",
        f"5 0 obj<< /Length {len(stream)} >>stream\n".encode("utf-8") + stream + b"\nendstream\nendobj\n",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(pdf))
        pdf.extend(obj)

    xref_position = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("utf-8"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("utf-8"))
    pdf.extend(
        f"trailer<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_position}\n%%EOF".encode("utf-8")
    )
    return bytes(pdf)


def _build_file_url(settings: Settings, filename: str) -> str:
    return urljoin(f"{settings.public_api_url.rstrip('/')}/", f"{EXPORT_FILES_ROUTE}/{quote(filename)}")


def write_pdf_export(job_id: str, draft: ExportDraft, settings: Settings) -> dict[str, str | int]:
    filename = f"{job_id}.pdf"
    export_root = settings.resolved_export_root.resolve()
    export_root.mkdir(parents=True, exist_ok=True)
    path = (export_root / filename).resolve()
    payload = _build_pdf([line for line in [draft.title, draft.subtitle, *draft.sections] if line])
    Path(path).write_bytes(payload)
    return {
        "file_name": filename,
        "file_path": str(path),
        "file_url": _build_file_url(settings, filename),
        "content_type": "application/pdf",
        "size_bytes": len(payload),
    }
