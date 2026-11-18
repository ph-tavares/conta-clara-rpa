"""Regras de negocio: tarifa com tributos, estimativa do mes e decisao de alerta."""
from dataclasses import dataclass
from datetime import date

# Status possiveis de cada casa no lote
OK = "OK"
ATENCAO_CALOR = "ATENCAO_CALOR"          # perto do limite e com onda de calor prevista
ACIMA_DO_LIMITE = "ACIMA_DO_LIMITE"
DADOS_INSUFICIENTES = "DADOS_INSUFICIENTES"
FALHA = "FALHA"
STATUS_COM_ALERTA = {ATENCAO_CALOR, ACIMA_DO_LIMITE}


def aliquota_icms(kwh_mes: float, faixas: list[dict]) -> float:
    for f in faixas:
        if f["ate_kwh"] is None or kwh_mes <= f["ate_kwh"]:
            return f["aliquota"]
    return faixas[-1]["aliquota"]


def tarifa_com_tributos(sem_tributos_kwh: float, kwh_mes: float, tributos: dict) -> float:
    """Calculo 'por dentro' (como na fatura): tarifa / (1 - ICMS - PIS/COFINS)."""
    total = aliquota_icms(kwh_mes, tributos["icms_faixas"]) + tributos["pis_cofins"]
    return round(sem_tributos_kwh / (1 - total), 4)


def valor_conta(kwh: float, tarifa_kwh: float, adicional_100kwh: float) -> float:
    """Mesma formula do MVP (estimar_reais em app/main.py)."""
    return round(kwh * tarifa_kwh + kwh / 100 * adicional_100kwh, 2)


@dataclass
class Consumo:
    diario_kwh: float
    projecao_30d_kwh: float
    dias_observados: int


def consumo(leituras: list[tuple[date, int]]) -> Consumo | None:
    """Consumo medio entre a primeira e a ultima leitura (mesma regra do MVP)."""
    if len(leituras) < 2:
        return None
    (d0, k0), (d1, k1) = leituras[0], leituras[-1]
    dias = (d1 - d0).days
    if dias <= 0:
        return None
    diario = (k1 - k0) / dias
    return Consumo(round(diario, 2), round(diario * 30, 1), dias)


def decidir(valor_estimado: float, limite: float, onda_de_calor: bool, fator_calor: float) -> str:
    if valor_estimado > limite:
        return ACIMA_DO_LIMITE
    if onda_de_calor and valor_estimado >= limite * fator_calor:
        return ATENCAO_CALOR
    return OK


def mensagem_alerta(apelido: str, status: str, valor: float, limite: float, bandeira: str, competencia: str) -> str:
    if status == ACIMA_DO_LIMITE:
        return (f"{apelido}: conta estimada de {competencia} em R$ {valor:.2f}, acima do limite de R$ {limite:.2f} "
                f"(bandeira {bandeira}). Sugestao: anotar nova leitura e rever aparelhos de maior consumo.")
    return (f"{apelido}: conta estimada de {competencia} em R$ {valor:.2f}, perto do limite de R$ {limite:.2f}, "
            f"e ha onda de calor prevista. Atencao ao uso de ventilador e chuveiro.")
