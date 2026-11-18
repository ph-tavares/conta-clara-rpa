# Testes e validação

## Como rodar

```bash
python -m unittest discover -s tests -v
```

Não precisa instalar nada, nem ter internet: as APIs da ANEEL, do Open-Meteo, do MVP e do ntfy são substituídas por um dublê (`tests/apoio.py`). O teste do cliente HTTP sobe um servidor local de verdade para provar as novas tentativas. Resultado da última execução: **34 testes, todos ok** ([`assets/07-testes-automatizados.png`](../assets/07-testes-automatizados.png)).

## Cenários automatizados

| Tipo | Teste | O que prova |
|---|---|---|
| Sucesso | `TestSucesso.test_execucao_completa` | coleta, contrato `0.9511/verde`, estimativas, status por casa, resumo `SUCESSO` |
| Sucesso | `TestSucesso.test_logs_sem_codigo_da_casa` | o código da casa não aparece em nenhum log nem em nenhuma saída (LGPD) |
| Decisão | `TestDecisao.test_mvp_ja_atualizado_nao_precisa_publicar` | MVP igual ao mês → `SEM_MUDANCA` |
| Decisão | `TestDecisao.test_onda_de_calor_antecipa_alerta` | casa a 94% do limite + calor → `ATENCAO_CALOR` |
| Decisão | `TestDecisao.test_bandeira_vermelha_encarece_e_dispara_alerta` | vermelha P2 empurra a casa para `ACIMA_DO_LIMITE` |
| Decisão | `TestDecisao.test_bandeira_nao_suportada_nao_e_publicada` | escassez hídrica → `NAO_PUBLICAR` (revisão humana) |
| Decisão | `TestDecisao.test_alerta_push_nao_e_reenviado` | duas execuções → um único push |
| Falha | `TestFalhas.test_aneel_fora_usa_cache` | ANEEL 503 → cache, código 1 |
| Falha | `TestFalhas.test_aneel_fora_sem_cache_e_falha_critica` | sem cache → código 2, nenhum contrato gerado |
| Falha | `TestFalhas.test_codigo_de_casa_invalido_nao_para_o_lote` | 401 numa casa → só ela fica `FALHA` |
| Falha | `TestFalhas.test_mvp_fora_do_ar` | MVP fora → casas do mutirão seguem |
| Falha | `TestFalhas.test_clima_fora_desliga_so_a_regra_de_calor` | Open-Meteo fora → aviso, código 0 |
| Falha | `TestFalhas.test_planilha_ausente_e_registrada` | arquivo ausente → erro registrado, código 1 |
| Falha | `TestFalhas.test_falha_no_push_fica_pendente` | ntfy fora → `alerta=falhou`, código 1 |
| Unidade | `TestRegras`, `TestFontes`, `TestEntrada`, `TestClienteHttp` | fórmula igual à do MVP (R$ 161,95), ICMS por faixa, número no formato brasileiro, nomes das bandeiras, vigência da tarifa, duplicatas, datas, pico de anotação, novas tentativas com espera exponencial, sem repetir erro 4xx |

## Cenários executados de verdade (APIs reais, 18/11/2026)

| # | Comando | Resultado | Evidência |
|---|---|---|---|
| 1 | `python src/executar.py` | SUCESSO (0): bandeira verde, tarifa 0,9511, decisão `ATUALIZAR`, 9 casas, 3 alertas push, 7 linhas rejeitadas | `assets/01-execucao-sucesso.png`, `assets/06-alertas-ntfy.png` |
| 2 | `python src/executar.py` de novo | SUCESSO (0): alertas `ja_enviado`, sem push duplicado | `assets/02-reexecucao-sem-reenvio.png` |
| 3 | `--simular-falha aneel` | SUCESSO_PARCIAL (1): 3 tentativas e recuperação pelo cache | `assets/03-falha-aneel-recuperacao.png` |
| 4 | `--simular-falha aneel-sem-cache` | FALHA_CRITICA (2): nada publicado | `assets/04-falha-critica.png` |
| 5 | `--simular-falha mvp` | SUCESSO_PARCIAL (1): casa do MVP `FALHA`, mutirão processado | `assets/05-falha-mvp.png` |

Os logs completos dessas execuções estão em [`logs/`](../logs). As simulações gravam as saídas em `saida/simulacoes/` e nunca sobrescrevem o contrato real.
