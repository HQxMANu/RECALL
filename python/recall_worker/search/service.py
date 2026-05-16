from __future__ import annotations

import re
import time

from recall_worker.search.ranking import blend_results


TOKEN_RE = re.compile(r'"[^"]+"|[a-zA-Z0-9_.-]+')


def build_fts_query(query: str) -> str:
    terms = [term.strip('"') for term in TOKEN_RE.findall(query)]
    if not terms:
        return ""
    return " AND ".join(f'"{term}"' for term in terms if term)


class SearchService:
    def __init__(self, database, embedder, vector_index, limit: int) -> None:
        self.database = database
        self.embedder = embedder
        self.vector_index = vector_index
        self.limit = limit

    def search(self, request: dict) -> dict:
        started = time.perf_counter()
        query = request.get("query", "").strip()
        folder_ids = request.get("folderIds") or []
        sort = request.get("sort", "relevance")
        limit = min(int(request.get("limit", 50) or 50), 100)
        offset = max(0, int(request.get("offset", 0) or 0))

        if not query:
            rows = self.database.recent_images(folder_ids, sort, limit, offset)
            results = [
                {
                    "imageId": int(row["id"]),
                    "path": row["path"],
                    "filename": row["filename"],
                    "thumbnailPath": row["thumbnail_path"],
                    "modifiedAt": row["modified_at_fs"],
                    "createdAt": row["created_at_fs"],
                    "ocrSnippet": (row["ocr_text"] or "")[:280] or None,
                    "semanticScore": 0.0,
                    "textScore": 0.0,
                    "finalScore": 0.0,
                    "folderId": int(row["folder_id"]),
                    "folderName": row["folder_name"],
                    "width": row["width"],
                    "height": row["height"],
                }
                for row in rows
            ]
            took_ms = round((time.perf_counter() - started) * 1000)
            return {
                "results": results,
                "tookMs": took_ms,
                "totalHits": len(results),
                "queryDebug": {"mode": "browse", "semanticCandidates": 0, "textCandidates": 0},
            }

        fts_query = build_fts_query(query)
        text_rows = self.database.fts_search(fts_query, folder_ids, self.limit) if fts_query else []
        semantic_vector = self.embedder.embed_text(query)
        semantic_hits = self.vector_index.search(semantic_vector, self.limit)

        if folder_ids:
            metadata_for_filter = self.database.fetch_images_by_ids(image_id for image_id, _ in semantic_hits)
            semantic_hits = [
                (image_id, score)
                for image_id, score in semantic_hits
                if image_id in metadata_for_filter and int(metadata_for_filter[image_id]["folder_id"]) in folder_ids
            ]

        combined_ids = [int(row["id"]) for row in text_rows] + [image_id for image_id, _ in semantic_hits]
        metadata_rows = self.database.fetch_images_by_ids(combined_ids)
        metadata_by_id = {image_id: dict(row) for image_id, row in metadata_rows.items()}

        ranked_results, debug = blend_results(
            query=query,
            text_ranked_ids=[int(row["id"]) for row in text_rows],
            semantic_ranked_ids=[image_id for image_id, _ in semantic_hits],
            metadata_by_id=metadata_by_id,
            sort=sort,
        )

        paged = ranked_results[offset : offset + limit]
        took_ms = round((time.perf_counter() - started) * 1000)
        return {
            "results": paged,
            "tookMs": took_ms,
            "totalHits": len(ranked_results),
            "queryDebug": debug,
        }
