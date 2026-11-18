"""Testes das regras de negocio, da leitura das fontes e da validacao das entradas."""
import tempfile
import threading
import unittest
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import json

from apoio import COMPETENCIA, HttpFalso, RAIZ

from robo_conta_clara import regras
from robo_conta_clara.entrada import ArquivoInvalido, ler_casas_mvp, ler_mutirao
from robo_conta_clara.fontes import (DadoInvalido, buscar_bandeira, buscar_clima, buscar_tarifa, chave_bandeira,
                                     numero_br)
from robo_conta_clara.http import ClienteHttp, FalhaHttp

CFG = json.loads((RAIZ / "config" / "config.json").read_text(encoding="utf-8"))
TRIB = CFG["tributos"]


class TestRegras(unittest.TestCase):
    def test_formula_igual_a_do_mvp(self):
        # O MVP no ar mostra R$ 161,95 para 172,5 kWh com 0,92 + amarela: o robo calcula igual.
        self.assertEqual(regras.valor_conta(172.5, 0.92, 1.885), 161.95)

    def test_icms_por_faixa(self):
        self.assertEqual(regras.aliquota_icms(80, TRIB["icms_faixas"]), 0.0)
        self.assertEqual(regras.aliquota_icms(150, TRIB["icms_faixas"]), 0.12)
        self.assertEqual(regras.aliquota_icms(250, TRIB["icms_faixas"]), 0.18)

    def test_tarifa_com_tributos_por_dentro(self):
        self.assertEqual(regras.tarifa_com_tributos(0.78938, 150, TRIB), round(0.78938 / 0.83, 4))

    def test_consumo_precisa_de_duas_leituras_em_dias_diferentes(self):
        self.assertIsNone(regras.consumo([(date(2026, 11, 1), 100)]))
        c = regras.consumo([(date(2026, 11, 1), 100), (date(2026, 11, 11), 150)])
        self.assertEqual((c.diario_kwh, c.projecao_30d_kwh, c.dias_observados), (5.0, 150.0, 10))

    def test_decisao(self):
        self.assertEqual(regras.decidir(151, 150, False, 0.9), regras.ACIMA_DO_LIMITE)
        self.assertEqual(regras.decidir(140, 150, True, 0.9), regras.ATENCAO_CALOR)
        self.assertEqual(regras.decidir(140, 150, False, 0.9), regras.OK)
        self.assertEqual(regras.decidir(100, 150, True, 0.9), regras.OK)


class TestFontes(unittest.TestCase):
    def test_numero_brasileiro(self):
        self.assertEqual(numero_br("18,85"), 18.85)
        self.assertEqual(numero_br(",00"), 0.0)
        self.assertEqual(numero_br("1.234,50"), 1234.5)
        with self.assertRaises(DadoInvalido):
            numero_br("abc")

    def test_nome_da_bandeira_para_chave_do_mvp(self):
        casos = {"Verde": "verde", "Amarela": "amarela", "Vermelha P1": "vermelha1", "Vermelha - Patamar 2": "vermelha2",
                 "Escassez Hídrica": "escassez_hidrica"}
        for nome, chave in casos.items():
            self.assertEqual(chave_bandeira(nome), chave)

    def test_bandeira_do_mes(self):
        b = buscar_bandeira(HttpFalso(bandeira="Vermelha P1", adicional="44,63"), CFG, COMPETENCIA)
        self.assertEqual((b.chave, b.adicional_100kwh, b.provisoria), ("vermelha1", 4.463, False))

    def test_bandeira_ainda_nao_publicada_vira_provisoria(self):
        b = buscar_bandeira(HttpFalso(), CFG, "2099-01")
        self.assertTrue(b.provisoria)
        self.assertEqual(b.chave, "verde")

    def test_tarifa_vigente(self):
        t = buscar_tarifa(HttpFalso(), CFG, COMPETENCIA)
        self.assertAlmostEqual(t.sem_tributos_kwh, 0.78938)

    def test_tarifa_absurda_e_recusada(self):
        with self.assertRaises(DadoInvalido):
            buscar_tarifa(HttpFalso(tusd="47242,00"), CFG, COMPETENCIA)

    def test_onda_de_calor(self):
        self.assertTrue(buscar_clima(HttpFalso(maximas=[33, 34, 32, 29, 28, 27, 30]), CFG).onda_de_calor)
        self.assertFalse(buscar_clima(HttpFalso(maximas=[33, 29, 28, 27, 26, 25, 30]), CFG).onda_de_calor)


