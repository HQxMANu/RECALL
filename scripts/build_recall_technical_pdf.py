from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, StyleSheet1, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output" / "pdf"
OUTPUT_PATH = OUTPUT_DIR / "Recall-Technical-Deep-Dive.pdf"


@dataclass(frozen=True)
class Section:
    title: str
    body: list[str]


def build_styles() -> StyleSheet1:
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="RecallTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=30,
            textColor=colors.HexColor("#0B2230"),
            alignment=TA_LEFT,
            spaceAfter=10,
        )
    )
    styles.add(
        ParagraphStyle(
            name="RecallSubtitle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=11,
            leading=16,
            textColor=colors.HexColor("#3C5566"),
            spaceAfter=10,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SectionHeading",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=21,
            textColor=colors.HexColor("#10354A"),
            spaceBefore=14,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SubHeading",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=16,
            textColor=colors.HexColor("#1F516D"),
            spaceBefore=10,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Body",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=14,
            textColor=colors.HexColor("#1C2C36"),
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="RecallBullet",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13.5,
            leftIndent=16,
            bulletIndent=6,
            textColor=colors.HexColor("#1C2C36"),
            spaceAfter=3,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Small",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#4B6271"),
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CalloutTitle",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=colors.white,
            alignment=TA_LEFT,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CalloutBody",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=colors.white,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CenteredSmall",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#4B6271"),
            alignment=TA_CENTER,
        )
    )
    return styles


def page_background(canvas, doc) -> None:
    canvas.saveState()
    width, height = letter
    canvas.setFillColor(colors.HexColor("#F4F8FB"))
    canvas.rect(0, 0, width, height, stroke=0, fill=1)
    canvas.setFillColor(colors.HexColor("#0E2A3A"))
    canvas.rect(0, height - 32, width, 32, stroke=0, fill=1)
    canvas.setFillColor(colors.HexColor("#5DE2C2"))
    canvas.rect(doc.leftMargin, height - 20, 120, 3, stroke=0, fill=1)
    canvas.setFillColor(colors.HexColor("#48606F"))
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(width - doc.rightMargin, 18, f"Recall Technical Deep Dive  •  Page {doc.page}")
    canvas.restoreState()


def escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def bullet(text: str, styles: StyleSheet1) -> Paragraph:
    return Paragraph(escape(text), styles["RecallBullet"], bulletText="•")


def body(text: str, styles: StyleSheet1) -> Paragraph:
    return Paragraph(escape(text), styles["Body"])


def code_inline(text: str) -> str:
    return f"<font name='Courier'>{escape(text)}</font>"


