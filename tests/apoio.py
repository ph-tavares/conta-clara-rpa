"""Dublês de teste: um cliente HTTP falso que responde como a ANEEL, o Open-Meteo, o MVP e o ntfy."""
import json
import os
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

os.environ.setdefault("ROBO_SEM_CONSOLE", "1")  # os logs de cada cenario vao para o arquivo da pasta temporaria
RAIZ = Path(__file__).resolve().parent.parent
assert (RAIZ / "src" / "robo_conta_clara").is_dir(), f"pacote do robo nao encontrado em {RAIZ / 'src'}"
sys.path.insert(0, str(RAIZ / "src"))

from robo_conta_clara.http import ClienteHttp, FalhaHttp  # noqa: E402

HOJE = date.today()
COMPETENCIA = HOJE.strftime("%Y-%m")


class HttpFalso(ClienteHttp):
    """Roteia pela URL. Cada fonte pode ser trocada por uma excecao para simular indisponibilidade."""

    def __init__(self, bandeira="Verde", adicional=",00", tusd="472,42", te="316,96", maximas=None,
                 mvp_config=None, leituras_mvp=None, fora=()):
        super().__init__(timeout_s=1, tentativas=1, espera_inicial_s=0, dormir=lambda s: None)
        self.bandeira, self.adicional, self.tusd, self.te = bandeira, adicional, tusd, te
        self.maximas = maximas if maximas is not None else [28, 29, 30, 27, 26, 29, 30]
        self.mvp_config = mvp_config or {"version": "abc1234", "tarifa_kwh": 0.92, "bandeira": "amarela",
                                         "adicional_bandeira_100kwh": 1.885}
        self.leituras_mvp = leituras_mvp if leituras_mvp is not None else {
            "demonstracao": [{"data": "2026-10-13", "kwh": 48210}, {"data": "2026-11-10", "kwh": 48371}]}
        self.fora = set(fora)
        self.chamadas: list[str] = []
        self.push: list[str] = []

    def get_json(self, url, params=None, headers=None, rotulo=""):
        self.chamadas.append(rotulo)
        if "invalid" in url:
            raise FalhaHttp(f"{rotulo}: URLError (nome nao resolvido)")
        if "dadosabertos.aneel" in url:
            if "aneel" in self.fora:
                raise FalhaHttp(f"{rotulo}: HTTP 503", 503)
            if "bandeira" in rotulo:
                return {"success": True, "result": {"records": [
                    {"DatCompetencia": f"{COMPETENCIA}-01", "NomBandeiraAcionada": self.bandeira,
                     "VlrAdicionalBandeira": self.adicional},
                    {"DatCompetencia": "2020-01-01", "NomBandeiraAcionada": "Amarela", "VlrAdicionalBandeira": "18,85"}]}}
            return {"success": True, "result": {"records": [
                {"DscREH": "RESOLUCAO HOMOLOGATORIA TESTE", "DatInicioVigencia": "2020-01-01",
                 "DatFimVigencia": "2099-12-31", "DscUnidadeTerciaria": "MWh", "VlrTUSD": self.tusd, "VlrTE": self.te}]}}
        if "open-meteo" in url:
            if "clima" in self.fora:
                raise FalhaHttp(f"{rotulo}: timeout")
            return {"daily": {"temperature_2m_max": self.maximas}}
        if url.endswith("/api/config"):
            if "mvp" in self.fora:
                raise FalhaHttp(f"{rotulo}: HTTP 503", 503)
            return self.mvp_config
        if url.endswith("/api/leituras"):
            if "mvp" in self.fora:
                raise FalhaHttp(f"{rotulo}: HTTP 503", 503)
            codigo = (headers or {}).get("X-Codigo-Casa")
            if codigo not in self.leituras_mvp:
                raise FalhaHttp(f"{rotulo}: HTTP 401", 401)
            return {"leituras": self.leituras_mvp[codigo]}
        raise AssertionError(f"URL inesperada no teste: {url}")

    def post_texto(self, url, corpo, headers=None, rotulo=""):
        if "ntfy" in self.fora:
            raise FalhaHttp("ntfy: HTTP 502", 502)
        self.push.append(corpo)
        return "{}"


def pasta_temporaria(casas_mvp: str | None = None, mutirao: str | None = None) -> Path:
    """Base isolada para o teste: config real do projeto + entradas do proprio teste."""
    base = Path(tempfile.mkdtemp(prefix="robo-teste-"))
    shutil.copytree(RAIZ / "config", base / "config")
    (base / "entrada").mkdir()
    if casas_mvp is not None:
        (base / "entrada" / "casas_mvp.csv").write_text(casas_mvp, encoding="utf-8")
    if mutirao is not None:
        (base / "entrada" / "mutirao.csv").write_text(mutirao, encoding="utf-8")
    return base


def ler_json(caminho: Path):
    return json.loads(caminho.read_text(encoding="utf-8"))
