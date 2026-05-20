from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable


def _weight_profile(query: str) -> tuple[float, float, float]:
    if '"' in query or "." in query:
        return 0.45, 0.5, 0.05
    return 0.65, 0.3, 0.05


def _rank_score(position: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return max(0.0, 1.0 - (position / max(total, 1)))


def recency_boost(iso_value: str | None) -> float:
    if not iso_value:
        return 0.0
    try:
        modified = datetime.fromisoformat(iso_value.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    age_days = max(0.0, (datetime.now(timezone.utc) - modified).total_seconds() / 86400)
    return max(0.0, 1.0 - min(age_days, 365.0) / 365.0)


def blend_results(
    query: str,
    text_ranked_ids: Iterable[int],
    semantic_ranked_ids: Iterable[int],
    metadata_by_id: dict[int, dict],
    sort: str,
) -> tuple[list[dict], dict]:
    text_ids = list(dict.fromkeys(text_ranked_ids))
    semantic_ids = list(dict.fromkeys(semantic_ranked_ids))
    semantic_weight, text_weight, recency_weight = _weight_profile(query)

    combined_ids = list(dict.fromkeys(text_ids + semantic_ids))
    results: list[dict] = []
    total_text = max(len(text_ids), 1)
    total_semantic = max(len(semantic_ids), 1)
    text_positions = {image_id: position for position, image_id in enumerate(text_ids)}
    semantic_positions = {image_id: position for position, image_id in enumerate(semantic_ids)}

    for image_id in combined_ids:
        metadata = metadata_by_id.get(image_id)
        if not metadata:
            continue
        text_position = text_positions.get(image_id)
        semantic_position = semantic_positions.get(image_id)
        text_score = _rank_score(text_position, total_text) if text_position is not None else 0.0
        semantic_score = _rank_score(semantic_position, total_semantic) if semantic_position is not None else 0.0
        freshness = recency_boost(metadata.get("modified_at_fs"))
        final_score = (
            semantic_weight * semantic_score
            + text_weight * text_score
            + recency_weight * freshness
        )
        results.append(
            {
                "imageId": image_id,
                "path": metadata["path"],
                "filename": metadata["filename"],
                "thumbnailPath": metadata.get("thumbnail_path"),
                "modifiedAt": metadata["modified_at_fs"],
                "createdAt": metadata.get("created_at_fs"),
                "ocrSnippet": (metadata.get("ocr_text") or "")[:280] or None,
                "semanticScore": round(semantic_score, 4),
                "textScore": round(text_score, 4),
                "finalScore": round(final_score, 4),
                "folderId": int(metadata["folder_id"]),
                "folderName": metadata.get("folder_name"),
                "width": metadata.get("width"),
                "height": metadata.get("height"),
            }
        )

    if sort == "newest":
        results.sort(key=lambda item: item["modifiedAt"], reverse=True)
    elif sort == "oldest":
        results.sort(key=lambda item: item["modifiedAt"])
    else:
        results.sort(key=lambda item: item["finalScore"], reverse=True)

    return results, {
        "semanticWeight": semantic_weight,
        "textWeight": text_weight,
        "recencyWeight": recency_weight,
        "textCandidates": len(text_ids),
        "semanticCandidates": len(semantic_ids),
    }
