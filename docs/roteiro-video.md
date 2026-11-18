# Roteiro do vídeo (até 3 minutos)

**Antes de gravar** (5 min):

1. Abra um terminal na pasta do projeto e deixe a fonte grande (Ctrl + roda do mouse).
2. Crie um tópico do ntfy e abra `https://ntfy.sh/<topico>` no navegador ou no app ntfy do celular:
   - PowerShell: `$env:NTFY_URL="https://ntfy.sh/contaclara-SEUNOME123"`
   - Git Bash: `export NTFY_URL=https://ntfy.sh/contaclara-SEUNOME123`
3. Apague `estado/` (se existir) para os alertas saírem de novo na gravação.
4. Deixe abertas as abas: MVP (`https://contaclara-gs.azurewebsites.net/#demonstracao`), `https://contaclara-gs.azurewebsites.net/api/config`, a página do repositório e o `docs/fluxo-processo.svg`.

Grave a tela com o **Xbox Game Bar** (Win + G) ou o **OBS**. Suba no YouTube como **não listado** e cole o link no README e no PDF (veja o fim deste arquivo).

---

| Tempo | Tela | Fala (sugestão) |
|---|---|---|
| 0:00–0:20 | MVP aberto na casa de demonstração | "Este é o Conta Clara: a família anota o número do medidor e vê quanto a conta deve dar. Só que a tarifa e a bandeira que o MVP usa eram valores fixos: 92 centavos e bandeira amarela. Todo mês alguém teria que ir no site da ANEEL, achar a tarifa da Enel SP, calcular imposto, atualizar o sistema e ainda avisar as famílias com conta alta. Esse é o processo manual que eu automatizei." |
| 0:20–0:40 | `fluxo-processo.svg` (BPMN) | "O robô roda sozinho todo dia às 8h, pelo GitHub Actions, e não repete alerta no mesmo mês. Ele coleta bandeira e tarifa na ANEEL, consulta a previsão de calor, compara com o MVP, valida as entradas e faz um laço por todas as casas. Para cada uma, decide se dispara alerta. No fim, grava as saídas e a auditoria." |
| 0:40–1:20 | Terminal: `python src/executar.py` | Enquanto roda, aponte: "Bandeira verde de novembro e tarifa da resolução 3.596 vieram da API da ANEEL agora. O robô leu o `/api/config` do MVP, viu que ele ainda usa 0,92 e amarela, e decidiu ATUALIZAR. Aqui está a validação da planilha do mutirão: linha duplicada, duas leituras no mesmo dia, nome no lugar do código (recusado por LGPD), número ilegível, data no futuro. Tudo vai para o `rejeitados.csv` com o motivo, nada some em silêncio. E aqui o laço: casa por casa, a regra de decisão. A CASA-002 dá 218 reais, acima do limite de 180, e o alerta é enviado." |
| 1:20–1:35 | Navegador/celular com o ntfy | "Os alertas chegaram no celular, só com o código pseudônimo da casa, sem nenhum dado pessoal." |
| 1:35–1:55 | `saida/2026-11/tarifa_vigente.json` e `/api/config` do MVP | "A integração com o MVP: o robô gera este contrato com `TARIFA_KWH` e `BANDEIRA`, no mesmo formato que o MVP lê, e pode publicar direto no App Service com `--publicar-azure`, confirmando em `/api/config`. Ele também consome a API do MVP para buscar as leituras das casas." *(Se tiver `az login`, rode `python src/executar.py --publicar-azure` e mostre o `/api/config` mudando para 0.9511 e verde.)* |
| 1:55–2:35 | Terminal: `python src/executar.py --simular-falha aneel` e depois `--simular-falha aneel-sem-cache` | "Tratamento de falhas: com a ANEEL fora do ar, o robô tenta 3 vezes com espera crescente e recupera pela última coleta válida, terminando como sucesso parcial. Sem cache, ele para com falha crítica, código 2, e não publica nada com dado duvidoso." |
| 2:35–2:50 | `logs/auditoria.jsonl` e `python -m unittest discover -s tests` | "Cada execução gera log com data e hora e uma trilha de auditoria em JSON. E há 34 testes automáticos cobrindo sucesso, decisão e falha." |
| 2:50–3:00 | README no GitHub | "Tudo está no repositório público, com README, BPMN, PDD e as evidências. Obrigado!" |

---

## Depois de gravar

1. Troque `LINK-DO-VIDEO` no `README.md` pelo link do vídeo.
2. Gere o PDF final com o link:
   ```bash
   python ferramentas/gerar_pdf.py --video https://youtu.be/SEU-VIDEO
   ```
   (se o repositório não for `ph-tavares/conta-clara-rpa`, acrescente `--repo https://github.com/<login>/conta-clara-rpa`)
3. `git add -A && git commit -m "docs: link do video e relatorio final" && git push`
4. Envie `docs/relatorio-rpa.pdf` na tarefa do Teams até **19/11/2026, 23h55**.
