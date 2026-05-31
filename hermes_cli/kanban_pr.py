"""GitHub pull request discovery, live status, and merge auto-complete for kanban.

Workers often leave a PR URL in a comment or run summary. This module finds
those URLs, polls GitHub for state, surfaces status on dashboard cards, and
auto-completes tasks when the PR is merged.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Iterable, Optional

import httpx

logger = logging.getLogger(__name__)

# Shared with kanban_db respawn guard — keep in sync.
GITHUB_PR_URL_RE = re.compile(
    r"https?://github\.com/[^/\s]+/[^/\s]+/pull/\d+",
    re.IGNORECASE,
)

_PR_STATUS_CACHE: dict[str, tuple[float, Optional["PullRequestInfo"]]] = {}
_PR_STATUS_CACHE_TTL = 60.0
_PR_STATUS_DB_TABLE = "pr_status_cache"
# When scanning runs for PR URLs, only inspect recent rows per task (board load).
_PR_DISCOVERY_RUNS_PER_TASK = 16
PR_MERGED_SUMMARY_PREFIX = "PR Merged into "


@dataclass(frozen=True)
class PullRequestInfo:
    url: str
    state: str
    merged: bool
    draft: bool
    target_branch: str
    label: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "state": self.state,
            "merged": self.merged,
            "draft": self.draft,
            "target_branch": self.target_branch,
            "label": self.label,
        }


def normalize_github_pr_url(url: str) -> str:
    """Strip trailing punctuation from a matched PR URL."""
    return url.rstrip(".,);]>'\"")


def extract_github_pr_url(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    match = GITHUB_PR_URL_RE.search(text)
    if not match:
        return None
    return normalize_github_pr_url(match.group(0))


def _iter_searchable_strings(value: Any) -> Iterable[str]:
    if value is None:
        return
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from _iter_searchable_strings(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_searchable_strings(item)


def _first_pr_url_in_texts(texts: Iterable[str]) -> Optional[str]:
    for text in texts:
        url = extract_github_pr_url(text)
        if url:
            return url
    return None


def _pr_url_from_run_row(row) -> Optional[str]:
    """Extract a GitHub PR URL from a ``task_runs`` row (summary, error, metadata)."""
    texts: list[str] = []
    if row["summary"]:
        texts.append(row["summary"])
    error = row["error"] if "error" in row.keys() else None
    if error:
        texts.append(error)
    if row["metadata"]:
        try:
            meta = json.loads(row["metadata"])
        except (TypeError, json.JSONDecodeError):
            meta = None
        texts.extend(_iter_searchable_strings(meta))
    return _first_pr_url_in_texts(texts)


def _parse_github_pr_path(url: str) -> Optional[tuple[str, str, int]]:
    match = re.match(
        r"https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)",
        url,
        re.IGNORECASE,
    )
    if not match:
        return None
    owner, repo, number = match.group(1), match.group(2), int(match.group(3))
    if repo.endswith(".git"):
        repo = repo[:-4]
    return owner, repo, number


def _resolve_github_token() -> Optional[str]:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token.strip()
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _pr_label(*, state: str, merged: bool, draft: bool) -> str:
    if merged:
        return "Merged"
    if draft and state == "open":
        return "Draft"
    if state == "open":
        return "Open"
    if state == "closed":
        return "Closed"
    return state.capitalize() if state else "Unknown"


def _pr_info_is_unknown(info: Optional[PullRequestInfo]) -> bool:
    """True when cache has no usable label (miss or failed fetch)."""
    if info is None:
        return True
    if (info.label or "").strip().lower() == "unknown":
        return True
    return (info.state or "").strip().lower() == "unknown"


def _ensure_pr_status_cache_table(conn) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_PR_STATUS_DB_TABLE} (
            url TEXT PRIMARY KEY,
            payload TEXT,
            fetched_at INTEGER NOT NULL
        )
        """
    )


