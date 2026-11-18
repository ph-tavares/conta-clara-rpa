"""Cliente HTTP com tempo limite e novas tentativas (biblioteca padrao, sem dependencias)."""
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("robo.http")
USER_AGENT = "conta-clara-rpa/1.0 (+robo academico FIAP GS 2026.2)"


class FalhaHttp(Exception):
    """Erro de rede ou resposta HTTP inesperada, ja depois de todas as tentativas."""

    def __init__(self, mensagem: str, status: int | None = None):
        super().__init__(mensagem)
        self.status = status


class ClienteHttp:
    def __init__(self, timeout_s: float = 30, tentativas: int = 3, espera_inicial_s: float = 2, dormir=time.sleep):
        self.timeout_s = timeout_s
        self.tentativas = tentativas
        self.espera_inicial_s = espera_inicial_s
        self.dormir = dormir

    def get_json(self, url: str, params: dict | None = None, headers: dict | None = None, rotulo: str = "") -> dict:
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        cabecalhos = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
        return json.loads(self._executar(urllib.request.Request(url, headers=cabecalhos), rotulo or url))

    def post_texto(self, url: str, corpo: str, headers: dict | None = None, rotulo: str = "") -> str:
        req = urllib.request.Request(url, data=corpo.encode("utf-8"), method="POST",
                                     headers={"User-Agent": USER_AGENT, **(headers or {})})
        return self._executar(req, rotulo or url)

    def _executar(self, req: urllib.request.Request, rotulo: str) -> str:
        espera = self.espera_inicial_s
        ultimo_erro: FalhaHttp | None = None
        for tentativa in range(1, self.tentativas + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    return resp.read().decode("utf-8")
            except urllib.error.HTTPError as e:
                ultimo_erro = FalhaHttp(f"{rotulo}: HTTP {e.code}", status=e.code)
                if 400 <= e.code < 500 and e.code != 429:
                    raise ultimo_erro  # erro do pedido (ex.: 401): repetir nao resolve
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                motivo = getattr(e, "reason", e)
                ultimo_erro = FalhaHttp(f"{rotulo}: {type(e).__name__} ({motivo})")
            except json.JSONDecodeError as e:
                ultimo_erro = FalhaHttp(f"{rotulo}: resposta nao e JSON ({e})")
            if tentativa < self.tentativas:
                log.warning("tentativa %d/%d falhou (%s); nova tentativa em %.0f s",
                            tentativa, self.tentativas, ultimo_erro, espera)
                self.dormir(espera)
                espera *= 2
        log.error("desistindo depois de %d tentativas: %s", self.tentativas, ultimo_erro)
        raise ultimo_erro
