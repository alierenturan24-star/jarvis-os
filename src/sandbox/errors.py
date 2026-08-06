from __future__ import annotations


class SandboxError(Exception):
    """SandboxManager içindeki genel hatalar için taban sınıf."""


class SandboxLimitExceeded(SandboxError):
    """Dosya sayısı/boyut sınırı aşıldığında dahili olarak kullanılır.

    Kullanıcıya sızmaz: ``clone_repository``/``inspect`` bunu yakalayıp
    ``SandboxStatus.BLOCKED`` durumuna çevirir.
    """