def _info_to_db_payload(info: Optional[PullRequestInfo]) -> Optional[str]:
    if info is None:
        return None
    return json.dumps(info.to_dict(), ensure_ascii=False)


def _info_from_db_payload(payload: Optional[str]) -> Optional[PullRequestInfo]:
    if not payload:
        return None
    try:
        data = json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return PullRequestInfo(
        url=str(data.get("url") or ""),
        state=str(data.get("state") or "unknown"),
        merged=bool(data.get("merged")),
        draft=bool(data.get("draft")),
        target_branch=str(data.get("target_branch") or ""),
        label=str(data.get("label") or "Unknown"),
    )


def _load_pr_status_from_db(conn, url: str) -> Optional[PullRequestInfo]:
    """Read a fresh PR status row from the board DB cache."""
    normalized = normalize_github_pr_url(url)
    _ensure_pr_status_cache_table(conn)
    row = conn.execute(
        f"SELECT payload, fetched_at FROM {_PR_STATUS_DB_TABLE} WHERE url = ?",
        (normalized,),
    ).fetchone()
    if not row:
        return None
    if time.time() - int(row["fetched_at"]) >= _PR_STATUS_CACHE_TTL:
        return None
    return _info_from_db_payload(row["payload"])


def _load_pr_status_batch_from_db(
    conn,
    urls: Iterable[str],
) -> dict[str, Optional[PullRequestInfo]]:
    """Batch-read PR status from the board DB (one query)."""
    normalized = [normalize_github_pr_url(u) for u in urls]
    normalized = list(dict.fromkeys(u for u in normalized if u))
    if not normalized:
        return {}
    _ensure_pr_status_cache_table(conn)
    now = time.time()
    placeholders = ",".join("?" for _ in normalized)
    rows = conn.execute(
        f"SELECT url, payload, fetched_at FROM {_PR_STATUS_DB_TABLE} "
        f"WHERE url IN ({placeholders})",
        tuple(normalized),
    ).fetchall()
    out: dict[str, Optional[PullRequestInfo]] = {}
    for row in rows:
        if now - int(row["fetched_at"]) >= _PR_STATUS_CACHE_TTL:
            continue
        out[row["url"]] = _info_from_db_payload(row["payload"])
    return out


def _save_pr_status_to_db(
    conn,
    url: str,
    info: Optional[PullRequestInfo],
) -> None:
    normalized = normalize_github_pr_url(url)
    _ensure_pr_status_cache_table(conn)
    conn.execute(
        f"INSERT OR REPLACE INTO {_PR_STATUS_DB_TABLE} "
        f"(url, payload, fetched_at) VALUES (?, ?, ?)",
        (normalized, _info_to_db_payload(info), int(time.time())),
    )


def cached_pull_request_info(
    url: str,
    *,
    conn=None,
) -> Optional[PullRequestInfo]:
    """Return cached PR state when fresh; never hits the network."""
    normalized = normalize_github_pr_url(url)
    now = time.time()
    cached = _PR_STATUS_CACHE.get(normalized)
    if cached and now - cached[0] < _PR_STATUS_CACHE_TTL:
        return cached[1]
    if conn is not None:
        db_info = _load_pr_status_from_db(conn, normalized)
        if db_info is not None:
            _PR_STATUS_CACHE[normalized] = (now, db_info)
            return db_info
        # Fresh negative cache (fetch failed recently).
        _ensure_pr_status_cache_table(conn)
        row = conn.execute(
            f"SELECT payload, fetched_at FROM {_PR_STATUS_DB_TABLE} WHERE url = ?",
            (normalized,),
        ).fetchone()
        if row and now - int(row["fetched_at"]) < _PR_STATUS_CACHE_TTL:
            if row["payload"] is None:
                _PR_STATUS_CACHE[normalized] = (now, None)
                return None
    return None


