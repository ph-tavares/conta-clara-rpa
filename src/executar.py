"""Ponto de entrada do robo.

    python src/executar.py                       # competencia do mes atual
    python src/executar.py --competencia 2026-12
    python src/executar.py --simular-falha aneel # demonstra a recuperacao pelo cache
    python src/executar.py --publicar-azure      # grava TARIFA_KWH/BANDEIRA no MVP (requer az login)

Codigo de saida: 0 = sucesso | 1 = sucesso parcial (algo falhou e foi registrado) | 2 = falha critica.
Variavel de ambiente opcional: NTFY_URL (ex.: https://ntfy.sh/<topico-secreto>) para alertas push.
"""
import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from robo_conta_clara.auditoria import agora  # noqa: E402
from robo_conta_clara.robo import Opcoes, executar  # noqa: E402

BASE = Path(__file__).resolve().parent.parent


def competencia(valor: str) -> str:
    if not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", valor):
        raise argparse.ArgumentTypeError("use AAAA-MM, ex.: 2026-11")
    return valor


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Robo mensal do Conta Clara (tarifa, bandeira, estimativas e alertas)")
    p.add_argument("--competencia", type=competencia, default=agora().strftime("%Y-%m"))
    p.add_argument("--casas-mvp", type=Path, default=BASE / "entrada" / "casas_mvp.csv")
    p.add_argument("--mutirao", type=Path, default=BASE / "entrada" / "leituras_mutirao.csv")
    p.add_argument("--publicar-azure", action="store_true", help="atualiza TARIFA_KWH e BANDEIRA no App Service")
    p.add_argument("--simular-falha", choices=["aneel", "aneel-sem-cache", "mvp", "clima"])
    a = p.parse_args(argv)
    return executar(Opcoes(base=BASE, competencia=a.competencia, arquivo_casas_mvp=a.casas_mvp,
                           arquivo_mutirao=a.mutirao, ntfy_url=os.getenv("NTFY_URL") or None,
                           publicar_azure=a.publicar_azure, simular_falha=a.simular_falha))


if __name__ == "__main__":
    sys.exit(main())
