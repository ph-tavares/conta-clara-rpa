"""Cenarios de ponta a ponta (sucesso, decisao e falha) com as fontes externas simuladas."""
import csv
import unittest

from apoio import COMPETENCIA, HttpFalso, ler_json, pasta_temporaria

from robo_conta_clara.robo import FALHA_CRITICA, SUCESSO, SUCESSO_PARCIAL, Opcoes, executar

CASAS_MVP = "apelido,codigo_casa,limite_reais\nMVP-DEMO,demonstracao,170\n"
MUTIRAO = ("id_casa;data_leitura;kwh_medidor;limite_reais\n"
           "CASA-001;2026-10-20;15230;120\nCASA-001;2026-11-17;15314;\n"      # 90 kWh/mes  -> OK
           "CASA-002;2026-10-20;30210;180\nCASA-002;2026-11-17;30409;\n"      # 213 kWh/mes -> acima do limite
           "CASA-003;2026-10-20;22100;140\nCASA-003;2026-11-17;22229;\n")     # 138 kWh/mes -> perto do limite


def rodar(http, casas=CASAS_MVP, mutirao=MUTIRAO, **kw):
    base = pasta_temporaria(casas, mutirao)
    op = Opcoes(base=base, competencia=COMPETENCIA, arquivo_casas_mvp=base / "entrada" / "casas_mvp.csv",
                arquivo_mutirao=base / "entrada" / "mutirao.csv", **kw)
    return base, op, executar(op, http=http)


def estimativas(base):
    with (base / "saida" / COMPETENCIA / "estimativas.csv").open(encoding="utf-8-sig") as f:
        return {r["casa"]: r for r in csv.DictReader(f, delimiter=";")}


class TestSucesso(unittest.TestCase):
    def test_execucao_completa(self):
        http = HttpFalso()
        base, op, codigo = rodar(http)
        self.assertEqual(codigo, SUCESSO)
        saida = base / "saida" / COMPETENCIA
        contrato = ler_json(saida / "tarifa_vigente.json")
        self.assertEqual((contrato["tarifa_kwh"], contrato["bandeira"], contrato["origem_dados"]),
                         (0.9511, "verde", "api_aneel"))
        self.assertEqual((saida / "tarifa_vigente.env").read_text(), "TARIFA_KWH=0.9511\nBANDEIRA=verde\n")
        est = estimativas(base)
        self.assertEqual({k: v["status"] for k, v in est.items()},
                         {"MVP-DEMO": "OK", "CASA-001": "OK", "CASA-002": "ACIMA_DO_LIMITE", "CASA-003": "OK"})
        resumo = ler_json(saida / "resumo_execucao.json")
        self.assertEqual(resumo["situacao"], "SUCESSO")
        self.assertTrue(resumo["decisao_mvp"].startswith("ATUALIZAR"))
        self.assertTrue((base / "saida" / "tarifa_vigente.json").exists())

    def test_logs_sem_codigo_da_casa(self):
        base, _, _ = rodar(HttpFalso())
        textos = [p.read_text(encoding="utf-8") for p in (base / "logs").iterdir()]
        textos += [p.read_text(encoding="utf-8-sig") for p in (base / "saida" / COMPETENCIA).iterdir()]
        self.assertTrue(textos)
        for t in textos:
            self.assertNotIn("demonstracao", t)


class TestDecisao(unittest.TestCase):
    def test_mvp_ja_atualizado_nao_precisa_publicar(self):
        http = HttpFalso(mvp_config={"tarifa_kwh": 0.9511, "bandeira": "verde", "adicional_bandeira_100kwh": 0})
        base, _, _ = rodar(http)
        self.assertTrue(ler_json(base / "saida" / COMPETENCIA / "resumo_execucao.json")["decisao_mvp"].startswith("SEM_MUDANCA"))

    def test_onda_de_calor_antecipa_alerta(self):
        base, _, _ = rodar(HttpFalso(maximas=[33, 34, 35, 30, 29, 28, 33]))
        self.assertEqual(estimativas(base)["CASA-003"]["status"], "ATENCAO_CALOR")

    def test_bandeira_vermelha_encarece_e_dispara_alerta(self):
        base, _, _ = rodar(HttpFalso(bandeira="Vermelha P2", adicional="78,77"))
        est = estimativas(base)
        self.assertEqual(est["MVP-DEMO"]["status"], "ACIMA_DO_LIMITE")  # 172,5 kWh com +R$ 7,88/100 kWh

    def test_bandeira_nao_suportada_nao_e_publicada(self):
        base, _, codigo = rodar(HttpFalso(bandeira="Escassez Hidrica", adicional="142,00"))
        resumo = ler_json(base / "saida" / COMPETENCIA / "resumo_execucao.json")
        self.assertEqual(codigo, SUCESSO_PARCIAL)
        self.assertTrue(resumo["decisao_mvp"].startswith("NAO_PUBLICAR"))

    def test_alerta_push_nao_e_reenviado(self):
        http = HttpFalso()
        base = pasta_temporaria(CASAS_MVP, MUTIRAO)
        op = Opcoes(base=base, competencia=COMPETENCIA, arquivo_casas_mvp=base / "entrada" / "casas_mvp.csv",
                    arquivo_mutirao=base / "entrada" / "mutirao.csv", ntfy_url="https://ntfy.sh/topico-teste")
        executar(op, http=http)
        executar(op, http=http)
        self.assertEqual(len(http.push), 1)  # so a CASA-002, uma unica vez
        self.assertEqual(estimativas(base)["CASA-002"]["alerta"], "ja_enviado")