def invalidate_pr_status_cache(url: Optional[str] = None, *, conn=None) -> None:
    """Drop cached GitHub PR state so the next fetch is live."""
    if url is None:
        _PR_STATUS_CACHE.clear()
        if conn is not None:
            _ensure_pr_status_cache_table(conn)
            conn.execute(f"DELETE FROM {_PR_STATUS_DB_TABLE}")
        return
    normalized = normalize_github_pr_url(url)
    _PR_STATUS_CACHE.pop(normalized, None)
    if conn is not None:
        _ensure_pr_status_cache_table(conn)
        conn.execute(
            f"DELETE FROM {_PR_STATUS_DB_TABLE} WHERE url = ?",
            (normalized,),
        )


def _cache_pr_status(
    url: str,
    info: Optional[PullRequestInfo],
    *,
    conn=None,
) -> None:
    normalized = normalize_github_pr_url(url)
    _PR_STATUS_CACHE[normalized] = (time.time(), info)
    if conn is not None:
        _save_pr_status_to_db(conn, normalized, info)


def _batch_cached_pull_request_info(
    conn,
    urls: Iterable[str],
) -> dict[str, Optional[PullRequestInfo]]:
    """Resolve many PR URLs from memory + board DB only (no network)."""
    unique = list(
        dict.fromkeys(normalize_github_pr_url(u) for u in urls if u)
    )
    out: dict[str, Optional[PullRequestInfo]] = {}
    need_db: list[str] = []
    now = time.time()
    for url in unique:
        entry = _PR_STATUS_CACHE.get(url)
        if entry and now - entry[0] < _PR_STATUS_CACHE_TTL:
            out[url] = entry[1]
            continue
        need_db.append(url)
    if need_db:
        db_map = _load_pr_status_batch_from_db(conn, need_db)
        for url in need_db:
            if url not in db_map:
                continue
            info = db_map[url]
            _PR_STATUS_CACHE[url] = (now, info)
            out[url] = info
    return out


def _pr_status_from_merge_summary(summary: Optional[str], url: str) -> Optional[dict[str, Any]]:
    """Return merged PR status derived from an auto-complete handoff summary."""
    text = (summary or "").strip()
    if not text.startswith(PR_MERGED_SUMMARY_PREFIX):
        return None
    target_branch = text[len(PR_MERGED_SUMMARY_PREFIX):].strip() or "target branch"
    info = PullRequestInfo(
        url=url,
        state="closed",
        merged=True,
        draft=False,
        target_branch=target_branch,
        label="Merged",
    )
    _cache_pr_status(url, info)
    return info.to_dict()


