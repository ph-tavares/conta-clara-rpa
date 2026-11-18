"""Orquestracao do processo mensal (ver docs/processo.bpmn)."""
import csv
import json
import logging
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import regras
from .alertas import Notificador
from .auditoria import Auditoria, agora, configurar_logs, mascarar_codigo
from .entrada import ArquivoInvalido, Casa, Rejeicao, ler_casas_mvp, ler_mutirao
from .fontes import (Bandeira, Clima, DadoInvalido, Tarifa, buscar_bandeira, buscar_clima, buscar_tarifa,
                     ler_cache, salvar_cache)
from .http import ClienteHttp, FalhaHttp
from .mvp import ClienteMvp, publicar_no_app_service

log = logging.getLogger("robo")

SUCESSO, SUCESSO_PARCIAL, FALHA_CRITICA = 0, 1, 2
NOME_SITUACAO = {SUCESSO: "SUCESSO", SUCESSO_PARCIAL: "SUCESSO_PARCIAL", FALHA_CRITICA: "FALHA_CRITICA"}


@dataclass
class Opcoes:
    base: Path
    competencia: str
    arquivo_casas_mvp: Path
    arquivo_mutirao: Path
    ntfy_url: str | None = None
    publicar_azure: bool = False
    simular_falha: str | None = None   # aneel | aneel-sem-cache | mvp | clima


@dataclass
class ResultadoCasa:
    competencia: str
    casa: str
    origem: str
    leituras_validas: int = 0
    dias_observados: int = 0
    consumo_diario_kwh: float | None = None
    projecao_30d_kwh: float | None = None
    valor_config_atual_mvp: float | None = None
    valor_estimado_reais: float | None = None
    variacao_reais: float | None = None
    limite_reais: float = 0.0
    status: str = regras.OK
    alerta: str = "nao"
    detalhe: str = ""


@dataclass
class Execucao:
    run_id: str
    competencia: str
    inicio: str
    fim: str = ""
    situacao: str = ""
    codigo_saida: int = 0
    origem_tarifa: str = ""
    avisos: list[str] = field(default_factory=list)
    erros: list[str] = field(default_factory=list)
    contagem: dict = field(default_factory=dict)
    decisao_mvp: str = ""


