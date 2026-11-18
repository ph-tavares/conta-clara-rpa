"""Semente do cache da ANEEL para o GitHub Actions.

A API da ANEEL nao aceita conexao dos runners do GitHub (EUA). Sem cache, o robo agendado terminava
em FALHA_CRITICA todo dia. A semente e a ultima coleta valida feita do Brasil e so entra quando o
Actions nao restaura um cache proprio. Datas injetadas: nenhum teste depende do relogio real.
"""
import shutil
import unittest
from datetime import datetime, timedelta
from unittest import mock

from apoio import RAIZ, HttpFalso, ler_json, pasta_temporaria
from robo_conta_clara.fontes import DadoInvalido, ler_cache
from robo_conta_clara.robo import SUCESSO_PARCIAL, Opcoes, executar

SEMENTE = RAIZ / "config" / "cache_aneel_semente.json"
WORKFLOW = RAIZ / ".github" / "workflows" / "robo-mensal.yml"


def data_da_semente():
    return datetime.fromisoformat(ler_json(SEMENTE)["salvo_em"])


class TestSementeCache(unittest.TestCase):
    def test_SeedCache_semente_e_coleta_valida_da_aneel(self):
        bandeira, tarifa, idade = ler_cache(SEMENTE, data_da_semente().date(), 45)
        self.assertEqual(idade, 0)
        self.assertIn("ANEEL", bandeira.fonte)
        self.assertIn("ANEEL", tarifa.fonte)
        self.assertEqual(tarifa.distribuidora, "ELETROPAULO")
        self.assertGreater(tarifa.tusd_rs_mwh + tarifa.te_rs_mwh, 0)

    def test_SeedCache_semente_vencida_nao_vale(self):
        depois = (data_da_semente() + timedelta(days=46)).date()
        with self.assertRaises(DadoInvalido):
            ler_cache(SEMENTE, depois, 45)

    def test_SeedCache_robo_com_aneel_fora_usa_semente(self):
        base = pasta_temporaria(casas_mvp="id_casa,codigo,limite_reais\nMVP-DEMO,demonstracao,150\n")
        self.addCleanup(shutil.rmtree, base, True)
        (base / "estado").mkdir()
        shutil.copy(SEMENTE, base / "estado" / "cache_aneel.json")
        quando = data_da_semente() + timedelta(days=1)
        competencia = quando.strftime("%Y-%m")
        op = Opcoes(base=base, competencia=competencia, arquivo_casas_mvp=base / "entrada" / "casas_mvp.csv",
                    arquivo_mutirao=base / "entrada" / "mutirao.csv")
        with mock.patch("robo_conta_clara.robo.agora", lambda: quando):
            codigo = executar(op, http=HttpFalso(fora={"aneel"}))
        resumo = ler_json(base / "saida" / competencia / "resumo_execucao.json")
        self.assertEqual(codigo, SUCESSO_PARCIAL)
        self.assertTrue(resumo["origem_tarifa"].startswith("cache_local"))

    def test_SeedCache_workflow_so_usa_semente_sem_cache_restaurado(self):
        texto = WORKFLOW.read_text(encoding="utf-8")
        passo = texto.find("config/cache_aneel_semente.json")
        self.assertGreater(passo, 0, "workflow nao usa a semente")
        self.assertIn("if [ ! -f estado/cache_aneel.json ]", texto)
        self.assertLess(texto.find("Restaurar estado da execucao anterior"), passo)
        self.assertLess(passo, texto.find("- name: Executar robo"))


if __name__ == "__main__":
    unittest.main()
