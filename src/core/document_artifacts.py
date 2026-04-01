from __future__ import annotations

import io
import logging
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

PENDING_DOCUMENT_ARTIFACTS_KEY = "pending_document_artifacts"
DOCUMENT_UPLOAD_ROOT = (Path(tempfile.gettempdir()) / "ikaros" / "documents").resolve()
MAX_DOCUMENT_FILE_SIZE_BYTES = 10 * 1024 * 1024

_DOC_TYPE_BY_MIME = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/msword": "doc",
    "text/plain": "txt",
}
_DOC_TYPE_BY_SUFFIX = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "doc",
    ".txt": "txt",
}
_DOC_SUFFIX_BY_TYPE = {
    "pdf": ".pdf",
    "docx": ".docx",
    "doc": ".doc",
    "txt": ".txt",
}
_TEXT_ENCODINGS = (
    "utf-8-sig",
    "utf-8",
    "utf-16",
    "gb18030",
    "gbk",
)


@dataclass(slots=True)
class DocumentArtifact:
    file_name: str
    mime_type: str
    doc_type: str
    original_path: str
    text_path: str

    def to_payload(self) -> dict[str, str]:
        return {
            "file_name": str(self.file_name or "").strip(),
            "mime_type": str(self.mime_type or "").strip(),
            "doc_type": str(self.doc_type or "").strip(),
            "original_path": str(self.original_path or "").strip(),
            "text_path": str(self.text_path or "").strip(),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> DocumentArtifact | None:
        if not isinstance(payload, dict):
            return None
        file_name = str(payload.get("file_name") or "").strip()
        mime_type = str(payload.get("mime_type") or "").strip()
        doc_type = str(payload.get("doc_type") or "").strip()
        original_path = str(payload.get("original_path") or "").strip()
        text_path = str(payload.get("text_path") or "").strip()
        if not text_path:
            return None
        if not original_path:
            original_path = text_path
        if not file_name:
            file_name = Path(text_path).name
        return cls(
            file_name=file_name or "document.txt",
            mime_type=mime_type or "text/plain",
            doc_type=doc_type or "txt",
            original_path=original_path,
            text_path=text_path,
        )


def describe_supported_document_formats() -> str:
    return "PDF、DOCX、TXT"


def resolve_document_type(mime_type: str | None, file_name: str | None) -> str | None:
    normalized_mime = _normalize_mime_type(mime_type)
    if normalized_mime in _DOC_TYPE_BY_MIME:
        return _DOC_TYPE_BY_MIME[normalized_mime]

    suffix = Path(str(file_name or "").strip()).suffix.lower()
    if suffix:
        return _DOC_TYPE_BY_SUFFIX.get(suffix)
    return None


def persist_document_artifact(
    *,
    file_bytes: bytes,
    file_name: str | None,
    mime_type: str | None,
    storage_root: str | Path | None = None,
) -> DocumentArtifact:
    doc_type = resolve_document_type(mime_type, file_name)
    if not doc_type:
        raise ValueError("unsupported_document_type")

    safe_name = str(file_name or "").strip() or f"document{_DOC_SUFFIX_BY_TYPE[doc_type]}"
    root = Path(storage_root or DOCUMENT_UPLOAD_ROOT).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    suffix = Path(safe_name).suffix.lower() or _DOC_SUFFIX_BY_TYPE[doc_type]
    stem = _sanitize_file_stem(Path(safe_name).stem)
    token = uuid4().hex[:12]

    if doc_type == "txt":
        text = _decode_text_bytes(file_bytes)
        if not text.strip():
            raise ValueError("empty_document_text")
        text_path = (root / f"{stem}_{token}.txt").resolve()
        text_path.write_text(text, encoding="utf-8")
        return DocumentArtifact(
            file_name=safe_name,
            mime_type=_normalize_mime_type(mime_type) or "text/plain",
            doc_type=doc_type,
            original_path=str(text_path),
            text_path=str(text_path),
        )

    original_path = (root / f"{stem}_{token}{suffix}").resolve()
    original_path.write_bytes(bytes(file_bytes or b""))

    if doc_type == "pdf":
        text = extract_text_from_pdf(file_bytes)
    else:
        text = extract_text_from_docx(file_bytes)

    if not text.strip():
        raise ValueError("empty_document_text")

    text_path = (root / f"{stem}_{token}_text.txt").resolve()
    text_path.write_text(text, encoding="utf-8")
    return DocumentArtifact(
        file_name=safe_name,
        mime_type=_normalize_mime_type(mime_type) or "application/octet-stream",
        doc_type=doc_type,
        original_path=str(original_path),
        text_path=str(text_path),
    )


def list_pending_document_artifacts(user_data: dict[str, Any] | None) -> list[DocumentArtifact]:
    if not isinstance(user_data, dict):
        return []
    raw_items = user_data.get(PENDING_DOCUMENT_ARTIFACTS_KEY)
    if not isinstance(raw_items, list):
        return []

    artifacts: list[DocumentArtifact] = []
    seen_paths: set[str] = set()
    for item in raw_items:
        artifact = DocumentArtifact.from_payload(item)
        if artifact is None:
            continue
        path_key = str(artifact.text_path or "").strip()
        if not path_key or path_key in seen_paths:
            continue
        seen_paths.add(path_key)
        artifacts.append(artifact)
    return artifacts


def append_pending_document_artifact(
    user_data: dict[str, Any] | None,
    artifact: DocumentArtifact,
) -> list[DocumentArtifact]:
    if not isinstance(user_data, dict):
        return []
    pending = list_pending_document_artifacts(user_data)
    pending = [item for item in pending if item.text_path != artifact.text_path]
    pending.append(artifact)
    user_data[PENDING_DOCUMENT_ARTIFACTS_KEY] = [item.to_payload() for item in pending]
    return pending


def pop_pending_document_artifacts(user_data: dict[str, Any] | None) -> list[DocumentArtifact]:
    pending = list_pending_document_artifacts(user_data)
    if isinstance(user_data, dict):
        user_data.pop(PENDING_DOCUMENT_ARTIFACTS_KEY, None)
    return pending


def build_document_forward_text(
    artifacts: list[DocumentArtifact],
    user_request: str = "",
) -> str:
    normalized = [
        item
        for item in list(artifacts or [])
        if isinstance(item, DocumentArtifact) and str(item.text_path or "").strip()
    ]
    request = str(user_request or "").strip()
    if not normalized:
        return request

    is_single = len(normalized) == 1
    lines = [
        (
            "用户发送了一个文档，请先读取对应的文本工件，再根据用户要求处理。"
            if is_single
            else "用户发送了多个文档，请先读取对应的文本工件，再根据用户要求处理。"
        )
    ]

    for index, artifact in enumerate(normalized, start=1):
        prefix = "" if is_single else f"文档{index} "
        lines.append(
            f"- {prefix}文件名：{str(artifact.file_name or '').strip() or 'document'}"
        )
        lines.append(f"- {prefix}文本工件：{artifact.text_path}")
        if artifact.original_path and artifact.original_path != artifact.text_path:
            lines.append(f"- {prefix}原始文件：{artifact.original_path}")

    if request:
        lines.append("")
        lines.append(f"用户要求：{request}")
    return "\n".join(lines).strip()


def extract_text_from_pdf(file_bytes: bytes) -> str:
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(stream=file_bytes, filetype="pdf")
        try:
            parts = [page.get_text() for page in doc]
        finally:
            doc.close()
        return "\n".join(part for part in parts if part).strip()
    except Exception as exc:
        logger.error("Failed to extract text from PDF: %s", exc)
        return ""


def extract_text_from_docx(file_bytes: bytes) -> str:
    try:
        from docx import Document

        doc = Document(io.BytesIO(file_bytes))
        return "\n".join(para.text for para in doc.paragraphs if para.text).strip()
    except Exception as exc:
        logger.error("Failed to extract text from DOCX: %s", exc)
        return ""


def _decode_text_bytes(file_bytes: bytes) -> str:
    payload = bytes(file_bytes or b"")
    if not payload:
        return ""

    for encoding in _TEXT_ENCODINGS:
        try:
            return payload.decode(encoding)
        except Exception:
            continue
    return payload.decode("utf-8", errors="replace")


def _normalize_mime_type(mime_type: str | None) -> str:
    return str(mime_type or "").split(";", 1)[0].strip().lower()


def _sanitize_file_stem(stem: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", str(stem or "").strip())
    normalized = normalized.strip("._")
    return normalized or "document"
