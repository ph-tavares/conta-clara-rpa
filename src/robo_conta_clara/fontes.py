"""Fontes externas: bandeira e tarifa (dados abertos ANEEL) e previsao de temperatura (Open-Meteo)."""
import json
import logging
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

from .http import ClienteHttp, FalhaHttp

log = logging.getLogger("robo.fontes")


class DadoInvalido(Exception):
    """A fonte respondeu, mas o conteudo nao serve (vazio, campo faltando, numero ilegivel)."""


def numero_br(texto) -> float:
    """'18,85' -> 18.85 ; ',00' -> 0.0 ; '1.234,5' -> 1234.5"""
    if texto is None or str(texto).strip() == "":
        raise DadoInvalido("valor numerico vazio")
    t = str(texto).strip().replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError as e:
        raise DadoInvalido(f"numero ilegivel: {texto!r}") from e


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


def chave_bandeira(nome_aneel: str) -> str:
    """Converte o nome da ANEEL para a chave usada pelo MVP (verde, amarela, vermelha1, vermelha2)."""
    n = _sem_acento(nome_aneel).replace("-", " ")
    if "verde" in n:
        return "verde"
    if "amarela" in n:
        return "amarela"
    if "vermelha" in n:
        if "2" in n:
            return "vermelha2"
        if "1" in n:
            return "vermelha1"
    if "escassez" in n:
        return "escassez_hidrica"
    return "desconhecida"


@dataclass
class Bandeira:
    competencia: str            # AAAA-MM
    nome_aneel: str
    chave: str
    adicional_rs_mwh: float
    provisoria: bool            # True se a ANEEL ainda nao publicou o mes pedido e usamos o ultimo publicado
    fonte: str = "ANEEL - Bandeira Tarifaria - Acionamento"

    @property
    def adicional_100kwh(self) -> float:
        return round(self.adicional_rs_mwh / 10, 3)  # R$/MWh -> R$ por 100 kWh


@dataclass
class Tarifa:
    distribuidora: str
    resolucao: str
    inicio_vigencia: str
    fim_vigencia: str
    tusd_rs_mwh: float
    te_rs_mwh: float
    fonte: str = "ANEEL - Tarifas Homologadas das Distribuidoras"

    @property
    def sem_tributos_kwh(self) -> float:
        return round((self.tusd_rs_mwh + self.te_rs_mwh) / 1000, 5)


@dataclass
class Clima:
    dias_previstos: int
    dias_quentes: int
    maxima_c: float
    onda_de_calor: bool


def buscar_bandeira(http: ClienteHttp, cfg: dict, competencia: str) -> Bandeira:
    a = cfg["aneel"]
    dados = http.get_json(a["url_datastore"], {
        "resource_id": a["recurso_bandeira_acionamento"], "sort": "DatCompetencia desc", "limit": 24,
    }, rotulo="ANEEL bandeira")
    registros = (dados.get("result") or {}).get("records") or []
    if not dados.get("success") or not registros:
        raise DadoInvalido("ANEEL bandeira: resposta sem registros")
    alvo = f"{competencia}-01"
    escolhido = next((r for r in registros if r.get("DatCompetencia") == alvo), None)
    provisoria = escolhido is None
    if provisoria:
        # Regra: a ANEEL divulga a bandeira no fim do mes anterior. Se ainda nao saiu, usa a mais recente e marca.
        anteriores = [r for r in registros if (r.get("DatCompetencia") or "") < alvo]
        if not anteriores:
            raise DadoInvalido(f"ANEEL bandeira: nada publicado ate {competencia}")
        escolhido = max(anteriores, key=lambda r: r["DatCompetencia"])
        log.warning("bandeira de %s ainda nao publicada; usando a de %s (provisoria)",
                    competencia, escolhido["DatCompetencia"][:7])
    nome = (escolhido.get("NomBandeiraAcionada") or "").strip()
    if not nome:
        raise DadoInvalido("ANEEL bandeira: nome da bandeira vazio")
    return Bandeira(competencia=competencia, nome_aneel=nome, chave=chave_bandeira(nome),
                    adicional_rs_mwh=numero_br(escolhido.get("VlrAdicionalBandeira")), provisoria=provisoria)