def callout(title: str, text: str, styles: StyleSheet1, color: str = "#10354A") -> Table:
    content = [
        [Paragraph(escape(title), styles["CalloutTitle"])],
        [Paragraph(escape(text), styles["CalloutBody"])],
    ]
    table = Table(content, colWidths=[6.6 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(color)),
                ("BOX", (0, 0), (-1, -1), 0, colors.HexColor(color)),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    return table


def labeled_box(title: str, lines: list[str], styles: StyleSheet1, width: float = 2.05 * inch) -> Table:
    rows = [[Paragraph(escape(title), styles["SubHeading"])]]
    rows.extend([[Paragraph(escape(line), styles["Small"])] for line in lines])
    table = Table(rows, colWidths=[width])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#CDE0EB")),
                ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#D9E8F0")),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def system_overview_table(styles: StyleSheet1) -> Table:
    table = Table(
        [
            [
                labeled_box(
                    "1. Tauri Shell",
                    [
                        "Windows desktop host",
                        "React + TypeScript UI",
                        "Tauri command bridge",
                        "Local shell state and file actions",
                    ],
                    styles,
                ),
                labeled_box(
                    "2. Rust Host",
                    [
                        "Boots app state",
                        "Launches Python worker",
                        "Owns folder watchers",
                        "Emits health and indexing events",
                    ],
                    styles,
                ),
                labeled_box(
                    "3. Python Worker",
                    [
                        "SQLite system of record",
                        "Indexing and chunking",
                        "Embedding and FAISS search",
                        "Lazy OCR and transcription",
                    ],
                    styles,
                ),
            ]
        ],
        colWidths=[2.1 * inch, 2.1 * inch, 2.1 * inch],
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return table


def startup_flow_table(styles: StyleSheet1) -> Table:
    rows = [
        ["Phase", "What happens", "Why it matters"],
        [
            "Shell ready",
            "Tauri creates the window, React boots, Rust serves local folder and indexing status immediately.",
            "The app opens quickly even before heavy AI services finish loading.",
        ],
        [
            "Core search warming",
            "Python worker opens SQLite, loads OpenCLIP and BGE, restores or rebuilds the two vector indices.",
            "Recall does not declare search ready until semantic retrieval is actually available.",
        ],
        [
            "Core search ready",
            "Image, document, and voice-note scopes become available once the preferred local embedding and vector engines are ready.",
            "This is the real usability gate for production search.",
        ],
        [
            "Indexing services deferred",
            "OCR and transcription stay unloaded until indexing work requires them.",
            "Startup avoids paying the OCR cost on every launch.",
        ],
    ]
    table = Table(rows, colWidths=[1.1 * inch, 3.2 * inch, 2.15 * inch], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#10354A")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("LEADING", (0, 0), (-1, -1), 11),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5FAFD")]),
                ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#CFE0EA")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def models_table(styles: StyleSheet1) -> Table:
    rows = [
        ["Capability", "Implementation", "Model/runtime details", "When loaded"],
        [
            "Image semantic search",
            "OpenCLIP image embedder",
            "ViT-B-32 using laion/CLIP-ViT-B-32-laion2B-s34B-b79K and open_clip_model.safetensors; 512-dim vectors",
            "Startup-critical",
        ],
        [
            "Document and audio semantic search",
            "Sentence-transformers style text embedder",
            "BAAI/bge-small-en-v1.5 via Hugging Face transformers; hidden size drives vector dimension",
            "Startup-critical",
        ],
        [
            "Vector retrieval",
            "FAISS with fallback",
            "IndexIDMap2 + IndexFlatIP for cosine-style inner-product retrieval; JSON metadata tracks revision and model match",
            "Startup-critical",
        ],
        [
            "Image OCR",
            "Lazy OCR engine",
            "PaddleOCR or Tesseract fallback; runtime inference fallback can demote Paddle to Tesseract",
            "Deferred until indexing",
        ],
        [
            "Voice-note transcription",
            "Lazy transcription engine",
            "faster-whisper small on CPU with int8 compute",
            "Deferred until indexing",
        ],
        [
            "Graceful degraded mode",
            "Hash fallback embedders and NumPy vector index",
            "Keeps local search functional if preferred ML dependencies are missing",
            "Only when preferred stack fails",
        ],
    ]
    table = Table(rows, colWidths=[1.2 * inch, 1.45 * inch, 2.75 * inch, 1.0 * inch], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F4760")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.2),
                ("LEADING", (0, 0), (-1, -1), 10.5),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5FAFD")]),
                ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#CFE0EA")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def schema_table(styles: StyleSheet1) -> Table:
    rows = [
        ["Table", "Purpose"],
        ["indexed_folders", "User-chosen roots that Recall actively watches and indexes."],
        ["indexed_images", "Image-specific metadata including OCR text and thumbnail path."],
        ["embeddings", "Image embedding blobs keyed by image id and model metadata."],
        ["indexed_assets", "Unified asset registry for images, documents, and voice notes."],
        ["asset_chunks", "Chunked text or transcript segments with page/time offsets."],
        ["text_embeddings", "Embeddings for document and transcript chunks."],
        ["indexing_jobs", "Job history, queue progress, trigger source, and errors."],
        ["app_settings", "Revision counters and small persistent flags used by runtime maintenance."],
        ["FTS virtual tables", "indexed_images_fts and asset_chunks_fts provide local lexical retrieval."],
    ]
    table = Table(rows, colWidths=[1.55 * inch, 4.9 * inch], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#10354A")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("LEADING", (0, 0), (-1, -1), 11),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5FAFD")]),
                ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#CFE0EA")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def ranking_table(styles: StyleSheet1) -> Table:
    rows = [
        ["Signal", "How Recall uses it"],
        ["FTS rank order", "Images search against indexed_images_fts; documents and voice notes search against asset_chunks_fts."],
        ["Semantic rank order", "Image queries use the image embedder; document and voice-note queries use the text embedder."],
        ["Weight profile", 'Quoted or dotted queries bias toward text (0.45 semantic / 0.5 text / 0.05 recency). General natural-language queries bias toward semantics (0.65 / 0.3 / 0.05).'],
        ["Recency boost", "A shallow freshness bonus decays across roughly one year of age."],
        ["Scope awareness", "Each scope returns results only when its own semantic stack is ready; browse mode is available without a textual query."],
    ]
    table = Table(rows, colWidths=[1.45 * inch, 5.0 * inch], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F4760")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("LEADING", (0, 0), (-1, -1), 11),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5FAFD")]),
                ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#CFE0EA")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def packaging_table(styles: StyleSheet1) -> Table:
    rows = [
        ["Mode", "Behavior"],
        [
            "Developer mode",
            "Runs Vite + cargo + the Rust shell against the workspace tree. It is best for iteration but exaggerates startup cost because build tools and hot reload are active.",
        ],
        [
            "Packaged mode",
            "Bundles the Python worker resources into the Tauri app so an installed build can launch without depending on the source tree layout.",
        ],
        [
            "Resource resolution",
            "Rust tries explicit development paths first, then Tauri resource paths, then extracted runtime fallbacks. This makes the same code work in both dev and release installs.",
        ],
        [
            "Operational tradeoff",
            "Production correctness improved at the cost of a larger installer because Python and ML dependencies are now shipped intentionally instead of accidentally omitted.",
        ],
    ]
    table = Table(rows, colWidths=[1.15 * inch, 5.3 * inch], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#10354A")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("LEADING", (0, 0), (-1, -1), 11),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5FAFD")]),
                ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#CFE0EA")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def build_story(styles: StyleSheet1) -> list:
    story: list = []
    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph("Recall Technical Deep Dive", styles["RecallTitle"]))
    story.append(
        Paragraph(
            "A technical briefing for engineers reviewing how Recall is structured, which local models it uses, "
            "how the desktop shell and Python worker cooperate, and how search, indexing, and packaging work in practice.",
            styles["RecallSubtitle"],
        )
    )
    story.append(Spacer(1, 0.08 * inch))
    story.append(
        callout(
            "Executive Summary",
            "Recall is a local-first multimodal desktop retrieval system. Tauri and React provide the desktop shell, "
            "Rust manages process orchestration and filesystem watching, and a Python worker owns indexing, storage, "
            "embeddings, and ranking. The current design intentionally treats semantic search as startup-critical "
            "while deferring OCR and transcription until indexing requires them.",
            styles,
            color="#0E3950",
        )
    )
    story.append(Spacer(1, 0.18 * inch))
    story.append(Paragraph("1. System Architecture", styles["SectionHeading"]))
    story.append(
        body(
            "At runtime, Recall is split into three cooperating layers. The desktop shell focuses on UX and OS integration, "
            "the Rust host manages lifecycle and inter-process messaging, and the Python worker handles all retrieval-heavy tasks.",
            styles,
        )
    )
    story.append(system_overview_table(styles))
    story.append(Spacer(1, 0.14 * inch))
    for text in [
        "The Tauri shell is responsible for the visible app and user-facing commands such as folder selection, file opening, and search requests.",
        "The Rust layer owns app state, worker startup, health snapshots, watcher synchronization, and event broadcasting back into the UI.",
        "The Python worker is the real retrieval engine: it persists metadata in SQLite, builds embeddings, manages vector indices, and processes indexing jobs.",
    ]:
        story.append(bullet(text, styles))

    story.append(Paragraph("2. Startup and Readiness Contract", styles["SectionHeading"]))
    story.append(
        body(
            "A central product decision in the current codebase is that the window should render quickly, but Recall should not claim search readiness until its semantic stack is usable. "
            "That means startup is staged around shell readiness and core-search readiness rather than around a single all-or-nothing boot gate.",
            styles,
        )
    )
    story.append(startup_flow_table(styles))
    story.append(Spacer(1, 0.12 * inch))
    story.append(
        callout(
            "Readiness Rule",
            "The UI can appear immediately, but the app should not advertise core search as ready until the embedding models and their corresponding vector indices are available. "
            "OCR and transcription are deliberately excluded from the critical startup path.",
            styles,
            color="#17556F",
        )
    )
    story.append(Spacer(1, 0.14 * inch))
    for text in [
        "The Rust host begins prewarming the worker after app state is created rather than blocking initial window paint on heavy ML services.",
        "Health snapshots distinguish shell, core search, and indexing readiness so the UI can expose what is truly available.",
        "The current server health logic is scope-based: image search relies on OpenCLIP + FAISS, while documents and voice notes rely on the text embedding stack.",
    ]:
        story.append(bullet(text, styles))

    story.append(Paragraph("3. Models and ML Runtime", styles["SectionHeading"]))
    story.append(
        body(
            "Recall now uses separate embedding paths for visual and textual retrieval. This makes the system more capable than the early image-only story, "
            "but it also means there are two startup-critical embedding paths instead of one.",
            styles,
        )
    )
    story.append(models_table(styles))
    story.append(Spacer(1, 0.12 * inch))
    for text in [
        "OpenCLIP handles image embeddings and query-to-image matching. Queries are embedded as text and compared against image vectors.",
        "BGE-small powers document and transcript retrieval, letting Recall semantically search extracted OCR text, PDF text, DOCX/TXT content, and audio transcripts.",
        "Hash and NumPy fallbacks keep the app from hard-failing when preferred ML dependencies are unavailable, but that degraded mode is materially weaker than the full design.",
    ]:
        story.append(bullet(text, styles))

    story.append(PageBreak())
    story.append(Paragraph("4. Storage and Searchable Data Model", styles["SectionHeading"]))
    story.append(
        body(
            "SQLite is the source of truth. FAISS speeds up nearest-neighbor retrieval, but the database remains authoritative for asset metadata, chunk text, indexing jobs, "
            "and revision tracking that determines whether vector snapshots are still valid.",
            styles,
        )
    )
    story.append(schema_table(styles))
    story.append(Spacer(1, 0.12 * inch))
    for text in [
        "indexed_images remains useful for image-specific metadata and FTS triggers, while indexed_assets generalizes the project into a multi-asset search engine.",
        "asset_chunks stores the retrieval granularity for documents and voice notes. A single file can yield many chunks, each with its own embedding.",
        "Revision counters in app_settings help the vector layer decide when a persisted FAISS index can be trusted and when it must be rebuilt.",
    ]:
        story.append(bullet(text, styles))

    story.append(Paragraph("5. Indexing Pipeline", styles["SectionHeading"]))
    story.append(
        body(
            "The indexer is designed around batch preparation and chunk flushing. It walks watched folders, normalizes assets into a common schema, "
            "and writes metadata, chunks, and embeddings in coordinated batches.",
            styles,
        )
    )
    story.append(
        KeepTogether(
            [
                callout(
                    "Asset Processing Paths",
                    "Images: hash file, generate thumbnail, optionally reuse duplicate OCR/vector data, run OCR if needed, embed image, and persist both the image record and OCR-derived text chunks.\n"
                    "Documents: extract native text from TXT/DOCX/PDF, fall back to OCR for weak PDFs, generate a preview, chunk the text, embed each chunk, and persist as indexed_assets + asset_chunks.\n"
                    "Voice notes: transcribe on demand, merge segments into ~45 second transcript chunks, embed each chunk, and persist the transcript-backed asset.",
                    styles,
                    color="#0F4760",
                ),
                Spacer(1, 0.12 * inch),
            ]
        )
    )
    for text in [
        "Chunking is overlap-based for documents and time-window-based for transcripts, which preserves semantic continuity while still allowing targeted retrieval.",
        "The pipeline aggressively skips unchanged ready assets by comparing modification time, file size, and preview readiness before recomputing work.",
        "Watcher-triggered updates batch filesystem events so Recall can coalesce bursts of changes instead of reindexing each file in isolation.",
    ]:
        story.append(bullet(text, styles))

    story.append(Paragraph("6. Search and Ranking", styles["SectionHeading"]))
    story.append(
        body(
            "Recall combines lexical and semantic evidence rather than choosing one or the other. The search service runs FTS queries and vector search in parallel conceptually, "
            "merges candidate ids, and then ranks the union with a lightweight blending rule.",
            styles,
        )
    )
    story.append(ranking_table(styles))
    story.append(Spacer(1, 0.12 * inch))
    for text in [
        "Image queries search OCR text through FTS and image vectors through FAISS, then blend both candidate sets with a small recency term.",
        "Document and voice-note queries work at chunk level semantically, but the UI returns asset-level rows by collapsing chunk hits back to their parent asset ids.",
        "Browse mode is distinct from query mode: an empty query returns recent assets from SQLite without invoking embeddings.",
    ]:
        story.append(bullet(text, styles))

    story.append(PageBreak())
    story.append(Paragraph("7. OCR, Transcription, and Deferred Services", styles["SectionHeading"]))
    story.append(
        body(
            "A recent and important refactor moved indexing-only services off the startup-critical path. "
            "That change is the main reason the desktop shell can feel responsive even though Recall still ships real ML dependencies locally.",
            styles,
        )
    )
    story.append(
        callout(
            "Deferred-by-Design",
            "OCR and transcription are wrapped in lazy engines. Their status begins as deferred, transitions to warming only when indexing needs them, "
            "and becomes ready or limited depending on which backend successfully initializes. This keeps normal startup focused on search instead of ingestion.",
            styles,
            color="#17556F",
        )
    )
    story.append(Spacer(1, 0.12 * inch))
    for text in [
        "LazyOcrEngine can promote from PaddleOCR to Tesseract at runtime if Paddle inference fails after startup.",
        "LazyTranscriptionEngine attempts faster-whisper small on CPU with int8 compute and drops to a no-op limited mode if the dependency stack fails.",
        "Document OCR fallback is only triggered for weak PDFs, which keeps searchable text extraction cheap when native PDF text is already usable.",
    ]:
        story.append(bullet(text, styles))

    story.append(Paragraph("8. Packaging and Deployment Mechanics", styles["SectionHeading"]))
    story.append(
        body(
            "Packaging is one of the trickier parts of Recall because the app is not just a thin UI. It ships a desktop shell plus a Python runtime and ML-oriented libraries.",
            styles,
        )
    )
    story.append(packaging_table(styles))
    story.append(Spacer(1, 0.12 * inch))
    for text in [
        "The recent runtime refactor moved packaged Recall away from workspace-relative assumptions and toward Tauri-bundled resources.",
        "The packaging optimization work pruned the production runtime instead of bundling the entire development environment blindly.",
        "This is a normal tension in local AI apps: deployment reliability improves when dependencies are bundled explicitly, but bundle size and installer time grow as a result.",
    ]:
        story.append(bullet(text, styles))

    story.append(Paragraph("9. Notable Strengths and Tradeoffs", styles["SectionHeading"]))
    strengths = [
        "Local-first by default: images, OCR text, embeddings, ranking, and search remain on the user’s device.",
        "Semantic search is treated as product-critical rather than as a later enhancement layered on top of text search.",
        "The codebase has a coherent degradation story: FAISS can fall back to NumPy, preferred embedders can fall back to hashed vectors, and OCR can fall back from Paddle to Tesseract.",
    ]
    tradeoffs = [
        "Shipping Python + ML dependencies makes packaging materially heavier than a typical Tauri-only desktop application.",
        "The health contract is scope-sensitive, so the product story should be communicated carefully to avoid confusion between shell readiness and deep semantic readiness.",
        "SQLite + dual vector indices is elegant for a local app, but the system still carries real cold-start cost because both embedding stacks are startup-critical by design.",
    ]
    story.append(Paragraph("Strengths", styles["SubHeading"]))
    for text in strengths:
        story.append(bullet(text, styles))
    story.append(Paragraph("Tradeoffs", styles["SubHeading"]))
    for text in tradeoffs:
        story.append(bullet(text, styles))

    story.append(Paragraph("10. Practical Mental Model", styles["SectionHeading"]))
    story.append(
        callout(
            "How to Explain Recall to a Technical Viewer",
            "Recall is a local desktop retrieval engine with a Tauri shell. Rust owns orchestration, Python owns indexing and search, SQLite stores canonical metadata, "
            "FTS handles lexical retrieval, FAISS accelerates vector similarity, OpenCLIP matches text to images, BGE matches text to documents and transcripts, "
            "and OCR/transcription are lazy services that expand the searchable corpus without slowing normal startup.",
            styles,
            color="#0E3950",
        )
    )
    story.append(Spacer(1, 0.12 * inch))
    return story


def build_pdf() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    styles = build_styles()
    doc = SimpleDocTemplate(
        str(OUTPUT_PATH),
        pagesize=letter,
        leftMargin=0.65 * inch,
        rightMargin=0.65 * inch,
        topMargin=0.72 * inch,
        bottomMargin=0.55 * inch,
        title="Recall Technical Deep Dive",
        author="OpenAI Codex",
    )
    story = build_story(styles)
    doc.build(story, onFirstPage=page_background, onLaterPages=page_background)
    return OUTPUT_PATH


if __name__ == "__main__":
    path = build_pdf()
    print(path)
