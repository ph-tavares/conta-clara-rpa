"""Envio de alertas (push pelo ntfy.sh, opcional) com protecao contra envio duplicado."""
import json
import logging
from pathlib import Path

from .http import ClienteHttp, FalhaHttp

log = logging.getLogger("robo.alertas")


class Notificador:
    """Se NTFY_URL nao estiver definida, os alertas ficam so no arquivo alertas.json (modo simulacao)."""

    def __init__(self, http: ClienteHttp, ntfy_url: str | None, arquivo_estado: Path):
        self.http = http
        self.ntfy_url = ntfy_url
        self.arquivo_estado = arquivo_estado
        self.enviados: set[str] = set()
        if arquivo_estado.exists():
            try:
                self.enviados = set(json.loads(arquivo_estado.read_text(encoding="utf-8")))
            except ValueError:
                log.warning("estado de alertas ilegivel; sera recriado")

    def enviar(self, chave: str, titulo: str, mensagem: str, prioridade: str = "default") -> str:
        """Retorna: enviado | simulado | ja_enviado | falhou."""
        registro = chave if self.ntfy_url else f"simulado:{chave}"  # simulacao nao bloqueia o envio real depois
        if registro in self.enviados:
            log.info("alerta %s ja enviado nesta competencia; nao reenviado", chave)
            return "ja_enviado"
        if not self.ntfy_url:
            situacao = "simulado"
        else:
            try:
                self.http.post_texto(self.ntfy_url, mensagem, rotulo="ntfy",
                                     headers={"Title": titulo.encode("ascii", "ignore").decode(),
                                              "Priority": prioridade, "Tags": "zap"})
                situacao = "enviado"
            except FalhaHttp as e:
                log.error("falha ao enviar alerta %s: %s (fica pendente para a proxima execucao)", chave, e)
                return "falhou"
        self.enviados.add(registro)
        self.arquivo_estado.parent.mkdir(parents=True, exist_ok=True)
        self.arquivo_estado.write_text(json.dumps(sorted(self.enviados), indent=1), encoding="utf-8")
        return situacao