def buscar_tarifa(http: ClienteHttp, cfg: dict, competencia: str) -> Tarifa:
    a = cfg["aneel"]
    filtros = {"SigAgente": a["distribuidora"], **a["filtro_tarifa"]}
    dados = http.get_json(a["url_datastore"], {
        "resource_id": a["recurso_tarifas_homologadas"], "filters": json.dumps(filtros, ensure_ascii=False),
        "sort": "DatInicioVigencia desc", "limit": 10,
    }, rotulo="ANEEL tarifa")
    registros = (dados.get("result") or {}).get("records") or []
    if not dados.get("success") or not registros:
        raise DadoInvalido(f"ANEEL tarifa: nenhuma tarifa B1 residencial para {a['distribuidora']}")
    dia = f"{competencia}-01"
    vigentes = [r for r in registros
                if r.get("DatInicioVigencia", "9999") <= dia <= (r.get("DatFimVigencia") or "9999-12-31")
                and r.get("DscUnidadeTerciaria") == "MWh"]
    if not vigentes:
        raise DadoInvalido(f"ANEEL tarifa: nenhuma tarifa vigente em {dia}")
    r = max(vigentes, key=lambda x: x["DatInicioVigencia"])
    tarifa = Tarifa(distribuidora=a["distribuidora"], resolucao=(r.get("DscREH") or "").strip(),
                    inicio_vigencia=r["DatInicioVigencia"], fim_vigencia=r.get("DatFimVigencia") or "",
                    tusd_rs_mwh=numero_br(r.get("VlrTUSD")), te_rs_mwh=numero_br(r.get("VlrTE")))
    if not 0.2 <= tarifa.sem_tributos_kwh <= 3.0:  # trava de sanidade: valor fora disso e erro de dado
        raise DadoInvalido(f"ANEEL tarifa: valor fora do esperado ({tarifa.sem_tributos_kwh} R$/kWh)")
    return tarifa


def buscar_clima(http: ClienteHttp, cfg: dict) -> Clima:
    c = cfg["clima"]
    dados = http.get_json(c["url"], {
        "latitude": c["latitude"], "longitude": c["longitude"], "daily": "temperature_2m_max",
        "timezone": "America/Sao_Paulo", "forecast_days": 7,
    }, rotulo="Open-Meteo")
    maximas = [t for t in (dados.get("daily") or {}).get("temperature_2m_max") or [] if t is not None]
    if not maximas:
        raise DadoInvalido("Open-Meteo: previsao sem temperaturas")
    quentes = sum(1 for t in maximas if t >= c["temperatura_calor_c"])
    return Clima(dias_previstos=len(maximas), dias_quentes=quentes, maxima_c=max(maximas),
                 onda_de_calor=quentes >= c["dias_calor_para_alerta"])


# ---------------- cache da ultima coleta boa da ANEEL (resiliencia) ----------------

def salvar_cache(caminho: Path, bandeira: Bandeira, tarifa: Tarifa, agora: datetime) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps({"salvo_em": agora.isoformat(), "bandeira": asdict(bandeira),
                                   "tarifa": asdict(tarifa)}, ensure_ascii=False, indent=2), encoding="utf-8")


def ler_cache(caminho: Path, hoje: date, validade_dias: int) -> tuple[Bandeira, Tarifa, int]:
    if not caminho.exists():
        raise DadoInvalido("sem cache local da ANEEL")
    try:
        d = json.loads(caminho.read_text(encoding="utf-8"))
        idade = (hoje - datetime.fromisoformat(d["salvo_em"]).date()).days
        bandeira, tarifa = Bandeira(**d["bandeira"]), Tarifa(**d["tarifa"])
    except (ValueError, KeyError, TypeError) as e:
        raise DadoInvalido(f"cache da ANEEL corrompido ({e})") from e
    if idade > validade_dias:
        raise DadoInvalido(f"cache da ANEEL vencido ({idade} dias; limite {validade_dias})")
    return bandeira, tarifa, idade


__all__ = ["Bandeira", "Tarifa", "Clima", "DadoInvalido", "FalhaHttp", "buscar_bandeira", "buscar_tarifa",
           "buscar_clima", "salvar_cache", "ler_cache", "numero_br", "chave_bandeira"]
