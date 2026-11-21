"""Deterministic preparation of document images for model-facing analysis.

Prepared bytes are written below ``Documents/.prepared`` and are referenced
everywhere else by content-free handles.  This module never reads a prepared
cache entry: the model gateway is the sole reader and verifies its SHA-256
immediately before a provider call.
"""

from __future__ import annotations

from functools import lru_cache
from io import BytesIO
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Iterable

from PIL import Image, ImageOps, UnidentifiedImageError

from .workspaces import Workspace, WorkspaceError, write_json_atomic

PREPARATION_IMPLEMENTATION = "audit-workbench-document-media-v1"
PREPARATION_POLICY = {
    "implementation": PREPARATION_IMPLEMENTATION,
    "render_pdf_dpi": 160,
    "overview_long_edge": 2_048,
    "overview_max_pixels": 4_000_000,
    "tile_long_edge": 2_048,
    "tile_overlap": 64,
    "max_parts": 4,
    "max_pixels": 12_000_000,
    "max_bytes": 12 * 1024 * 1024,
}
MAX_VISUAL_PAGES = 20


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


PREPARATION_POLICY_HASH = _canonical_hash(PREPARATION_POLICY)


class MediaPreparationError(WorkspaceError):
    """A visual source could not be normalized within the declared policy."""

    def __init__(self, message: str, *, code: str = "visual_preparation_failed"):
        self.code = code
        super().__init__(f"{code}: {message}")


def planned_prepared_set_hash(
    source_sha1: str, page: int, *, frame: int | None = None
) -> str:
    """Identity available during read-only unit expansion."""

    return _canonical_hash(
        {
            "source_sha1": str(source_sha1),
            "page": int(page),
            "frame": int(frame or page),
            "policy_hash": PREPARATION_POLICY_HASH,
        }
    )


def _document(workspace: Workspace, document_id: str) -> dict:
    document = next(
        (
            item
            for item in workspace.documents
            if str(item.get("id")) == str(document_id)
        ),
        None,
    )
    if document is None:
        raise MediaPreparationError(f"Document '{document_id}' was not found.")
    return document


def _source_image(
    workspace: Workspace, document_id: str, page: int
) -> tuple[Image.Image, int]:
    from . import documents

    document = _document(workspace, document_id)
    path = documents.document_path(workspace, document)
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            try:
                import pypdfium2 as pdfium
            except ImportError as error:
                raise MediaPreparationError(
                    "PDF visual rendering requires pypdfium2."
                ) from error
            pdf = pdfium.PdfDocument(str(path))
            try:
                if not 1 <= int(page) <= len(pdf):
                    raise MediaPreparationError(
                        f"PDF page {page} does not exist."
                    )
                pdf_page = pdf[int(page) - 1]
                try:
                    width_points, height_points = pdf_page.get_size()
                    requested_scale = PREPARATION_POLICY["render_pdf_dpi"] / 72
                    safe_scale = min(
                        requested_scale,
                        8_192 / max(1.0, width_points, height_points),
                    )
                    rendered = pdf_page.render(scale=safe_scale)
                    try:
                        image = rendered.to_pil().copy()
                    finally:
                        rendered.close()
                finally:
                    pdf_page.close()
            finally:
                pdf.close()
            return image, int(page)

        with Image.open(path) as source:
            frame_count = int(getattr(source, "n_frames", 1) or 1)
            if not 1 <= int(page) <= frame_count:
                raise MediaPreparationError(
                    f"Image frame {page} does not exist."
                )
            source.seek(int(page) - 1)
            source.load()
            return source.copy(), int(page)
    except MediaPreparationError:
        raise
    except (
        OSError,
        UnidentifiedImageError,
        ValueError,
        Image.DecompressionBombError,
    ) as error:
        raise MediaPreparationError(
            "The source is not a supported or valid image."
        ) from error


def image_frame_count(path: Path) -> int:
    """Return a safely bounded deterministic frame count for an image source."""

    try:
        with Image.open(path) as image:
            return max(1, int(getattr(image, "n_frames", 1) or 1))
    except (
        OSError,
        UnidentifiedImageError,
        ValueError,
        Image.DecompressionBombError,
    ) as error:
        raise MediaPreparationError(
            "The source is not a supported or valid image."
        ) from error


