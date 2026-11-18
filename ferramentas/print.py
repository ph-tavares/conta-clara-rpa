"""Gera prints (PNG) para o relatorio sem precisar tirar captura de tela a mao.

  python print.py texto saida_do_comando.txt docs/evidencias/01-compose-ps.png "Titulo do print"
  python print.py url https://exemplo.com docs/evidencias/13-mvp-url-publica.png [largura] [altura]

Usa o Edge (ou Chrome) em modo headless. So biblioteca padrao do Python.
"""
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CANDIDATOS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def navegador() -> str:
    for c in CANDIDATOS:
        if os.path.exists(c):
            return c
    for nome in ("msedge", "microsoft-edge", "google-chrome", "chromium", "chrome"):
        if shutil.which(nome):
            return shutil.which(nome)
    sys.exit("Edge/Chrome nao encontrado: instale um dos dois ou ajuste CANDIDATOS em print.py")


def capturar(url: str, saida: Path, largura: int, altura: int) -> None:
    saida.parent.mkdir(parents=True, exist_ok=True)
    for tentativa in (1, 2, 3):  # o headless as vezes trava se a pagina ainda nao subiu: tenta de novo
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as perfil:  # perfil isolado: sem cookies do usuario
            try:
                subprocess.run([navegador(), "--headless=new", "--hide-scrollbars", "--no-first-run",
                                f"--user-data-dir={perfil}", f"--window-size={largura},{altura}",
                                "--virtual-time-budget=10000", f"--screenshot={saida.resolve()}", url],
                               check=True, capture_output=True, timeout=60)
                break
            except subprocess.TimeoutExpired:
                print(f"tentativa {tentativa}: navegador nao respondeu em 60 s")
    else:
        sys.exit(f"print nao gerado: {saida}")
    if not saida.exists() or saida.stat().st_size == 0:
        sys.exit(f"print nao gerado: {saida}")
    print(f"ok: {saida}")


def texto(arquivo: str, saida: Path, titulo: str) -> None:
    conteudo = ANSI.sub("", Path(arquivo).read_text(encoding="utf-8", errors="replace")).rstrip()
    linhas = conteudo.splitlines() or [""]
    largura = max(900, min(1800, 40 + 8 * max(len(l) for l in linhas)))
    altura = 90 + 18 * len(linhas)
    pagina = f"""<!doctype html><meta charset="utf-8"><style>
body{{margin:0;background:#1e1e1e;color:#d4d4d4;font:13px/18px Consolas,'Cascadia Mono',monospace}}
.t{{background:#323233;color:#ccc;padding:8px 14px;font:13px 'Segoe UI',sans-serif}}
pre{{margin:0;padding:12px 14px;white-space:pre}}</style>
<div class="t">{html.escape(titulo)}</div><pre>{html.escape(conteudo)}</pre>"""
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(pagina)
    try:
        capturar(Path(f.name).resolve().as_uri(), saida, largura, altura)
    finally:
        os.unlink(f.name)


if __name__ == "__main__":
    if len(sys.argv) >= 5 and sys.argv[1] == "texto":
        texto(sys.argv[2], Path(sys.argv[3]), sys.argv[4])
    elif len(sys.argv) >= 4 and sys.argv[1] == "url":
        w = int(sys.argv[4]) if len(sys.argv) > 4 else 1400
        h = int(sys.argv[5]) if len(sys.argv) > 5 else 900
        capturar(sys.argv[2], Path(sys.argv[3]), w, h)
    else:
        sys.exit(__doc__)
