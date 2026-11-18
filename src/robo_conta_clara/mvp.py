"""Integracao com o MVP Conta Clara (API publica no Azure App Service)."""
import logging
import shutil
import subprocess
import time
from datetime import date

from .http import ClienteHttp, FalhaHttp

log = logging.getLogger("robo.mvp")


class ClienteMvp:
    def __init__(self, http: ClienteHttp, url_base: str):
        self.http = http
        self.url_base = url_base.rstrip("/")

    def config(self) -> dict:
        return self.http.get_json(f"{self.url_base}/api/config", rotulo="MVP /api/config")

    def leituras(self, codigo_casa: str) -> list[tuple[date, int]]:
        # Codigo da casa vai no cabecalho (como no MVP), nunca na URL nem no log.
        dados = self.http.get_json(f"{self.url_base}/api/leituras", headers={"X-Codigo-Casa": codigo_casa},
                                   rotulo="MVP /api/leituras")
        return [(date.fromisoformat(l["data"]), int(l["kwh"])) for l in dados.get("leituras", [])]


def publicar_no_app_service(cfg: dict, tarifa_kwh: float, bandeira: str, cliente: ClienteMvp,
                            espera_max_s: int = 240, executar=subprocess.run, dormir=time.sleep) -> dict:
    """Grava TARIFA_KWH e BANDEIRA nas configuracoes do web app (az CLI) e confirma lendo /api/config.

    Requer `az login` feito antes, numa conta com permissao no web app. O App Service reinicia o
    container ao mudar app settings; por isso a confirmacao espera ate o MVP responder os valores novos.
    """
    az = shutil.which("az") or shutil.which("az.cmd")
    if not az:
        raise RuntimeError("Azure CLI (az) nao encontrado; publique manualmente com o arquivo .env gerado")
    m = cfg["mvp"]
    comando = [az, "webapp", "config", "appsettings", "set", "--resource-group", m["resource_group"],
               "--name", m["web_app"], "--settings", f"TARIFA_KWH={tarifa_kwh}", f"BANDEIRA={bandeira}",
               "--output", "none"]
    log.info("publicando no App Service %s: TARIFA_KWH=%s BANDEIRA=%s", m["web_app"], tarifa_kwh, bandeira)
    r = executar(comando, capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        # stderr do az pode trazer IDs da assinatura: registra so a primeira linha
        raise RuntimeError(f"az falhou (codigo {r.returncode}): {(r.stderr or '').strip().splitlines()[:1]}")
    inicio = time.monotonic()
    while time.monotonic() - inicio < espera_max_s:
        try:
            atual = cliente.config()
            if abs(float(atual.get("tarifa_kwh", -1)) - tarifa_kwh) < 1e-6 and atual.get("bandeira") == bandeira:
                log.info("MVP confirmou os valores novos em /api/config")
                return atual
        except FalhaHttp as e:
            log.info("MVP reiniciando (%s); aguardando", e)
        dormir(15)
    raise RuntimeError("MVP nao mostrou os valores novos em /api/config dentro do tempo limite")