def _normalized(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    if image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, "white")
        background.alpha_composite(rgba)
        return background.convert("RGB")
    return image.convert("RGB")


def _bounded(image: Image.Image, *, long_edge: int, max_pixels: int) -> Image.Image:
    width, height = image.size
    scale = min(
        1.0,
        long_edge / max(width, height),
        math.sqrt(max_pixels / max(1, width * height)),
    )
    if scale >= 1:
        return image.copy()
    size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def _tile_boxes(width: int, height: int) -> list[tuple[int, int, int, int]]:
    long_edge = int(PREPARATION_POLICY["tile_long_edge"])
    overlap = int(PREPARATION_POLICY["tile_overlap"])
    stride = max(1, long_edge - overlap)
    xs = [0] if width <= long_edge else list(range(0, width, stride))
    ys = [0] if height <= long_edge else list(range(0, height, stride))
    if xs and xs[-1] + long_edge < width:
        xs.append(max(0, width - long_edge))
    if ys and ys[-1] + long_edge < height:
        ys.append(max(0, height - long_edge))
    boxes = []
    for y in ys:
        for x in xs:
            box = (x, y, min(width, x + long_edge), min(height, y + long_edge))
            if box not in boxes:
                boxes.append(box)
    return boxes


def _variants(image: Image.Image) -> list[tuple[str, tuple[int, int, int, int], Image.Image]]:
    width, height = image.size
    overview = _bounded(
        image,
        long_edge=int(PREPARATION_POLICY["overview_long_edge"]),
        max_pixels=int(PREPARATION_POLICY["overview_max_pixels"]),
    )
    values = [("overview", (0, 0, width, height), overview)]
    dense = width * height > int(PREPARATION_POLICY["overview_max_pixels"])
    unusual = max(width / max(1, height), height / max(1, width)) >= 3.0
    if dense or unusual:
        for box in _tile_boxes(width, height):
            tile = _bounded(
                image.crop(box),
                long_edge=int(PREPARATION_POLICY["tile_long_edge"]),
                max_pixels=int(PREPARATION_POLICY["overview_max_pixels"]),
            )
            values.append(("detail", box, tile))
            if len(values) >= int(PREPARATION_POLICY["max_parts"]):
                break
    return values