def executar(op: Opcoes, http: ClienteHttp | None = None) -> int:
    run_id = agora().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    pasta_logs = op.base / "logs"
    arquivo_log = configurar_logs(pasta_logs, run_id)
    aud = Auditoria(pasta_logs / "auditoria.jsonl", run_id)
    cfg = json.loads((op.base / "config" / "config.json").read_text(encoding="utf-8"))
    if http is None:
        h = cfg["http"]
        http = ClienteHttp(h["timeout_s"], h["tentativas"], h["espera_inicial_s"])

    if op.simular_falha in ("aneel", "aneel-sem-cache"):
        cfg["aneel"]["url_datastore"] = "https://aneel-fora-do-ar.invalid/api/3/action/datastore_search"
    if op.simular_falha == "mvp":
        cfg["mvp"]["url_base"] = "https://mvp-fora-do-ar.invalid"
    if op.simular_falha == "clima":
        cfg["clima"]["url"] = "https://clima-fora-do-ar.invalid/v1/forecast"

    ex = Execucao(run_id=run_id, competencia=op.competencia, inicio=agora().isoformat(timespec="seconds"))
    # Simulacoes de falha gravam em pasta separada: nunca sobrescrevem o contrato real consumido pelo MVP
    pasta_saida = op.base / "saida" / (f"simulacoes/{op.simular_falha}/" if op.simular_falha else "") / op.competencia
    pasta_saida.mkdir(parents=True, exist_ok=True)
    log.info("=== Robo Conta Clara | execucao %s | competencia %s ===", run_id, op.competencia)
    if op.simular_falha:
        log.warning("MODO DE TESTE: simulando falha em '%s'", op.simular_falha)
    aud.evento("inicio", "ok", competencia=op.competencia, simular_falha=op.simular_falha,
               publicar_azure=op.publicar_azure, alertas_push=bool(op.ntfy_url))

    # 1) Tarifa e bandeira do mes (ANEEL), com recuperacao pelo cache da ultima coleta boa
    cache = op.base / "estado" / "cache_aneel.json"
    if op.simular_falha == "aneel-sem-cache":
        cache = op.base / "estado" / "cache_inexistente.json"
    try:
        bandeira = buscar_bandeira(http, cfg, op.competencia)
        tarifa = buscar_tarifa(http, cfg, op.competencia)
        salvar_cache(cache, bandeira, tarifa, agora())
        ex.origem_tarifa = "api_aneel"
        log.info("ANEEL: bandeira %s (adicional R$ %.2f/MWh)%s | tarifa B1 %s: TUSD %.2f + TE %.2f R$/MWh (%s)",
                 bandeira.nome_aneel, bandeira.adicional_rs_mwh, " [PROVISORIA]" if bandeira.provisoria else "",
                 tarifa.distribuidora, tarifa.tusd_rs_mwh, tarifa.te_rs_mwh, tarifa.resolucao[:45])
        aud.evento("coleta_aneel", "ok", bandeira=bandeira.chave, provisoria=bandeira.provisoria,
                   tarifa_sem_tributos_kwh=tarifa.sem_tributos_kwh, resolucao=tarifa.resolucao)
        if bandeira.provisoria:
            ex.avisos.append("bandeira do mes ainda nao publicada pela ANEEL; usada a mais recente")
    except (FalhaHttp, DadoInvalido) as e:
        log.error("ANEEL indisponivel ou com dado invalido: %s", e)
        aud.evento("coleta_aneel", "falha", erro=str(e))
        try:
            bandeira, tarifa, idade = ler_cache(cache, agora().date(), cfg["aneel"]["cache_validade_dias"])
            ex.origem_tarifa = f"cache_local ({idade} dia(s))"
            ex.avisos.append(f"ANEEL fora: usado cache local de {idade} dia(s) - {e}")
            log.warning("RECUPERACAO: usando a ultima coleta valida (cache de %d dia(s)): bandeira %s, tarifa %.5f R$/kWh",
                        idade, bandeira.chave, tarifa.sem_tributos_kwh)
            aud.evento("recuperacao_cache", "ok", idade_dias=idade)
        except DadoInvalido as e2:
            ex.erros.append(f"ANEEL fora e sem cache valido: {e2}")
            log.critical("FALHA CRITICA: sem tarifa confiavel (%s). Nada sera publicado nem alertado.", e2)
            aud.evento("recuperacao_cache", "falha", erro=str(e2))
            return _encerrar(op, ex, aud, pasta_saida, arquivo_log, FALHA_CRITICA, [], [])

    # 2) Previsao de calor (opcional: falha aqui nao interrompe o processo)
    clima: Clima | None = None
    try:
        clima = buscar_clima(http, cfg)
        log.info("Open-Meteo: %d de %d dias com maxima >= %.0f C (max %.1f C) -> onda de calor: %s",
                 clima.dias_quentes, clima.dias_previstos, cfg["clima"]["temperatura_calor_c"], clima.maxima_c,
                 "SIM" if clima.onda_de_calor else "nao")
        aud.evento("coleta_clima", "ok", **asdict(clima))
    except (FalhaHttp, DadoInvalido) as e:
        ex.avisos.append(f"previsao do tempo indisponivel; regra de calor desligada nesta execucao ({e})")
        log.warning("Open-Meteo indisponivel (%s): regra de calor desligada nesta execucao", e)
        aud.evento("coleta_clima", "falha", erro=str(e))
    onda_de_calor = bool(clima and clima.onda_de_calor)

    # 3) Valores para o MVP (contrato tarifa_vigente) e decisao de atualizacao
    trib = cfg["tributos"]
    tarifa_ref = regras.tarifa_com_tributos(tarifa.sem_tributos_kwh, trib["faixa_referencia_kwh"], trib)
    bandeira_ok = bandeira.chave in cfg["regras"]["bandeiras_aceitas_pelo_mvp"]
    contrato = _contrato(op, ex, cfg, bandeira, tarifa, tarifa_ref, clima)
    _gravar_json(pasta_saida / "tarifa_vigente.json", contrato)
    (pasta_saida / "tarifa_vigente.env").write_text(f"TARIFA_KWH={tarifa_ref}\nBANDEIRA={bandeira.chave}\n", encoding="utf-8")
    if not op.simular_falha:
        shutil.copyfile(pasta_saida / "tarifa_vigente.json", op.base / "saida" / "tarifa_vigente.json")
    log.info("Contrato para o MVP gerado: TARIFA_KWH=%s BANDEIRA=%s (%s/tarifa_vigente.json)",
             tarifa_ref, bandeira.chave, pasta_saida.relative_to(op.base).as_posix())

    cliente_mvp = ClienteMvp(http, cfg["mvp"]["url_base"])
    config_mvp: dict | None = None
    try:
        config_mvp = cliente_mvp.config()
        log.info("MVP no ar (versao %s): hoje usa TARIFA_KWH=%s BANDEIRA=%s",
                 str(config_mvp.get("version"))[:7], config_mvp.get("tarifa_kwh"), config_mvp.get("bandeira"))
    except FalhaHttp as e:
        ex.avisos.append(f"MVP indisponivel para leitura da configuracao ({e})")
        log.error("MVP indisponivel (%s): sem comparacao com a configuracao atual", e)

    if not bandeira_ok:
        ex.decisao_mvp = f"NAO_PUBLICAR: bandeira '{bandeira.chave}' nao e suportada pelo MVP (revisao humana)"
        ex.erros.append(ex.decisao_mvp)
        log.error(ex.decisao_mvp)
    elif config_mvp is None:
        ex.decisao_mvp = "INDEFINIDA: MVP fora do ar; contrato gerado para publicar depois"
    elif (abs(float(config_mvp.get("tarifa_kwh", 0)) - tarifa_ref) < 1e-6 and config_mvp.get("bandeira") == bandeira.chave):
        ex.decisao_mvp = "SEM_MUDANCA: o MVP ja usa a tarifa e a bandeira do mes"
    else:
        ex.decisao_mvp = (f"ATUALIZAR: MVP usa {config_mvp.get('tarifa_kwh')}/{config_mvp.get('bandeira')}, "
                          f"o mes pede {tarifa_ref}/{bandeira.chave}")
    log.info("Decisao sobre o MVP: %s", ex.decisao_mvp)
    aud.evento("decisao_mvp", "ok", decisao=ex.decisao_mvp.split(":")[0])

    # 4) Lote de casas: entrada do MVP + planilha do mutirao
    casas: list[Casa] = []
    rejeicoes: list[Rejeicao] = []
    limite_padrao = cfg["regras"]["limite_padrao_reais"]
    for leitor, caminho in ((lambda p: ler_casas_mvp(p, limite_padrao), op.arquivo_casas_mvp),
                            (lambda p: ler_mutirao(p, limite_padrao, agora().date()), op.arquivo_mutirao)):
        try:
            c, r = leitor(caminho)
            casas += c
            rejeicoes += r
            log.info("Entrada %s: %d casa(s) valida(s), %d linha(s) rejeitada(s)", caminho.name, len(c), len(r))
            aud.evento("leitura_entrada", "ok", arquivo=caminho.name, casas=len(c), rejeitadas=len(r))
        except ArquivoInvalido as e:
            ex.erros.append(str(e))
            log.error("Entrada ignorada: %s", e)
            aud.evento("leitura_entrada", "falha", arquivo=caminho.name, erro=str(e))
    for r in rejeicoes:
        log.warning("Rejeitada %s linha %d (%s): %s", r.arquivo, r.linha, r.id_casa, r.motivo)

    notificador = Notificador(http, op.ntfy_url, op.base / "estado" / f"alertas_enviados_{op.competencia}.json")
    adicional_atual = float(config_mvp.get("adicional_bandeira_100kwh", 0)) if config_mvp else None
    tarifa_atual = float(config_mvp.get("tarifa_kwh", 0)) if config_mvp else None
    resultados: list[ResultadoCasa] = []

    for i, casa in enumerate(casas, start=1):  # estrutura de repeticao sobre a colecao de casas
        res = ResultadoCasa(op.competencia, casa.apelido, casa.origem, limite_reais=casa.limite_reais)
        ident = f"{casa.apelido} ({mascarar_codigo(casa.codigo)})" if casa.codigo else casa.apelido
        try:
            if casa.origem == "mvp":
                casa.leituras = cliente_mvp.leituras(casa.codigo)
            res.leituras_validas = len(casa.leituras)
            cons = regras.consumo(casa.leituras)
            if len(casa.leituras) < cfg["regras"]["minimo_leituras"] or cons is None:
                res.status = regras.DADOS_INSUFICIENTES
                res.detalhe = "precisa de 2 leituras em dias diferentes"
            else:
                tarifa_casa = regras.tarifa_com_tributos(tarifa.sem_tributos_kwh, cons.projecao_30d_kwh, trib)
                res.dias_observados = cons.dias_observados
                res.consumo_diario_kwh, res.projecao_30d_kwh = cons.diario_kwh, cons.projecao_30d_kwh
                res.valor_estimado_reais = regras.valor_conta(cons.projecao_30d_kwh, tarifa_casa, bandeira.adicional_100kwh)
                if tarifa_atual is not None:
                    res.valor_config_atual_mvp = regras.valor_conta(cons.projecao_30d_kwh, tarifa_atual, adicional_atual)
                    res.variacao_reais = round(res.valor_estimado_reais - res.valor_config_atual_mvp, 2)
                res.status = regras.decidir(res.valor_estimado_reais, casa.limite_reais, onda_de_calor,
                                            cfg["regras"]["fator_atencao_calor"])
                if res.status in regras.STATUS_COM_ALERTA:
                    msg = regras.mensagem_alerta(casa.apelido, res.status, res.valor_estimado_reais,
                                                 casa.limite_reais, bandeira.chave, op.competencia)
                    res.alerta = notificador.enviar(f"{op.competencia}:{casa.apelido}:{res.status}",
                                                    f"Conta Clara - {res.status}", msg,
                                                    "high" if res.status == regras.ACIMA_DO_LIMITE else "default")
                    res.detalhe = msg
        except FalhaHttp as e:
            res.status, res.detalhe = regras.FALHA, str(e)
        except (ValueError, KeyError) as e:
            res.status, res.detalhe = regras.FALHA, f"dado inesperado do MVP: {e}"
        nivel = logging.ERROR if res.status == regras.FALHA else logging.INFO
        valor = "-" if res.valor_estimado_reais is None else f"{res.valor_estimado_reais:.2f}"
        proj = "-" if res.projecao_30d_kwh is None else f"{res.projecao_30d_kwh:.1f}"
        log.log(nivel, "[%d/%d] %s | %s | proj %s kWh | R$ %s (limite %.2f) | alerta: %s%s", i, len(casas), ident,
                res.status, proj, valor, casa.limite_reais, res.alerta,
                f" | {res.detalhe}" if res.status in (regras.FALHA, regras.DADOS_INSUFICIENTES) else "")
        aud.evento("casa", res.status, casa=casa.apelido, origem=casa.origem, valor=res.valor_estimado_reais,
                   limite=casa.limite_reais, alerta=res.alerta)
        resultados.append(res)

    # 5) Publicacao opcional no App Service (integracao de escrita com o MVP)
    if op.publicar_azure and not op.simular_falha:  # simulacao nunca publica
        if ex.decisao_mvp.startswith("ATUALIZAR"):
            try:
                atual = publicar_no_app_service(cfg, tarifa_ref, bandeira.chave, cliente_mvp)
                ex.decisao_mvp += " -> PUBLICADO e confirmado em /api/config"
                aud.evento("publicacao_mvp", "ok", tarifa_kwh=atual.get("tarifa_kwh"), bandeira=atual.get("bandeira"))
            except (RuntimeError, OSError) as e:
                ex.erros.append(f"publicacao no MVP falhou: {e}")
                log.error("Publicacao no MVP falhou: %s", e)
                aud.evento("publicacao_mvp", "falha", erro=str(e))
        else:
            log.info("Publicacao no MVP nao necessaria (%s)", ex.decisao_mvp.split(":")[0])

    falhas = sum(r.status == regras.FALHA for r in resultados) + sum(r.alerta == "falhou" for r in resultados)
    codigo = SUCESSO_PARCIAL if (falhas or ex.erros or ex.origem_tarifa != "api_aneel") else SUCESSO
    return _encerrar(op, ex, aud, pasta_saida, arquivo_log, codigo, resultados, rejeicoes)


