"""Leitura e validacao das entradas do lote.

Duas origens de casas:
  * casas cadastradas no MVP (arquivo com apelido + codigo da casa; as leituras vem da API do MVP);
  * planilha do mutirao do CRAS (leituras anotadas pelos agentes para familias sem celular).
Nenhum nome, CPF ou endereco: so um identificador pseudonimo (ex.: CASA-001).
"""
import csv
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

log = logging.getLogger("robo.entrada")

ID_CASA = re.compile(r"^CASA-\d{3,6}$")
COLUNAS_MUTIRAO = {"id_casa", "data_leitura", "kwh_medidor", "limite_reais"}
COLUNAS_MVP = {"apelido", "codigo_casa", "limite_reais"}


class ArquivoInvalido(Exception):
    pass


@dataclass
class Casa:
    apelido: str
    origem: str                       # "mvp" ou "mutirao"
    limite_reais: float
    codigo: str | None = None         # so para casas do MVP; NUNCA vai para log ou saida
    leituras: list[tuple[date, int]] = field(default_factory=list)


@dataclass
class Rejeicao:
    arquivo: str
    linha: int
    id_casa: str
    motivo: str


def _abrir_csv(caminho: Path, obrigatorias: set[str]) -> list[dict]:
    if not caminho.exists():
        raise ArquivoInvalido(f"arquivo nao encontrado: {caminho.name}")
    try:
        texto = caminho.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as e:
        raise ArquivoInvalido(f"{caminho.name}: codificacao invalida (salve como UTF-8)") from e
    linhas = [l for l in texto.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    if not linhas:
        raise ArquivoInvalido(f"{caminho.name}: arquivo vazio")
    separador = ";" if linhas[0].count(";") > linhas[0].count(",") else ","  # Excel em PT-BR salva com ';'
    leitor = csv.DictReader(linhas, delimiter=separador)
    faltando = obrigatorias - {c.strip() for c in (leitor.fieldnames or [])}
    if faltando:
        raise ArquivoInvalido(f"{caminho.name}: colunas obrigatorias ausentes: {', '.join(sorted(faltando))}")
    return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in leitor]


def _limite(texto: str, padrao: float) -> float:
    if not texto:
        return padrao
    valor = float(texto.replace(",", "."))
    if not 10 <= valor <= 5000:
        raise ValueError("limite fora de 10 a 5000 reais")
    return valor


def ler_casas_mvp(caminho: Path, limite_padrao: float) -> tuple[list[Casa], list[Rejeicao]]:
    casas, rejeitadas, vistos = [], [], set()
    for n, row in enumerate(_abrir_csv(caminho, COLUNAS_MVP), start=2):
        apelido, codigo = row["apelido"], row["codigo_casa"]
        try:
            if not apelido or not codigo:
                raise ValueError("apelido ou codigo vazio")
            if apelido in vistos:
                raise ValueError("apelido duplicado")
            casas.append(Casa(apelido=apelido, origem="mvp", codigo=codigo,
                              limite_reais=_limite(row["limite_reais"], limite_padrao)))
            vistos.add(apelido)
        except ValueError as e:
            rejeitadas.append(Rejeicao(caminho.name, n, apelido or "?", str(e)))
    return casas, rejeitadas


def ler_mutirao(caminho: Path, limite_padrao: float, hoje: date) -> tuple[list[Casa], list[Rejeicao]]:
    """Valida linha a linha; problemas viram rejeicoes registradas (nada e descartado em silencio)."""
    rejeitadas: list[Rejeicao] = []
    por_casa: dict[str, dict[date, tuple[int, int]]] = {}
    limites: dict[str, float] = {}
    conflitos: set[tuple[str, date]] = set()

    for n, row in enumerate(_abrir_csv(caminho, COLUNAS_MUTIRAO), start=2):
        id_casa = row["id_casa"].upper()
        try:
            if not ID_CASA.match(id_casa):
                raise ValueError("id_casa fora do padrao CASA-000 (nao use nome ou endereco)")
            try:
                dia = date.fromisoformat(row["data_leitura"])
            except ValueError:
                raise ValueError(f"data invalida: {row['data_leitura']!r} (use AAAA-MM-DD)") from None
            if dia > hoje:
                raise ValueError("data no futuro")
            if not row["kwh_medidor"].isdigit():
                raise ValueError(f"kwh_medidor invalido: {row['kwh_medidor']!r}")
            kwh = int(row["kwh_medidor"])
            if kwh > 999_999:
                raise ValueError("kwh_medidor acima de 6 digitos")
            limites[id_casa] = _limite(row["limite_reais"], limites.get(id_casa, limite_padrao))
        except ValueError as e:
            rejeitadas.append(Rejeicao(caminho.name, n, id_casa or "?", str(e)))
            continue

        dias = por_casa.setdefault(id_casa, {})
        if dia in dias:
            kwh_antes, linha_antes = dias[dia]
            if kwh_antes == kwh:
                rejeitadas.append(Rejeicao(caminho.name, n, id_casa, f"linha duplicada (igual a linha {linha_antes}); ignorada"))
            else:
                conflitos.add((id_casa, dia))
                rejeitadas.append(Rejeicao(caminho.name, n, id_casa,
                                           f"duas leituras diferentes no mesmo dia (linha {linha_antes}: {kwh_antes}); ambas descartadas"))
            continue
        dias[dia] = (kwh, n)

    casas = []
    for id_casa, dias in sorted(por_casa.items()):
        validas: list[tuple[date, int, int]] = []  # (dia, kwh, linha)
        for dia in sorted(dias):
            kwh, n = dias[dia]
            if (id_casa, dia) in conflitos:
                continue
            # Regra do medidor: o numero so aumenta. Se cair, uma das duas leituras foi anotada errado:
            # se a nova ainda e maior que a penultima, o erro foi a anterior (um "pico"); senao, e a nova.
            if validas and kwh < validas[-1][1]:
                if len(validas) >= 2 and kwh >= validas[-2][1]:
                    d_err, k_err, n_err = validas.pop()
                    rejeitadas.append(Rejeicao(caminho.name, n_err, id_casa,
                                               f"leitura fora da sequencia do medidor ({k_err} em {d_err}, maior que {kwh} em {dia}); descartada"))
                else:
                    rejeitadas.append(Rejeicao(caminho.name, n, id_casa,
                                               f"medidor voltou ({kwh} < {validas[-1][1]} em {validas[-1][0]}); leitura descartada"))
                    continue
            validas.append((dia, kwh, n))
        casas.append(Casa(apelido=id_casa, origem="mutirao", limite_reais=limites[id_casa],
                          leituras=[(d, k) for d, k, _ in validas]))
    return casas, rejeitadas
