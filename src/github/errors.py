from __future__ import annotations


class GitHubIntelligenceError(Exception):
    """GitHubIntelligence modülündeki genel hatalar için taban sınıf."""


class GitHubRateLimitError(GitHubIntelligenceError):
    """GitHub API rate limit'e takılıp güvenli şekilde beklenemediğinde
    (bekleme süresi çok uzunsa) fırlatılır."""
