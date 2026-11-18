# Integração com o MVP Conta Clara

O MVP (`app/main.py` do repositório [conta-clara](https://github.com/ph-tavares/conta-clara)) lê a tarifa e a bandeira das variáveis de ambiente `TARIFA_KWH` e `BANDEIRA` e mostra os dois valores em `/api/config`. A tela usa esses valores para calcular a **conta estimada** e o **valor esperado** na conferência. Antes do robô, os dois eram valores fixos de referência (`0.92` e `amarela`).

O robô gera esses valores **todo mês**, a partir dos dados abertos da ANEEL, e os entrega ao MVP de três formas.

## 1. Contrato em arquivo: `saida/tarifa_vigente.json` (formato estável, `versao_contrato: 1`)

```json
{
  "versao_contrato": 1,
  "competencia": "2026-11",
  "gerado_em": "2026-11-18T10:29:23-03:00",
  "tarifa_kwh": 0.9511,
  "bandeira": "verde",
  "adicional_bandeira_100kwh": 0.0,
  "bandeira_provisoria": false,
  "bandeira_suportada_pelo_mvp": true,
  "origem_dados": "api_aneel",
  "detalhe": { "distribuidora": "ELETROPAULO", "resolucao": "RESOLUÇÃO HOMOLOGATÓRIA Nº 3.596 ...", "...": "..." }
}
```

| Campo | Tipo | Uso no MVP |
|---|---|---|
| `tarifa_kwh` | número (R$/kWh, com tributos aproximados) | vira `TARIFA_KWH` |
| `bandeira` | `verde` \| `amarela` \| `vermelha1` \| `vermelha2` (mesmas chaves do dicionário `ADICIONAL_BANDEIRA` do MVP) | vira `BANDEIRA` |
| `adicional_bandeira_100kwh` | número (R$ por 100 kWh) | conferência: deve bater com `ADICIONAL_BANDEIRA[bandeira]` |
| `bandeira_provisoria` | booleano | `true` quando a ANEEL ainda não publicou a bandeira do mês |
| `origem_dados` | `api_aneel` ou `cache_local (N dia(s))` | rastreabilidade |

O mesmo contrato também é gravado no formato de variáveis de ambiente, em `saida/<competencia>/tarifa_vigente.env`:

```
TARIFA_KWH=0.9511
BANDEIRA=verde
```

## 2. Publicação automática no App Service (`--publicar-azure`)

```bash
az login                                   # conta com acesso ao web app contaclara-gs
python src/executar.py --publicar-azure
```

O robô só publica quando a decisão é `ATUALIZAR`, ou seja, quando os valores do mês são diferentes dos que estão em `/api/config` e a bandeira é suportada pelo MVP. Ele roda `az webapp config appsettings set ... TARIFA_KWH=... BANDEIRA=...` e depois **confirma lendo `/api/config`** até o MVP mostrar os valores novos. O App Service reinicia o container ao trocar as configurações.

Manualmente, o efeito é o mesmo:

```bash
az webapp config appsettings set -g rg-contaclara -n contaclara-gs --settings TARIFA_KWH=0.9511 BANDEIRA=verde
curl -s https://contaclara-gs.azurewebsites.net/api/config
```

> **Cuidado com o Terraform do MVP:** o `infra/terraform/main.tf` do MVP define `app_settings` sem essas duas chaves. Um `terraform apply` posterior removeria os valores publicados pelo robô. Para tornar a ligação permanente, acrescente ao `lifecycle.ignore_changes` do `azurerm_linux_web_app`:
> ```hcl
> ignore_changes = [
>   site_config[0].application_stack[0].docker_image_name,
>   app_settings["TARIFA_KWH"],
>   app_settings["BANDEIRA"],
> ]
> ```

## 3. Leitura do MVP pelo robô (API)

Em toda execução, o robô também **consome** o MVP:

- `GET /api/config`: compara a configuração atual com a do mês e decide `ATUALIZAR`, `SEM_MUDANCA`, `NAO_PUBLICAR` ou `INDEFINIDA`;
- `GET /api/leituras` com o cabeçalho `X-Codigo-Casa`: busca as leituras de cada casa cadastrada para recalcular a estimativa com a tarifa nova. O código vai só no cabeçalho, nunca na URL nem no log, onde aparece como `cod#` mais 8 caracteres do hash.

## Ligação com a camada Ouro (Big Data)

O componente de Dados pode gravar a tabela Ouro de tarifas no mesmo formato. Basta que a linha do mês tenha `competencia`, `tarifa_kwh`, `bandeira` e `adicional_bandeira_100kwh`. Com isso, MVP, robô e Ouro falam o mesmo contrato.
