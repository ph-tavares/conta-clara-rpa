"""Gera docs/relatorio-rpa.pdf a partir de docs/relatorio.html, com os links do repositorio e do video.

    python ferramentas/gerar_pdf.py --video https://youtu.be/XXXX
    python ferramentas/gerar_pdf.py --video https://youtu.be/XXXX --repo https://github.com/<login>/conta-clara-rpa

Usa o Edge ou o Chrome em modo headless (os mesmos do print.py). So biblioteca padrao.
"""
import argparse
import html
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from print import navegador  # noqa: E402

DOCS = Path(__file__).resolve().parent.parent / "docs"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--video", default="", help="link do video (YouTube nao listado, Drive etc.)")
    p.add_argument("--repo", default="https://github.com/ph-tavares/conta-clara-rpa")
    a = p.parse_args()
    if a.video:
        video = f'<a href="{html.escape(a.video)}">{html.escape(a.video)}</a>'
    else:
        video = '<span class="pendente">inserir: gere de novo com ferramentas/gerar_pdf.py --video &lt;link&gt;</span>'
        print("AVISO: PDF gerado sem o link do video")
    texto = (DOCS / "relatorio.html").read_text(encoding="utf-8")
    texto = texto.replace("{{REPO}}", html.escape(a.repo.rstrip("/"))).replace("{{VIDEO_HTML}}", video)
    # arquivo temporario na propria pasta docs/ para os caminhos ../assets/ continuarem valendo
    with tempfile.NamedTemporaryFile("w", suffix=".html", dir=DOCS, delete=False, encoding="utf-8") as f:
        f.write(texto)
    saida = DOCS / "relatorio-rpa.pdf"
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as perfil:
            subprocess.run([navegador(), "--headless=new", "--no-pdf-header-footer", "--no-first-run",
                            f"--user-data-dir={perfil}", "--virtual-time-budget=5000",
                            f"--print-to-pdf={saida.resolve()}", Path(f.name).resolve().as_uri()],
                           check=True, capture_output=True, timeout=120)
    finally:
        os.unlink(f.name)
    print(f"ok: {saida}")


if __name__ == "__main__":
    main()