def _contrato(op, ex, cfg, bandeira: Bandeira, tarifa: Tarifa, tarifa_ref: float, clima: Clima | None) -> dict:
    trib = cfg["tributos"]
    return {
        "versao_contrato": 1,
        "competencia": op.competencia,
        "gerado_em": agora().isoformat(timespec="seconds"),
        "run_id": ex.run_id,
        "tarifa_kwh": tarifa_ref,
        "bandeira": bandeira.chave,
        "adicional_bandeira_100kwh": bandeira.adicional_100kwh,
        "bandeira_provisoria": bandeira.provisoria,
        "bandeira_suportada_pelo_mvp": bandeira.chave in cfg["regras"]["bandeiras_aceitas_pelo_mvp"],
        "origem_dados": ex.origem_tarifa,
        "detalhe": {
            "distribuidora": tarifa.distribuidora,
            "distribuidora_nome": cfg["aneel"]["distribuidora_nome_comercial"],
            "subgrupo": "B1 Residencial Convencional",
            "resolucao": tarifa.resolucao,
            "vigencia": [tarifa.inicio_vigencia, tarifa.fim_vigencia],
            "tusd_rs_mwh": tarifa.tusd_rs_mwh,
            "te_rs_mwh": tarifa.te_rs_mwh,
            "tarifa_sem_tributos_kwh": tarifa.sem_tributos_kwh,
            "tributos_aproximados": {"pis_cofins": trib["pis_cofins"],
                                     "icms": regras.aliquota_icms(trib["faixa_referencia_kwh"], trib["icms_faixas"]),
                                     "faixa_referencia_kwh": trib["faixa_referencia_kwh"]},
            "bandeira_nome_aneel": bandeira.nome_aneel,
            "bandeira_adicional_rs_mwh": bandeira.adicional_rs_mwh,
            "onda_de_calor_prevista": clima.onda_de_calor if clima else None,
        },
        "fontes": ["https://dadosabertos.aneel.gov.br/dataset/bandeiras-tarifarias",
                   "https://dadosabertos.aneel.gov.br/dataset/tarifas-distribuidoras-energia-eletrica",
                   "https://open-meteo.com/"],
    }