class TestFalhas(unittest.TestCase):
    def test_aneel_fora_usa_cache(self):
        base, op, _ = rodar(HttpFalso())                      # 1a execucao grava o cache
        codigo = executar(op, http=HttpFalso(fora={"aneel"}))  # 2a: ANEEL fora do ar
        resumo = ler_json(base / "saida" / COMPETENCIA / "resumo_execucao.json")
        self.assertEqual(codigo, SUCESSO_PARCIAL)
        self.assertTrue(resumo["origem_tarifa"].startswith("cache_local"))
        self.assertEqual(ler_json(base / "saida" / COMPETENCIA / "tarifa_vigente.json")["tarifa_kwh"], 0.9511)

    def test_aneel_fora_sem_cache_e_falha_critica(self):
        base, _, codigo = rodar(HttpFalso(fora={"aneel"}))
        saida = base / "saida" / COMPETENCIA
        self.assertEqual(codigo, FALHA_CRITICA)
        self.assertFalse((saida / "tarifa_vigente.json").exists())   # nada e publicado com dado duvidoso
        self.assertEqual(ler_json(saida / "resumo_execucao.json")["situacao"], "FALHA_CRITICA")

    def test_codigo_de_casa_invalido_nao_para_o_lote(self):
        casas = CASAS_MVP + "MVP-02,codigo-revogado,150\n"
        base, _, codigo = rodar(HttpFalso(), casas=casas)
        est = estimativas(base)
        self.assertEqual(codigo, SUCESSO_PARCIAL)
        self.assertEqual(est["MVP-02"]["status"], "FALHA")
        self.assertIn("401", est["MVP-02"]["detalhe"])
        self.assertEqual(len(est), 5)  # as outras casas foram processadas

    def test_mvp_fora_do_ar(self):
        base, _, codigo = rodar(HttpFalso(fora={"mvp"}))
        est = estimativas(base)
        self.assertEqual(codigo, SUCESSO_PARCIAL)
        self.assertEqual(est["MVP-DEMO"]["status"], "FALHA")
        self.assertEqual(est["CASA-002"]["status"], "ACIMA_DO_LIMITE")  # o mutirao segue normalmente

    def test_clima_fora_desliga_so_a_regra_de_calor(self):
        base, _, codigo = rodar(HttpFalso(fora={"clima"}))
        self.assertEqual(codigo, SUCESSO)
        avisos = ler_json(base / "saida" / COMPETENCIA / "resumo_execucao.json")["avisos"]
        self.assertTrue(any("previsao do tempo" in a for a in avisos))

    def test_planilha_ausente_e_registrada(self):
        base = pasta_temporaria(CASAS_MVP, None)
        op = Opcoes(base=base, competencia=COMPETENCIA, arquivo_casas_mvp=base / "entrada" / "casas_mvp.csv",
                    arquivo_mutirao=base / "entrada" / "nao-existe.csv")
        codigo = executar(op, http=HttpFalso())
        resumo = ler_json(base / "saida" / COMPETENCIA / "resumo_execucao.json")
        self.assertEqual(codigo, SUCESSO_PARCIAL)
        self.assertTrue(any("nao encontrado" in e for e in resumo["erros"]))

    def test_falha_no_push_fica_pendente(self):
        base, _, codigo = rodar(HttpFalso(fora={"ntfy"}), ntfy_url="https://ntfy.sh/topico-teste")
        self.assertEqual(codigo, SUCESSO_PARCIAL)
        self.assertEqual(estimativas(base)["CASA-002"]["alerta"], "falhou")


if __name__ == "__main__":
    unittest.main()
