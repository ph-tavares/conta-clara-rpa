"""Logs legiveis + trilha de auditoria em JSON Lines, sem dados sensiveis."""
import hashlib
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BRT = timezone(timedelta(hours=-3), "BRT")  # Brasil sem horario de verao desde 2019 (evita depender de tzdata no Windows)


def agora() -> datetime:
    return datetime.now(BRT)


def mascarar_codigo(codigo: str) -> str:
    """Identifica a casa no log sem revelar o codigo (que funciona como senha da casa no MVP)."""
    return "cod#" + hashlib.sha256(codigo.encode()).hexdigest()[:8]


_SEGREDOS = [re.compile(p) for p in (r"(?i)(x-codigo-casa[\"']?\s*[:=]\s*)[^\s,}]+",
                                     r"(?i)(bearer\s+)[a-z0-9._-]+",
                                     r"(https://ntfy\.sh/)[\w-]+")]


class FiltroSegredos(logging.Filter):
    """Ultima barreira: mesmo que alguem logue um cabecalho ou URL por engano, o valor sai mascarado."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for p in _SEGREDOS:
            msg = p.sub(r"\1***", msg)
        record.msg, record.args = msg, None
        return True


def configurar_logs(pasta: Path, run_id: str, nivel=logging.INFO) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / f"robo-{run_id}.log"
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)-13s | %(message)s", "%Y-%m-%d %H:%M:%S")
    fmt.converter = lambda *a: agora().timetuple()
    raiz = logging.getLogger()
    for h in list(raiz.handlers):  # nova execucao no mesmo processo (testes): fecha os arquivos da anterior
        h.close()
        raiz.removeHandler(h)
    raiz.setLevel(nivel)
    destinos: list[logging.Handler] = [logging.FileHandler(arquivo, encoding="utf-8")]
    if os.getenv("ROBO_SEM_CONSOLE") != "1":
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        destinos.append(logging.StreamHandler(sys.stdout))
    for h in destinos:
        h.setFormatter(fmt)
        h.addFilter(FiltroSegredos())
        raiz.addHandler(h)
    return arquivo


class Auditoria:
    """Cada evento vira uma linha JSON em logs/auditoria.jsonl (facil de filtrar e de carregar em BI)."""

    def __init__(self, arquivo: Path, run_id: str):
        self.arquivo = arquivo
        self.run_id = run_id
        arquivo.parent.mkdir(parents=True, exist_ok=True)

    def evento(self, etapa: str, resultado: str, **dados) -> None:
        linha = {"ts": agora().isoformat(timespec="seconds"), "run_id": self.run_id, "etapa": etapa,
                 "resultado": resultado, **dados}
        with self.arquivo.open("a", encoding="utf-8") as f:
            f.write(json.dumps(linha, ensure_ascii=False) + "\n")
