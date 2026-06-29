from __future__ import annotations

import logging
from pathlib import Path
from typing import Generator

import pygit2

logger = logging.getLogger(__name__)


class GitConnector:
    """
    Read-only Git connector.
    Push is architecturally impossible: no write credentials, no push call.
    """

    def __init__(self, repo_url: str, token: str, project_id: str):
        self.repo_url = repo_url
        self.project_id = project_id
        self._token = token

    def _callbacks(self) -> pygit2.RemoteCallbacks:
        return pygit2.RemoteCallbacks(
            credentials=pygit2.UserPass("x-token", self._token)
        )

    # ── Clone / update ────────────────────────────────────────────────────────

    def clone_or_update(self, local_path: str) -> pygit2.Repository:
        """Clone if absent, fetch origin if already present. Never pushes."""
        lp = Path(local_path)
        if not lp.exists():
            logger.info("[git] Cloning %s → %s", self.repo_url, local_path)
            return pygit2.clone_repository(
                self.repo_url,
                str(lp),
                callbacks=self._callbacks(),
            )

        repo = pygit2.Repository(str(lp))
        logger.info("[git] Fetching updates for %s", self.repo_url)
        try:
            repo.remotes["origin"].fetch(callbacks=self._callbacks())
        except Exception as exc:
            logger.warning("[git] Fetch failed for %s: %s", self.repo_url, exc)
        return repo

    # ── File enumeration ──────────────────────────────────────────────────────

    def list_files(
        self, repo: pygit2.Repository, branch: str = "main"
    ) -> Generator[Path, None, None]:
        """Yield all file paths tracked in the given branch (relative to repo root)."""
        commit = self._resolve_branch(repo, branch)
        yield from self._walk_tree(repo, commit.tree, Path(""))

    def _walk_tree(
        self,
        repo: pygit2.Repository,
        tree: pygit2.Tree,
        prefix: Path,
    ) -> Generator[Path, None, None]:
        for entry in tree:
            entry_path = prefix / entry.name
            if entry.type_str == "tree":
                yield from self._walk_tree(repo, repo.get(entry.id), entry_path)
            elif entry.type_str == "blob":
                yield entry_path

    # ── File reading ──────────────────────────────────────────────────────────

    def read_file(
        self, repo: pygit2.Repository, file_path: str, branch: str = "main"
    ) -> str | None:
        """Return decoded content of a file at branch tip, or None on error."""
        try:
            commit = self._resolve_branch(repo, branch)
            blob = commit.tree / file_path
            return blob.data.decode("utf-8", errors="replace")
        except Exception as exc:
            logger.debug("[git] Cannot read %s@%s: %s", file_path, branch, exc)
            return None

    def read_file_bytes(
        self, repo: pygit2.Repository, file_path: str, branch: str = "main"
    ) -> bytes | None:
        try:
            commit = self._resolve_branch(repo, branch)
            blob = commit.tree / file_path
            return blob.data
        except Exception:
            return None

    # ── Metadata ──────────────────────────────────────────────────────────────

    def get_commit_hash(self, repo: pygit2.Repository, branch: str = "main") -> str:
        try:
            return str(self._resolve_branch(repo, branch).id)
        except Exception:
            return "unknown"

    def get_changed_files(
        self, repo: pygit2.Repository, old_commit_hash: str, new_commit_hash: str
    ) -> list[str]:
        """Return list of file paths changed between two commits."""
        try:
            old_commit = repo.get(old_commit_hash)
            new_commit = repo.get(new_commit_hash)
            diff = repo.diff(old_commit, new_commit)
            return [delta.new_file.path for delta in diff.deltas]
        except Exception as exc:
            logger.warning("[git] Cannot compute diff: %s", exc)
            return []

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_branch(repo: pygit2.Repository, branch: str) -> pygit2.Commit:
        """Resolve a branch name to its tip commit, with fallbacks."""
        # Try local branch
        ref = repo.lookup_branch(branch)
        if ref:
            return ref.peel(pygit2.Commit)
        # Try remote tracking branch
        ref = repo.lookup_branch(f"origin/{branch}", pygit2.GIT_BRANCH_REMOTE)
        if ref:
            return ref.peel(pygit2.Commit)
        # Fallback: HEAD
        logger.warning("[git] Branch '%s' not found, using HEAD", branch)
        return repo.head.peel(pygit2.Commit)