class _Servidor(BaseHTTPRequestHandler):
    respostas: list[int] = []

    def do_GET(self):
        codigo = self.respostas.pop(0)
        self.send_response(codigo)
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, *a):
        pass


class TestClienteHttp(unittest.TestCase):
    """Servidor HTTP local de verdade, para provar as novas tentativas sem depender da internet."""

    def setUp(self):
        self.srv = HTTPServer(("127.0.0.1", 0), _Servidor)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}/x"
        self.esperas = []
        self.http = ClienteHttp(timeout_s=5, tentativas=3, espera_inicial_s=1, dormir=self.esperas.append)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def test_recupera_depois_de_erros_5xx(self):
        _Servidor.respostas = [503, 500, 200]
        self.assertEqual(self.http.get_json(self.url), {"ok": True})
        self.assertEqual(self.esperas, [1, 2])  # espera exponencial

    def test_desiste_depois_das_tentativas(self):
        _Servidor.respostas = [503, 503, 503]
        with self.assertRaises(FalhaHttp):
            self.http.get_json(self.url)

    def test_nao_repete_erro_do_cliente(self):
        _Servidor.respostas = [401]
        with self.assertRaises(FalhaHttp) as ctx:
            self.http.get_json(self.url)
        self.assertEqual((ctx.exception.status, self.esperas), (401, []))


class TestEntrada(unittest.TestCase):
    def _arquivo(self, texto: str) -> Path:
        f = Path(tempfile.mkdtemp()) / "mutirao.csv"
        f.write_text(texto, encoding="utf-8")
        return f

    def test_mutirao_valido_com_ponto_e_virgula(self):
        f = self._arquivo("id_casa;data_leitura;kwh_medidor;limite_reais\nCASA-001;2026-10-01;100;120\nCASA-001;2026-10-11;150;\n")
        casas, rej = ler_mutirao(f, 150, date(2026, 11, 18))
        self.assertEqual((len(casas), casas[0].limite_reais, len(casas[0].leituras), rej), (1, 120.0, 2, []))

    def test_rejeicoes_registradas(self):
        f = self._arquivo("\n".join([
            "id_casa,data_leitura,kwh_medidor,limite_reais",
            "CASA-001,2026-10-01,100,120",
            "CASA-001,2026-10-01,100,",        # duplicada identica
            "CASA-002,2026-10-01,100,",
            "CASA-002,2026-10-01,130,",        # conflito no mesmo dia
            "Joao da Silva,2026-10-01,5,",     # nome no lugar do id
            "CASA-003,2026-13-01,5,",          # data invalida
            "CASA-003,2099-01-01,5,",          # futuro
            "CASA-003,2026-10-02,-5,",         # numero invalido
        ]))
        casas, rej = ler_mutirao(f, 150, date(2026, 11, 18))
        motivos = " | ".join(r.motivo for r in rej)
        for trecho in ("duplicada", "mesmo dia", "fora do padrao", "data invalida", "futuro", "kwh_medidor invalido"):
            self.assertIn(trecho, motivos)
        self.assertEqual({c.apelido: len(c.leituras) for c in casas}, {"CASA-001": 1, "CASA-002": 0})

    def test_pico_de_anotacao_e_descartado(self):
        f = self._arquivo("id_casa,data_leitura,kwh_medidor,limite_reais\n"
                          "CASA-001,2026-10-01,100,\nCASA-001,2026-10-08,190,\nCASA-001,2026-10-15,140,\n")
        casas, rej = ler_mutirao(f, 150, date(2026, 11, 18))
        self.assertEqual([k for _, k in casas[0].leituras], [100, 140])
        self.assertIn("fora da sequencia", rej[0].motivo)
        self.assertEqual(rej[0].linha, 3)

    def test_arquivo_ausente_ou_sem_colunas(self):
        with self.assertRaises(ArquivoInvalido):
            ler_mutirao(Path("nao-existe.csv"), 150, date.today())
        with self.assertRaises(ArquivoInvalido):
            ler_mutirao(self._arquivo("casa,data\nCASA-001,2026-10-01\n"), 150, date.today())
        with self.assertRaises(ArquivoInvalido):
            ler_mutirao(self._arquivo("# so comentario\n"), 150, date.today())

    def test_casas_mvp_duplicadas(self):
        f = self._arquivo("apelido,codigo_casa,limite_reais\nA,cod1,100\nA,cod2,100\nB,,100\n")
        casas, rej = ler_casas_mvp(f, 150)
        self.assertEqual(len(casas), 1)
        self.assertEqual([r.motivo for r in rej], ["apelido duplicado", "apelido ou codigo vazio"])


if __name__ == "__main__":
    unittest.main()