def _task_merge_summary(task_dict: dict[str, Any]) -> Optional[str]:
    """Best-effort completion summary for PR merge inference."""
    summary = task_dict.get("latest_summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    result = task_dict.get("result")
    if isinstance(result, str) and result.strip():
        return result.strip()
    return None


def fetch_pull_request_info(
    url: str,
    *,
    force_refresh: bool = False,
    conn=None,
) -> Optional[PullRequestInfo]:
    """Return live GitHub PR state for ``url``, with a short TTL cache."""
    normalized = normalize_github_pr_url(url)
    now = time.time()
    if not force_refresh:
        cached = cached_pull_request_info(normalized, conn=conn)
        if cached is not None and not _pr_info_is_unknown(cached):
            return cached
        entry = _PR_STATUS_CACHE.get(normalized)
        if entry and now - entry[0] < _PR_STATUS_CACHE_TTL and entry[1] is None:
            return None

    parsed = _parse_github_pr_path(normalized)
    if not parsed:
        _cache_pr_status(normalized, None, conn=conn)
        return None

    owner, repo, number = parsed
    api_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = _resolve_github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    info: Optional[PullRequestInfo] = None
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(api_url, headers=headers)
        if resp.status_code == 404:
            logger.debug("GitHub PR not found: %s", normalized)
        elif resp.status_code == 403:
            logger.debug("GitHub PR fetch forbidden (rate limit?): %s", normalized)
        elif resp.is_success:
            data = resp.json()
            merged = bool(data.get("merged_at"))
            state = str(data.get("state") or "unknown")
            draft = bool(data.get("draft"))
            base = data.get("base") or {}
            target_branch = str(base.get("ref") or "")
            html_url = str(data.get("html_url") or normalized)
            info = PullRequestInfo(
                url=html_url,
                state=state,
                merged=merged,
                draft=draft,
                target_branch=target_branch,
                label=_pr_label(state=state, merged=merged, draft=draft),
            )
        else:
            logger.debug(
                "GitHub PR fetch failed (%s): %s",
                resp.status_code,
                normalized,
            )
    except Exception as exc:
        logger.debug("GitHub PR fetch error for %s: %s", normalized, exc)

    _cache_pr_status(normalized, info, conn=conn)
    return info


def find_pr_urls_for_tasks(
    conn,
    task_ids: Iterable[str],
) -> dict[str, str]:
    """Return ``{task_id: pr_url}`` for tasks with a discoverable PR link."""
    ids = list(dict.fromkeys(task_ids))
    if not ids:
        return {}

    found: dict[str, str] = {}
    placeholders = ",".join("?" for _ in ids)

    comment_rows = conn.execute(
        f"""
        SELECT task_id, body
          FROM task_comments
         WHERE task_id IN ({placeholders})
           AND body LIKE '%github.com%/pull/%'
         ORDER BY created_at DESC
        """,
        tuple(ids),
    ).fetchall()
    for row in comment_rows:
        tid = row["task_id"]
        if tid in found:
            continue
        url = extract_github_pr_url(row["body"])
        if url:
            found[tid] = url

    remaining = [tid for tid in ids if tid not in found]
    if remaining:
        run_placeholders = ",".join("?" for _ in remaining)
        run_rows = conn.execute(
            f"""
            SELECT task_id, summary, metadata, error
              FROM (
                SELECT task_id, summary, metadata, error,
                       ROW_NUMBER() OVER (
                         PARTITION BY task_id
                         ORDER BY COALESCE(ended_at, started_at) DESC, id DESC
                       ) AS rn
                  FROM task_runs
                 WHERE task_id IN ({run_placeholders})
              )
             WHERE rn <= ?
            """,
            tuple(remaining) + (_PR_DISCOVERY_RUNS_PER_TASK,),
        ).fetchall()
        for row in run_rows:
            tid = row["task_id"]
            if tid in found:
                continue
            url = _pr_url_from_run_row(row)
            if url:
                found[tid] = url

    remaining = [tid for tid in ids if tid not in found]
    if remaining:
        task_placeholders = ",".join("?" for _ in remaining)
        task_rows = conn.execute(
            f"SELECT id, result FROM tasks WHERE id IN ({task_placeholders})",
            tuple(remaining),
        ).fetchall()
        for row in task_rows:
            url = extract_github_pr_url(row["result"])
            if url:
                found[row["id"]] = url

    return found


def pr_info_for_task(
    conn,
    task_id: str,
    *,
    fetch_live: bool = True,
    task_dict: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Return PR status dict for a task, or None when no PR URL is known."""
    urls = find_pr_urls_for_tasks(conn, [task_id])
    url = urls.get(task_id)
    if not url:
        return None

    if task_dict is None:
        from hermes_cli import kanban_db as kb

        task = kb.get_task(conn, task_id)
        if task is not None:
            task_dict = {
                "status": task.status,
                "latest_summary": kb.latest_summary(conn, task_id),
                "result": task.result,
            }

    if task_dict and task_dict.get("status") == "done":
        merged = _pr_status_from_merge_summary(_task_merge_summary(task_dict), url)
        if merged:
            return merged

    cached = cached_pull_request_info(url, conn=conn)
    if cached is not None and not _pr_info_is_unknown(cached):
        return cached.to_dict()

    if not fetch_live:
        return {
            "url": url,
            "label": "Unknown",
            "state": "unknown",
            "merged": False,
            "draft": False,
            "target_branch": "",
        }

    # Drawer / explicit refresh: live fetch only when cache is missing or unknown.
    if _pr_info_is_unknown(cached):
        info = fetch_pull_request_info(url, force_refresh=True, conn=conn)
        if info:
            return info.to_dict()
    elif cached is not None:
        return cached.to_dict()

    return {
        "url": url,
        "label": "Unknown",
        "state": "unknown",
        "merged": False,
        "draft": False,
        "target_branch": "",
    }


def attach_pr_status_to_task_dicts(
    conn,
    task_dicts: list[dict[str, Any]],
    *,
    fetch_live: bool = True,
    cache_only: bool = False,
    resolve_unknown: bool = False,
) -> None:
    """Mutate task dicts in place, adding a ``pr`` field when applicable.

    ``cache_only`` (board load): memory + per-board SQLite cache only — no
    GitHub calls. ``resolve_unknown``: live fetch only for URLs whose cached
    state is missing or ``Unknown`` (task drawer). Dispatcher merge sync uses
    ``fetch_pull_request_info(..., force_refresh=True)`` directly.
    """
    if not task_dicts:
        return
    urls = find_pr_urls_for_tasks(conn, [d["id"] for d in task_dicts])
    if not urls:
        return

    unique_urls = list(dict.fromkeys(urls.values()))
    info_by_url: dict[str, Optional[PullRequestInfo]] = {}
    if cache_only:
        info_by_url = _batch_cached_pull_request_info(conn, unique_urls)
    elif fetch_live:
        if resolve_unknown:
            cached_map = _batch_cached_pull_request_info(conn, unique_urls)
            for url in unique_urls:
                norm = normalize_github_pr_url(url)
                cached = cached_map.get(norm)
                if _pr_info_is_unknown(cached):
                    info_by_url[norm] = fetch_pull_request_info(
                        url, force_refresh=True, conn=conn,
                    )
                else:
                    info_by_url[norm] = cached
        else:
            for url in unique_urls:
                norm = normalize_github_pr_url(url)
                info_by_url[norm] = fetch_pull_request_info(url, conn=conn)

    for d in task_dicts:
        url = urls.get(d["id"])
        if not url:
            continue
        if d.get("status") == "done":
            merged = _pr_status_from_merge_summary(_task_merge_summary(d), url)
            if merged:
                d["pr"] = merged
                continue
        if fetch_live or cache_only:
            norm = normalize_github_pr_url(url)
            info = info_by_url.get(norm)
            if info:
                d["pr"] = info.to_dict()
            else:
                d["pr"] = {
                    "url": url,
                    "label": "Unknown",
                    "state": "unknown",
                    "merged": False,
                    "draft": False,
                    "target_branch": "",
                }
        else:
            d["pr"] = {
                "url": url,
                "label": "Unknown",
                "state": "unknown",
                "merged": False,
                "draft": False,
                "target_branch": "",
            }


def sync_merged_pull_requests(conn) -> list[str]:
    """Auto-complete open tasks whose linked PR has merged.

    Returns the list of task ids transitioned to ``done``.
    """
    from hermes_cli import kanban_db as kb

    rows = conn.execute(
        "SELECT id FROM tasks WHERE status NOT IN ('done', 'archived')"
    ).fetchall()
    if not rows:
        return []

    task_ids = [row["id"] for row in rows]
    urls = find_pr_urls_for_tasks(conn, task_ids)
    if not urls:
        return []

    completed: list[str] = []
    for task_id, url in urls.items():
        info = fetch_pull_request_info(url, force_refresh=True, conn=conn)
        if not info or not info.merged:
            continue
        summary = f"{PR_MERGED_SUMMARY_PREFIX}{info.target_branch or 'target branch'}"
        ok = kb.complete_task(
            conn,
            task_id,
            summary=summary,
            metadata={
                "pr_merged": True,
                "pr_url": info.url,
                "pr_target_branch": info.target_branch,
            },
            enforce_review=False,
        )
        if ok:
            completed.append(task_id)
            logger.info(
                "Auto-completed task %s after PR merge (%s)",
                task_id,
                info.url,
            )
    return completed