def _png_bytes(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(
        output,
        format="PNG",
        optimize=False,
        compress_level=9,
        icc_profile=None,
        pnginfo=None,
    )
    return output.getvalue()


def _prepared_root(workspace: Workspace) -> Path:
    return workspace.root / "Documents" / ".prepared"


def _manifest_path(
    workspace: Workspace, source_sha1: str, page: int, frame: int
) -> Path:
    identity = planned_prepared_set_hash(source_sha1, page, frame=frame)
    return _prepared_root(workspace) / f"{identity.removeprefix('sha256:')}.json"


def _reusable_handles(
    workspace: Workspace,
    *,
    source_sha1: str,
    page: int,
    frame: int,
) -> list[dict] | None:
    """Load content-free preparation metadata without reading image bytes."""

    path = _manifest_path(workspace, source_sha1, page, frame)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        handles = payload["handles"]
        if (
            payload.get("source_sha1") != source_sha1
            or payload.get("policy_hash") != PREPARATION_POLICY_HASH
            or int(payload.get("page")) != page
            or int(payload.get("frame")) != frame
            or not isinstance(handles, list)
            or not handles
            or any(not isinstance(item, dict) for item in handles)
        ):
            raise ValueError("prepared-media manifest identity is invalid")
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise MediaPreparationError(
            "Prepared-media metadata is invalid."
        ) from error
    for handle in handles:
        cache_key = str(handle.get("cache_key") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", cache_key):
            raise MediaPreparationError(
                "Prepared-media metadata contains an invalid cache key."
            )
        if not (_prepared_root(workspace) / f"{cache_key}.png").is_file():
            raise MediaPreparationError(
                "Prepared media recorded for this source is missing."
            )
    return [dict(item) for item in handles]


def _set_hash(handles: Iterable[dict]) -> str:
    return _canonical_hash(
        [
            {
                "prepared_sha256": item["prepared_sha256"],
                "page": item["page"],
                "frame": item["frame"],
                "variant": item["variant"],
                "tile_order": item["tile_order"],
                "width": item["width"],
                "height": item["height"],
            }
            for item in handles
        ]
    )


def prepare_document_page(
    workspace: Workspace, document_id: str, page: int
) -> list[dict]:
    """Normalize one standalone image frame or rendered PDF page."""

    document = _document(workspace, document_id)
    source_sha1 = str(document.get("sha1") or "")
    if not source_sha1:
        raise MediaPreparationError("The source document has no content hash.")
    reusable = _reusable_handles(
        workspace,
        source_sha1=source_sha1,
        page=int(page),
        frame=int(page),
    )
    if reusable is not None:
        return reusable
    image, frame = _source_image(workspace, document_id, int(page))
    normalized = _normalized(image)
    handles: list[dict] = []
    total_pixels = total_bytes = 0
    pending: list[tuple[dict, bytes]] = []
    for order, (variant, bounds, part) in enumerate(_variants(normalized)):
        content = _png_bytes(part)
        width, height = part.size
        pixels = width * height
        if (
            total_pixels + pixels > int(PREPARATION_POLICY["max_pixels"])
            or total_bytes + len(content) > int(PREPARATION_POLICY["max_bytes"])
        ):
            continue
        prepared_sha = hashlib.sha256(content).hexdigest()
        cache_key = hashlib.sha256(
            json.dumps(
                {
                    "source_sha1": source_sha1,
                    "page": int(page),
                    "frame": frame,
                    "variant": variant,
                    "tile_order": order,
                    "bounds": list(bounds),
                    "prepared_sha256": prepared_sha,
                    "policy_hash": PREPARATION_POLICY_HASH,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        handle = {
            "cache_key": cache_key,
            "source_ref": (
                f"document:{document_id}:page:{int(page)}:"
                f"{variant}:{order}"
            ),
            "source_sha1": source_sha1,
            "prepared_sha256": f"sha256:{prepared_sha}",
            "page": int(page),
            "frame": frame,
            "variant": variant,
            "tile_order": order,
            "mime": "image/png",
            "width": width,
            "height": height,
            "prepared_byte_count": len(content),
            "pixel_count": pixels,
            "policy_hash": PREPARATION_POLICY_HASH,
            "prepared_set_hash": "",
        }
        pending.append((handle, content))
        total_pixels += pixels
        total_bytes += len(content)
    if not pending:
        raise MediaPreparationError(
            "The image could not fit within the prepared-media bounds."
        )
    prepared_set_hash = _set_hash(handle for handle, _content in pending)
    root = _prepared_root(workspace)
    root.mkdir(parents=True, exist_ok=True)
    for handle, content in pending:
        handle["prepared_set_hash"] = prepared_set_hash
        path = root / f"{handle['cache_key']}.png"
        if not path.exists():
            path.write_bytes(content)
        handles.append(handle)
    write_json_atomic(
        _manifest_path(workspace, source_sha1, int(page), frame),
        {
            "schema_version": 1,
            "source_sha1": source_sha1,
            "page": int(page),
            "frame": frame,
            "policy_hash": PREPARATION_POLICY_HASH,
            "prepared_set_hash": prepared_set_hash,
            "handles": handles,
        },
    )
    return handles


@lru_cache(maxsize=64)
def _render_pdf_page_cached(
    path_str: str, source_sha1: str, page: int, dpi: int
) -> bytes:
    """Render one PDF page to PNG bytes, cached by content hash and page."""
    del source_sha1
    try:
        import pypdfium2 as pdfium
    except ImportError as error:
        raise MediaPreparationError(
            "PDF visual rendering requires pypdfium2."
        ) from error
    pdf = pdfium.PdfDocument(path_str)
    try:
        if not 1 <= int(page) <= len(pdf):
            raise MediaPreparationError(f"PDF page {page} does not exist.")
        pdf_page = pdf[int(page) - 1]
        try:
            width_points, height_points = pdf_page.get_size()
            scale = min(
                max(72, int(dpi)) / 72.0,
                2_400 / max(1.0, width_points, height_points),
            )
            rendered = pdf_page.render(scale=scale)
            try:
                image = rendered.to_pil().copy()
            finally:
                rendered.close()
        finally:
            pdf_page.close()
    finally:
        pdf.close()
    return _png_bytes(image)


def render_page_png(
    workspace: Workspace, document_id: str, page: int, dpi: int = 180
) -> bytes:
    """Render one page of a PDF document as a crisp PNG for visual overlay."""
    from . import documents

    document = _document(workspace, document_id)
    path = documents.document_path(workspace, document)
    if path.suffix.lower() != ".pdf":
        raise MediaPreparationError("Page rendering is only supported for PDF files.")
    return _render_pdf_page_cached(
        str(path), str(document.get("sha1") or ""), int(page), int(dpi)
    )


def _merge_line_rects(
    rects: list[tuple[float, float, float, float]],
    bbox: tuple[float, float, float, float],
) -> list[dict[str, float]]:
    """Merge per-character PDF rects on the same line into normalized top-left boxes."""
    if not rects:
        return []
    x0, y0, x1, y1 = bbox
    width = max(1.0, x1 - x0)
    height = max(1.0, y1 - y0)

    # Group rectangles whose vertical spans overlap into one box per line.
    ordered = sorted(rects, key=lambda r: (-r[3], r[0]))
    lines: list[list[float]] = []
    for left, bottom, right, top in ordered:
        if right <= left or top <= bottom:
            continue
        placed = False
        for line in lines:
            overlap = min(line[3], top) - max(line[1], bottom)
            min_h = max(0.5, min(line[3] - line[1], top - bottom))
            if overlap >= min_h * 0.35:
                line[0] = min(line[0], left)
                line[1] = min(line[1], bottom)
                line[2] = max(line[2], right)
                line[3] = max(line[3], top)
                placed = True
                break
        if not placed:
            lines.append([left, bottom, right, top])

    pad_x = 0.0045
    pad_y = 0.003
    out: list[dict[str, float]] = []
    for left, bottom, right, top in lines:
        nx = max(0.0, ((left - x0) / width) - pad_x)
        ny = max(0.0, ((y1 - top) / height) - pad_y)
        nx2 = min(1.0, ((right - x0) / width) + pad_x)
        ny2 = min(1.0, ((y1 - bottom) / height) + pad_y)
        if nx2 > nx and ny2 > ny:
            out.append(
                {
                    "x": round(nx, 5),
                    "y": round(ny, 5),
                    "width": round(nx2 - nx, 5),
                    "height": round(ny2 - ny, 5),
                }
            )
    return out


def _search_page_boxes(
    textpage,
    bbox: tuple[float, float, float, float],
    page_no: int,
    query: str,
    claimed: set[tuple[int, int]],
) -> list[dict[str, float]]:
    text = re.sub(r"\s+", " ", str(query or "")).strip()
    if not text:
        return []
    searcher = textpage.search(text)
    first_hit: tuple[int, int] | None = None
    chosen: tuple[int, int] | None = None
    for _ in range(32):
        hit = searcher.get_next()
        if hit is None:
            break
        if first_hit is None:
            first_hit = hit
        if (page_no, hit[0]) not in claimed:
            chosen = hit
            break
    if chosen is None:
        chosen = first_hit
    if chosen is None:
        return []
    claimed.add((page_no, chosen[0]))
    rect_count = textpage.count_rects(chosen[0], chosen[1])
    rects = [textpage.get_rect(i) for i in range(rect_count)]
    return _merge_line_rects(rects, bbox)


def _visual_region_boxes(citation: dict | None) -> list[dict[str, float]]:
    if not isinstance(citation, dict):
        return []
    region = citation.get("region")
    if not isinstance(region, dict):
        return []
    try:
        x = float(region["x"])
        y = float(region["y"])
        w = float(region["width"])
        h = float(region["height"])
    except (KeyError, TypeError, ValueError):
        return []
    if w <= 0 or h <= 0:
        return []
    return [
        {
            "x": round(max(0.0, min(1.0, x)), 5),
            "y": round(max(0.0, min(1.0, y)), 5),
            "width": round(max(0.0, min(1.0 - max(0.0, x), w)), 5),
            "height": round(max(0.0, min(1.0 - max(0.0, y), h)), 5),
        }
    ]


def _display_field_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return ", ".join(_display_field_value(item) for item in value if item is not None)
    return str(value).strip()


def _parse_audit_notes(markdown: str) -> list[str]:
    raw = str(markdown or "").strip()
    if not raw:
        return []
    out: list[str] = []
    current = ""

    def _flush() -> None:
        nonlocal current
        cleaned = re.sub(r"\s+", " ", current.replace("**", "")).strip()
        if cleaned:
            out.append(cleaned)
        current = ""

    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line or re.match(r"^#{1,6}\s+", line):
            _flush()
            continue
        if re.match(r"^(?:[-*•]|\d+\.)\s+", line):
            _flush()
            current = re.sub(r"^(?:[-*•]|\d+\.)\s+", "", line)
        elif current:
            current = f"{current} {line}"
        else:
            current = line
    _flush()
    return out


_NOTE_KEYWORDS = (
    "workflow approval",
    "authorisations",
    "authorization",
    "authorisation",
    "approval",
    "received and inspected",
    "vendor representative",
    "controlled form",
    "payment terms",
    "due date",
    "signature",
)


def _note_queries(note: str, located_items: list[dict]) -> list[str]:
    queries: list[str] = []
    seen: set[str] = set()

    def _add(text: str) -> None:
        cleaned = re.sub(r"\s+", " ", text or "").strip()
        if len(cleaned) < 3:
            return
        key = cleaned.casefold()
        if key not in seen:
            seen.add(key)
            queries.append(cleaned)

    # 1. Double-quoted phrases
    for match in re.findall(r'["\u201c]([^"\u201d]{3,90})["\u201d]', note):
        _add(match)
    # 2. Single-quoted phrases (ignore apostrophes inside words like vendor's)
    for match in re.findall(
        r"(?<![A-Za-z0-9])['\u2018]([^'\u2019]{3,90})['\u2019]", note
    ):
        _add(match)
    # 3. Already-extracted field values explicitly mentioned in the note
    note_lower = note.casefold()
    matched_values = sorted(
        {
            str(item.get("value") or "").strip()
            for item in located_items
            if len(str(item.get("value") or "").strip()) >= 3
            and str(item.get("value") or "").strip().casefold() in note_lower
        },
        key=len,
        reverse=True,
    )
    for val in matched_values:
        _add(val)
    # 4. Reference/date/currency tokens
    for match in re.findall(
        r"\b(?:[A-Z]{2,6}[-]?\d{4,}[-A-Z0-9]*|\d{2}\s+[A-Z][a-z]{2}\s+20\d{2})\b",
        note,
    ):
        _add(match)
    # 5. Domain section keywords if mentioned in the note
    for kw in _NOTE_KEYWORDS:
        if kw in note_lower:
            _add(kw)
    return queries


def _locate_audit_notes(
    effective: dict,
    located_items: list[dict],
    citation_by_id: dict[str, dict],
    page_count: int,
    page_ctx,
) -> list[dict]:
    notes_text = _parse_audit_notes(str(effective.get("audit_notes_markdown") or ""))
    if not notes_text:
        return []

    by_citation = {
        str(item["citation_id"]): item
        for item in located_items
        if item.get("citation_id") and item.get("boxes")
    }
    by_value = {
        str(item["value"]).strip().casefold(): item
        for item in located_items
        if item.get("value") and item.get("boxes")
    }
    placed_pins: list[tuple[int, float, float]] = []
    unanchored_count = 0
    note_claimed: set[tuple[int, int]] = set()
    markers: list[dict] = []

    def _decollide(page_no: int, px: float, py: float) -> tuple[float, float]:
        x, y = px, py
        for _ in range(12):
            clashes = any(
                p == page_no and abs(ox - x) < 0.042 and abs(oy - y) < 0.036
                for p, ox, oy in placed_pins
            )
            if not clashes:
                break
            if x + 0.045 <= 0.96:
                x += 0.045
            else:
                y = min(0.95, y + 0.04)
        placed_pins.append((page_no, x, y))
        return round(x, 5), round(y, 5)

    for number, text in enumerate(notes_text, start=1):
        anchor_page = 1
        anchor_box: dict[str, float] | None = None

        # Prefer explicit [cN] citations inside the note
        for cite_id in re.findall(r"\[(c\d+)\]", text):
            existing = by_citation.get(cite_id)
            if existing:
                anchor_page = int(existing["page"])
                anchor_box = existing["boxes"][0]
                break
            cite = citation_by_id.get(cite_id)
            if cite:
                region = _visual_region_boxes(cite)
                if region:
                    anchor_page = int(cite.get("page") or 1)
                    anchor_box = region[0]
                    break

        if anchor_box is None:
            for query in _note_queries(text, located_items):
                existing = by_value.get(query.casefold())
                if existing:
                    anchor_page = int(existing["page"])
                    anchor_box = existing["boxes"][0]
                    break
                for page_no in range(1, min(page_count, 25) + 1):
                    ctx = page_ctx(page_no)
                    if ctx is None:
                        continue
                    _pdf_page, tp, bbox = ctx
                    boxes = _search_page_boxes(tp, bbox, page_no, query, note_claimed)
                    if boxes:
                        anchor_page = page_no
                        anchor_box = boxes[0]
                        break
                if anchor_box is not None:
                    break

        if anchor_box is not None:
            raw_x = min(0.955, anchor_box["x"] + anchor_box["width"] + 0.014)
            raw_y = max(0.03, min(0.95, anchor_box["y"] + (anchor_box["height"] / 2.0)))
            x, y = _decollide(anchor_page, raw_x, raw_y)
            markers.append(
                {
                    "key": f"note:{number}",
                    "number": number,
                    "text": text,
                    "page": anchor_page,
                    "x": x,
                    "y": y,
                    "anchored": True,
                    "box": anchor_box,
                }
            )
        else:
            unanchored_count += 1
            raw_x = 0.925
            raw_y = max(0.12, 0.89 - (unanchored_count - 1) * 0.055)
            x, y = _decollide(1, raw_x, raw_y)
            markers.append(
                {
                    "key": f"note:{number}",
                    "number": number,
                    "text": text,
                    "page": 1,
                    "x": x,
                    "y": y,
                    "anchored": False,
                    "box": None,
                }
            )

    return markers


def locate_analysis_highlights(workspace: Workspace, document_id: str) -> dict:
    """Locate normalized PDF bounding boxes for every extracted field or citation."""
    from . import document_analysis, documents

    document = _document(workspace, document_id)
    path = documents.document_path(workspace, document)
    if path.suffix.lower() != ".pdf":
        return {"document_id": document_id, "page_count": 0, "items": [], "notes": []}

    detail = document_analysis.load_analysis(workspace, document_id)
    effective = (detail or {}).get("effective")
    if not isinstance(effective, dict):
        return {"document_id": document_id, "page_count": 0, "items": [], "notes": []}

    try:
        import pypdfium2 as pdfium
    except ImportError:
        return {"document_id": document_id, "page_count": 0, "items": [], "notes": []}

    citations = effective.get("citations") or []
    citation_by_id = {
        str(c.get("id")): c for c in citations if isinstance(c, dict) and c.get("id")
    }
    records = effective.get("records") or []

    pdf = pdfium.PdfDocument(str(path))
    page_cache: dict[int, tuple[object, object, tuple[float, float, float, float]]] = {}
    claimed: set[tuple[int, int]] = set()
    items: list[dict] = []
    try:
        page_count = len(pdf)

        def _page_ctx(page_no: int):
            if page_no < 1 or page_no > page_count:
                return None
            if page_no not in page_cache:
                pdf_page = pdf[page_no - 1]
                textpage = pdf_page.get_textpage()
                page_cache[page_no] = (pdf_page, textpage, pdf_page.get_bbox())
            return page_cache[page_no]

        def _locate(
            page_hint: int | None, queries: list[str], citation: dict | None
        ) -> tuple[int, list[dict[str, float]]]:
            region_boxes = _visual_region_boxes(citation)
            if region_boxes:
                return int(page_hint or 1), region_boxes
            candidate_pages = (
                [page_hint]
                if page_hint and 1 <= page_hint <= page_count
                else list(range(1, min(page_count, 25) + 1))
            )
            for q in queries:
                for page_no in candidate_pages:
                    ctx = _page_ctx(page_no)
                    if ctx is None:
                        continue
                    _pdf_page, tp, bbox = ctx
                    boxes = _search_page_boxes(tp, bbox, page_no, q, claimed)
                    if boxes:
                        return page_no, boxes
            return int(page_hint or 1), []

        if records:
            for rec_idx, record in enumerate(records):
                if not isinstance(record, dict):
                    continue
                listed = record.get("fields")
                entries: list[tuple[str, str, str | None]] = []
                if isinstance(listed, list):
                    for entry in listed:
                        if not isinstance(entry, dict):
                            continue
                        entries.append(
                            (
                                str(entry.get("name") or ""),
                                _display_field_value(entry.get("value")),
                                str(entry.get("citation") or "") or None,
                            )
                        )
                else:
                    for key, value in record.items():
                        if isinstance(value, dict):
                            for inner_k, inner_v in value.items():
                                entries.append(
                                    (f"{key}_{inner_k}", _display_field_value(inner_v), None)
                                )
                        else:
                            entries.append((str(key), _display_field_value(value), None))

                seen_names: dict[str, int] = {}
                for name, value, cite_id in entries:
                    occ = seen_names.get(name, 0)
                    seen_names[name] = occ + 1
                    field_key = f"{rec_idx}:{name}:{occ}"
                    cite = citation_by_id.get(cite_id or "")
                    page_hint = int(cite.get("page")) if cite and cite.get("page") else None
                    excerpt = str((cite or {}).get("excerpt") or "").strip()
                    queries: list[str] = []
                    # Short tokens like "PKR" or "25" are ambiguous on their own;
                    # prefer the longer citation excerpt when available.
                    if len(value) <= 3 and len(excerpt) > len(value):
                        queries.extend([excerpt, value])
                    else:
                        queries.extend([value, excerpt])
                    queries = [q for q in queries if q]
                    page_no, boxes = _locate(page_hint, queries, cite)
                    if boxes:
                        items.append(
                            {
                                "key": field_key,
                                "field_name": name,
                                "value": value,
                                "citation_id": cite_id,
                                "page": page_no,
                                "boxes": boxes,
                            }
                        )
        else:
            for cite in citations:
                if not isinstance(cite, dict):
                    continue
                cite_id = str(cite.get("id") or "")
                excerpt = str(cite.get("excerpt") or "").strip()
                page_hint = int(cite.get("page") or 1)
                page_no, boxes = _locate(page_hint, [excerpt] if excerpt else [], cite)
                if boxes:
                    items.append(
                        {
                            "key": f"cite:{cite_id}",
                            "field_name": cite_id,
                            "value": excerpt or str(cite.get("description") or ""),
                            "citation_id": cite_id,
                            "page": page_no,
                            "boxes": boxes,
                        }
                    )
        notes = _locate_audit_notes(
            effective, items, citation_by_id, page_count, _page_ctx
        )
        return {
            "document_id": document_id,
            "page_count": page_count,
            "items": items,
            "notes": notes,
        }
    finally:
        for pdf_page, textpage, _bbox in page_cache.values():
            try:
                textpage.close()
            except Exception:
                pass
            try:
                pdf_page.close()
            except Exception:
                pass
        pdf.close()


__all__ = [
    "MAX_VISUAL_PAGES",
    "MediaPreparationError",
    "PREPARATION_IMPLEMENTATION",
    "PREPARATION_POLICY",
    "PREPARATION_POLICY_HASH",
    "image_frame_count",
    "locate_analysis_highlights",
    "planned_prepared_set_hash",
    "prepare_document_page",
    "render_page_png",
]