def _gravar_json(caminho: Path, dados) -> None:
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def _gravar_csv(caminho: Path, linhas: list[dict], colunas: list[str]) -> None:
    with caminho.open("w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: abre certo no Excel
        w = csv.DictWriter(f, fieldnames=colunas, delimiter=";")
        w.writeheader()
        w.writerows(linhas)


def _encerrar(op, ex: Execucao, aud: Auditoria, pasta: Path, arquivo_log: Path, codigo: int,
              resultados: list[ResultadoCasa], rejeicoes: list[Rejeicao]) -> int:
    ex.fim = agora().isoformat(timespec="seconds")
    ex.codigo_saida, ex.situacao = codigo, NOME_SITUACAO[codigo]
    por_status: dict[str, int] = {}
    for r in resultados:
        por_status[r.status] = por_status.get(r.status, 0) + 1
    ex.contagem = {"casas_processadas": len(resultados), "por_status": por_status,
                   "alertas": sum(r.status in regras.STATUS_COM_ALERTA for r in resultados),
                   "linhas_rejeitadas": len(rejeicoes)}
    if resultados:
        _gravar_csv(pasta / "estimativas.csv", [asdict(r) for r in resultados], list(asdict(resultados[0]).keys()))
        _gravar_json(pasta / "alertas.json", [{"casa": r.casa, "status": r.status, "valor_estimado_reais": r.valor_estimado_reais,
                                               "limite_reais": r.limite_reais, "envio": r.alerta, "mensagem": r.detalhe}
                                              for r in resultados if r.status in regras.STATUS_COM_ALERTA])
    _gravar_csv(pasta / "rejeitados.csv", [asdict(r) for r in rejeicoes], ["arquivo", "linha", "id_casa", "motivo"])
    _gravar_json(pasta / "resumo_execucao.json", {**asdict(ex), "log": f"logs/{arquivo_log.name}"})
    aud.evento("fim", ex.situacao, codigo_saida=codigo, **ex.contagem)
    log.info("=== Fim: %s (codigo %d) | %d casa(s) | por status %s | %d alerta(s) | %d linha(s) rejeitada(s) ===",
             ex.situacao, codigo, len(resultados), por_status, ex.contagem["alertas"], len(rejeicoes))
    for a in ex.avisos:
        log.warning("Aviso: %s", a)
    for e in ex.erros:
        log.error("Erro: %s", e)
    log.info("Saidas em %s/ | log em logs/%s | auditoria em logs/auditoria.jsonl",
             pasta.relative_to(op.base).as_posix(), arquivo_log.name)
    return codigo
