from __future__ import annotations

import re

# Her giriş: (bulgu adı, regex, risk kategorisi).
# Kategori "network" | "execution" | "dependency" — ``evaluate_risk``
# bunları network_risk/execution_risk/dependency_risk'e toplar.
SUSPICIOUS_PATTERNS: tuple[tuple[str, re.Pattern, str], ...] = (
    ("curl ile çalıştırma (pipe-to-shell)", re.compile(r"curl\s+[^\n|]*\|\s*(sudo\s+)?(sh|bash|zsh)\b"), "network"),
    ("wget ile çalıştırma (pipe-to-shell)", re.compile(r"wget\s+[^\n|]*\|\s*(sudo\s+)?(sh|bash|zsh)\b"), "network"),
    ("PowerShell indir-ve-çalıştır", re.compile(r"Invoke-WebRequest|IWR\s|Invoke-Expression|IEX\s|IEX\(|DownloadString|DownloadFile", re.IGNORECASE), "network"),
    ("Base64 ile gizlenmiş komut (decode + pipe)", re.compile(r"base64\s+(-d|--decode)[^\n]*\|\s*(sh|bash|zsh)", re.IGNORECASE), "network"),
    ("os.system çağrısı", re.compile(r"os\.system\s*\("), "execution"),
    ("subprocess shell=True", re.compile(r"subprocess\.[A-Za-z_]+\([^)]*shell\s*=\s*True"), "execution"),
    ("eval() kullanımı", re.compile(r"(?<![\w.])eval\s*\("), "execution"),
    ("exec() kullanımı", re.compile(r"(?<![\w.])exec\s*\("), "execution"),
    ("Windows registry değişikliği", re.compile(r"reg(?:\.exe)?\s+add\b|Set-ItemProperty\s+[^\n]*HKLM|winreg\.", re.IGNORECASE), "execution"),
    ("Zamanlanmış görev oluşturma", re.compile(r"schtasks|New-ScheduledTask|crontab\s+-e|@reboot\b", re.IGNORECASE), "execution"),
    ("Başlangıç (startup) klasörüne yazma", re.compile(r"\\Startup\\|/\.config/autostart|Start Menu\\Programs\\Startup", re.IGNORECASE), "execution"),
    ("Dosya silme / sistem klasörüne yazma", re.compile(r"rm\s+-rf\s+/(?!\S)|del\s+/[sf]\s|Remove-Item\s+[^\n]*-Recurse[^\n]*-Force|C:\\\\Windows\\\\System32|/etc/passwd", re.IGNORECASE), "execution"),
    ("Kimlik bilgisi/token erişimi", re.compile(
        r"AWS_SECRET_ACCESS_KEY|\.aws[\\/]credentials|\.ssh[\\/]id_rsa|"
        r"GITHUB_TOKEN|process\.env\.\w*TOKEN|os\.environ\[.?['\"]?\w*(TOKEN|SECRET|PASSWORD)|\.npmrc",
        re.IGNORECASE,
    ), "dependency"),
)

# package.json "scripts" alanındaki bu anahtarlar, bağımlılık kurulumu
# SIRASINDA otomatik çalışacağı için özellikle risklidir (klasik
# tedarik-zinciri saldırı vektörü) — regex değil, yapısal (JSON) kontrol.
LIFECYCLE_SCRIPT_KEYS = ("preinstall", "postinstall", "prepare")

LICENSE_FILENAMES = (
    "LICENSE", "LICENSE.md", "LICENSE.txt", "LICENSE.rst",
    "COPYING", "COPYING.md", "UNLICENSE",
)
