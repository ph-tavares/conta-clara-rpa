# PDD: Documento de Definição do Processo

**Processo:** atualização mensal da tarifa e da bandeira do Conta Clara, estimativa da conta de cada casa e alerta de conta alta
**Robô:** `conta-clara-rpa` (Python 3.10 ou mais novo, só biblioteca padrão)
**Desenho BPMN:** [`processo.bpmn`](processo.bpmn), que abre em https://demo.bpmn.io ou no Camunda Modeler, e [`fluxo-processo.svg`](fluxo-processo.svg)

## 1. Processo atual (AS-IS, manual)

| # | Etapa manual | Quem | Problema |
|---|---|---|---|
| 1 | Entrar no site da ANEEL e descobrir a bandeira do mês | voluntário do CRAS | a bandeira muda todo mês e é divulgada no fim do mês anterior; é fácil esquecer |
| 2 | Procurar a tarifa B1 residencial da Enel SP na resolução homologatória | voluntário | tabela com mais de 300 mil linhas; erro de linha ou de unidade (R$/MWh × R$/kWh) |
| 3 | Somar TUSD e TE, aplicar ICMS e PIS/COFINS e trocar `TARIFA_KWH`/`BANDEIRA` no MVP | quem tem acesso à nuvem | o MVP ficou com valores fixos de referência (0,92 e amarela) |
| 4 | Passar a planilha do mutirão a limpo e calcular a conta de cada família | voluntário | duplicatas, número digitado errado, nome no lugar do código |
| 5 | Avisar as famílias com conta acima do limite | agente do CRAS | o aviso chega tarde ou não chega |

Tempo estimado: de 3 a 4 horas por mês para cerca de 50 casas, com risco alto de erro.

## 2. Processo automatizado (TO-BE)

| Item | Definição |
|---|---|
| **Gatilho** | agendado: todo dia às 08h (GitHub Actions, `.github/workflows/robo-mensal.yml`), com o estado guardado entre execuções; também pode ser disparado manualmente. Rodar todo dia é seguro: alertas não se repetem no mês e o MVP só é atualizado quando muda algo |
| **Entradas** | (1) API CKAN da ANEEL: *Bandeira Tarifária – Acionamento* e *Tarifas Homologadas*; (2) API Open-Meteo: máxima prevista para 7 dias na zona sul de SP; (3) API do MVP: `/api/config` e `/api/leituras`; (4) `entrada/casas_mvp.csv`: casas do MVP acompanhadas, com apelido, código e limite; (5) `entrada/leituras_mutirao.csv`: planilha do mutirão do CRAS, com id pseudônimo, data, kWh e limite |
| **Saídas** | `saida/<AAAA-MM>/tarifa_vigente.json` e `.env` (contrato do MVP), `estimativas.csv`, `alertas.json`, `rejeitados.csv`, `resumo_execucao.json`; push no ntfy.sh; `logs/robo-<id>.log` e `logs/auditoria.jsonl` |
| **Intervenção humana** | nenhuma no caminho normal. Revisão humana só quando o robô a pede: bandeira não suportada pelo MVP ou falha crítica |

### Etapas

| # | Etapa | Regra ou decisão | Exceção e tratamento |
|---|---|---|---|
| 1 | Coletar a bandeira da competência | `DatCompetencia = AAAA-MM-01`; se o mês ainda não saiu, usa o mais recente e marca `bandeira_provisoria` | API fora: 3 tentativas com espera de 2, 4 e 8 s, depois o cache |
| 2 | Coletar a tarifa B1 residencial convencional vigente da ELETROPAULO (Enel SP) | vigente se início ≤ dia 1 da competência ≤ fim; trava de sanidade entre 0,20 e 3,00 R$/kWh | dado vazio ou absurdo vira `DadoInvalido` e cai no cache |
| 3 | Recuperar pelo cache | cache local com até 45 dias | sem cache válido: **falha crítica**, código 2; nada é publicado nem alertado |
| 4 | Consultar a previsão de calor | onda de calor = 3 ou mais dias com máxima ≥ 32 °C nos próximos 7 dias | falha só desliga a regra de calor (aviso no resumo) |
| 5 | Gerar o contrato do MVP | tarifa com tributos "por dentro": (TUSD+TE)/(1 − ICMS − PIS/COFINS), faixa de referência de 150 kWh (ICMS 12%) | — |
| 6 | Decidir a atualização do MVP | `ATUALIZAR` se o `/api/config` difere do contrato; `SEM_MUDANCA` se é igual; `NAO_PUBLICAR` se a bandeira não existe no MVP (ex.: escassez hídrica) | MVP fora: `INDEFINIDA`, contrato fica pronto para publicar depois |
| 7 | Ler e validar as entradas | id no padrão `CASA-000` (sem nome nem endereço), data ISO e não futura, kWh inteiro de até 6 dígitos, limite de R$ 10 a R$ 5.000 | arquivo ausente ou sem colunas: erro registrado e o lote segue com a outra origem; linha ruim vai para `rejeitados.csv` com o motivo |
| 8 | Tratar duplicatas e inconsistências | linha idêntica: ignora uma; duas leituras diferentes no mesmo dia: descarta as duas; medidor "voltando": descarta a leitura fora da sequência | tudo registrado em `rejeitados.csv` e no log |
| 9 | **Para cada casa** (repetição) | obter as leituras (API do MVP ou planilha), calcular o consumo diário e a projeção de 30 dias, aplicar o ICMS da faixa e o adicional da bandeira | erro numa casa (ex.: 401 de código revogado) marca só essa casa como `FALHA`; o lote continua |
| 10 | Decidir o alerta | `ACIMA_DO_LIMITE` se a conta passa do limite; `ATENCAO_CALOR` se está a 90% ou mais do limite e há onda de calor; senão `OK`; menos de 2 leituras: `DADOS_INSUFICIENTES` | push falhou: `alerta=falhou`, a execução termina com código 1 e o alerta é tentado de novo na próxima execução |
| 11 | Enviar o alerta sem duplicar | chave `competência:casa:status` guardada em `estado/` | reexecução no mesmo mês: `ja_enviado` |
| 12 | Publicar no MVP (opcional, `--publicar-azure`) | só se a decisão for `ATUALIZAR`; confirma lendo `/api/config` | `az` ausente ou erro: registrado, código 1 |
| 13 | Gravar saídas, log e auditoria | código de saída: 0 sucesso, 1 parcial, 2 crítica | — |

## 3. Indicadores do processo

- Tempo de execução (em média 6 s com as APIs no ar), casas processadas, linhas rejeitadas, alertas enviados e execuções com cache.
- Dia em que o MVP passou a usar a tarifa do mês (meta: no mesmo dia em que a ANEEL publica).

## 4. Fora do escopo

- Envio da contestação à distribuidora (o cidadão envia pelo canal oficial).
- Leitura do medidor por foto (componente de Visão Computacional).
