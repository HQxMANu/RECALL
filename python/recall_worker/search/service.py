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
    def __init__(self, database, *args) -> None:
        self.database = database
        if len(args) == 3:
            image_embedder, image_vector_index, limit = args
            self.image_embedder = image_embedder
            self.text_embedder = image_embedder
            self.image_vector_index = image_vector_index
            self.text_vector_index = image_vector_index
            self.limit = limit
            return
        if len(args) == 5:
            image_embedder, text_embedder, image_vector_index, text_vector_index, limit = args
            self.image_embedder = image_embedder
            self.text_embedder = text_embedder
            self.image_vector_index = image_vector_index
            self.text_vector_index = text_vector_index
            self.limit = limit
            return
        raise TypeError("SearchService expects either 3 or 5 constructor arguments after database")

    def search(self, request: dict) -> dict:
        started = time.perf_counter()
        query = request.get("query", "").strip()
        folder_ids = request.get("folderIds") or []
        sort = request.get("sort", "relevance")
        limit = min(int(request.get("limit", 50) or 50), 100)
        offset = max(0, int(request.get("offset", 0) or 0))
        scope = request.get("scope", "images")

        if not query:
            return self._browse(scope, folder_ids, sort, limit, offset, started)

        if scope == "images":
            return self._search_images(query, folder_ids, sort, limit, offset, started)
        if scope == "documents":
            return self._search_text_assets("document", query, folder_ids, sort, limit, offset, started)
        if scope == "voice-notes":
            return self._search_text_assets("voice-note", query, folder_ids, sort, limit, offset, started)
        raise ValueError(f"Unsupported search scope: {scope}")

    def _browse(self, scope: str, folder_ids: list[int], sort: str, limit: int, offset: int, started: float) -> dict:
        if scope == "images":
            rows = self.database.recent_assets("image", folder_ids, sort, limit, offset)
        elif scope == "documents":
            rows = self.database.recent_assets("document", folder_ids, sort, limit, offset)
        elif scope == "voice-notes":
            rows = self.database.recent_assets("voice-note", folder_ids, sort, limit, offset)
        else:
            rows = []

        results = [self._format_browse_row(dict(row)) for row in rows]
        took_ms = round((time.perf_counter() - started) * 1000)
        return {
            "results": results,
            "tookMs": took_ms,
            "totalHits": len(results),
            "queryDebug": {"mode": "browse", "semanticCandidates": 0, "textCandidates": 0, "scope": scope},
        }

    def _search_images(self, query: str, folder_ids: list[int], sort: str, limit: int, offset: int, started: float) -> dict:
        fts_query = build_fts_query(query)
        text_rows = self.database.fts_search(fts_query, folder_ids, self.limit) if fts_query else []
        semantic_vector = self.image_embedder.embed_text(query)
        semantic_hits = self.image_vector_index.search(semantic_vector, self.limit)
        combined_ids = [int(row["id"]) for row in text_rows] + [image_id for image_id, _ in semantic_hits]
        metadata_rows = self.database.fetch_images_by_ids(combined_ids)
        metadata_by_id = {
            image_id: {
                **dict(row),
                "asset_type": "image",
                "preview_path": row["thumbnail_path"],
                "snippet": (row["ocr_text"] or "")[:280] or None,
            }
            for image_id, row in metadata_rows.items()
        }

        if folder_ids:
            semantic_hits = [
                (image_id, score)
                for image_id, score in semantic_hits
                if image_id in metadata_by_id and int(metadata_by_id[image_id]["folder_id"]) in folder_ids
            ]

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
            "queryDebug": {**debug, "scope": "images"},
        }

    def _search_text_assets(
        self,
        asset_type: str,
        query: str,
        folder_ids: list[int],
        sort: str,
        limit: int,
        offset: int,
        started: float,
    ) -> dict:
        fts_query = build_fts_query(query)
        text_rows = self.database.asset_fts_search(fts_query, asset_type, folder_ids, self.limit) if fts_query else []

        semantic_vector = self.text_embedder.embed_text(query)
        semantic_hits = self.text_vector_index.search(semantic_vector, self.limit * 3)
        semantic_rows_by_chunk = self.database.fetch_chunk_rows_by_ids(
            [chunk_id for chunk_id, _score in semantic_hits],
            asset_type,
            folder_ids,
        )

        text_ranked_asset_ids: list[int] = []
        semantic_ranked_asset_ids: list[int] = []
        metadata_by_id: dict[int, dict] = {}

        for row in text_rows:
            asset_id = int(row["asset_id"])
            if asset_id not in text_ranked_asset_ids:
                text_ranked_asset_ids.append(asset_id)
            metadata_by_id.setdefault(asset_id, self._metadata_from_chunk_row(dict(row), asset_type))

        for chunk_id, _score in semantic_hits:
            row = semantic_rows_by_chunk.get(chunk_id)
            if row is None:
                continue
            asset_id = int(row["asset_id"])
            if asset_id not in semantic_ranked_asset_ids:
                semantic_ranked_asset_ids.append(asset_id)
            metadata_by_id.setdefault(asset_id, self._metadata_from_chunk_row(dict(row), asset_type))

        ranked_results, debug = blend_results(
            query=query,
            text_ranked_ids=text_ranked_asset_ids,
            semantic_ranked_ids=semantic_ranked_asset_ids,
            metadata_by_id=metadata_by_id,
            sort=sort,
        )
        paged = ranked_results[offset : offset + limit]
        took_ms = round((time.perf_counter() - started) * 1000)
        return {
            "results": paged,
            "tookMs": took_ms,
            "totalHits": len(ranked_results),
            "queryDebug": {**debug, "scope": asset_type},
        }

    @staticmethod
    def _metadata_from_chunk_row(row: dict, asset_type: str) -> dict:
        return {
            "path": row["path"],
            "filename": row["filename"],
            "modified_at_fs": row["modified_at_fs"],
            "created_at_fs": row.get("created_at_fs"),
            "folder_id": row["folder_id"],
            "folder_name": row.get("folder_name"),
            "asset_type": asset_type,
            "preview_path": row.get("preview_path"),
            "snippet": (row.get("chunk_text") or "")[:280] or None,
            "page_number": row.get("page_number"),
            "start_ms": row.get("start_ms"),
            "end_ms": row.get("end_ms"),
            "duration_ms": row.get("duration_ms"),
            "width": row.get("width"),
            "height": row.get("height"),
        }

    @staticmethod
    def _format_browse_row(row: dict) -> dict:
        snippet = None
        if row.get("asset_type") == "image":
            snippet = None
        return {
            "imageId": int(row["id"]),
            "assetId": int(row["id"]),
            "assetType": row["asset_type"],
            "path": row["path"],
            "filename": row["filename"],
            "thumbnailPath": row.get("preview_path"),
            "previewPath": row.get("preview_path"),
            "modifiedAt": row["modified_at_fs"],
            "createdAt": row.get("created_at_fs"),
            "ocrSnippet": snippet,
            "snippet": snippet,
            "semanticScore": 0.0,
            "textScore": 0.0,
            "finalScore": 0.0,
            "folderId": int(row["folder_id"]),
            "folderName": row.get("folder_name"),
            "width": row.get("width"),
            "height": row.get("height"),
            "pageNumber": None,
            "startMs": None,
            "endMs": None,
            "durationMs": row.get("duration_ms"),
        }
