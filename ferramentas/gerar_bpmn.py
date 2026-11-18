"""Gera docs/processo.bpmn (BPMN 2.0 com diagrama, abre no bpmn.io / Camunda Modeler)
e docs/fluxo-processo.svg (mesma figura, para o README e o relatorio) a partir de um unico layout.

    python ferramentas/gerar_bpmn.py
"""
import html
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
TW, TH, GW, EV = 128, 64, 50, 36  # tarefa, gateway, evento

# id: (tipo, rotulo, cx, cy)
NOS = {
    "inicio":      ("timer", "Todo dia, 08h", 50, 110),
    "t_coleta":    ("task", "Coletar bandeira e tarifa do mês (API ANEEL)", 180, 110),
    "gw_aneel":    ("xor", "ANEEL ok e dado válido?", 330, 110),
    "t_cache_salva": ("task", "Salvar cache da coleta", 470, 110),
    "m1":          ("xor", "", 610, 110),
    "t_clima":     ("task", "Consultar previsão de calor (Open-Meteo)", 750, 110),
    "t_contrato":  ("task", "Gerar contrato tarifa_vigente (.json e .env)", 910, 110),
    "t_config":    ("task", "Ler /api/config do MVP e decidir a atualização", 1070, 110),
    "t_entradas":  ("task", "Ler e validar entradas (MVP + planilha do mutirão)", 1230, 110),
    "t_cache_le":  ("task", "Ler cache local (até 45 dias)", 330, 250),
    "gw_cache":    ("xor", "Cache válido?", 470, 250),
    "t_critica":   ("task", "Registrar falha crítica (nada é publicado)", 470, 370),
    "fim_erro":    ("end_error", "Falha crítica (código 2)", 610, 370),
    "t_proxima":   ("task", "Pegar a próxima casa do lote", 180, 530),
    "t_leituras":  ("task", "Obter leituras (API do MVP ou planilha)", 330, 530),
    "gw_leit":     ("xor", "Leituras ok (2 ou mais)?", 480, 530),
    "t_calc":      ("task", "Calcular consumo e conta com a tarifa do mês", 630, 530),
    "gw_lim":      ("xor", "Acima do limite ou perto com calor?", 780, 530),
    "t_alerta":    ("task", "Enviar alerta push (sem reenvio)", 930, 530),
    "m2":          ("xor", "", 1070, 530),
    "gw_mais":     ("xor", "Há mais casas?", 1200, 530),
    "t_reg":       ("task", "Registrar FALHA ou DADOS INSUFICIENTES", 480, 660),
    "gw_pub":      ("xor", "Publicar? (--publicar-azure e ATUALIZAR)", 180, 845),
    "t_pub":       ("task", "Atualizar App Service e confirmar /api/config", 340, 845),
    "m3":          ("xor", "", 490, 845),
    "t_saidas":    ("task", "Gravar saídas, logs e auditoria", 640, 845),
    "fim":         ("end", "Fim (código 0 ou 1)", 790, 845),
}

ROTULO_LATERAL = {"gw_mais": "dir", "gw_pub": "esq"}

# (origem, destino, rotulo, pontos intermediarios)
ARESTAS = [
    ("inicio", "t_coleta", "", []),
    ("t_coleta", "gw_aneel", "", []),
    ("gw_aneel", "t_cache_salva", "sim", []),
    ("t_cache_salva", "m1", "", []),
    ("gw_aneel", "t_cache_le", "não", []),
    ("t_cache_le", "gw_cache", "", []),
    ("gw_cache", "m1", "sim", [(610, 250)]),
    ("gw_cache", "t_critica", "não", []),
    ("t_critica", "fim_erro", "", []),
    ("m1", "t_clima", "", []),
    ("t_clima", "t_contrato", "", []),
    ("t_contrato", "t_config", "", []),
    ("t_config", "t_entradas", "", []),
    ("t_entradas", "t_proxima", "", [(1230, 422), (90, 422), (90, 530)]),
    ("t_proxima", "t_leituras", "", []),
    ("t_leituras", "gw_leit", "", []),
    ("gw_leit", "t_calc", "sim", []),
    ("gw_leit", "t_reg", "não", []),
    ("t_reg", "m2", "", [(1070, 660)]),
    ("t_calc", "gw_lim", "", []),
    ("gw_lim", "t_alerta", "sim", []),
    ("gw_lim", "m2", "não", [(780, 600), (1070, 600)]),
    ("t_alerta", "m2", "", []),
    ("m2", "gw_mais", "", []),
    ("gw_mais", "t_proxima", "sim", [(1200, 470), (180, 470)]),
    ("gw_mais", "gw_pub", "não", [(1200, 725), (180, 725)]),
    ("gw_pub", "t_pub", "sim", []),
    ("gw_pub", "m3", "não", [(180, 905), (490, 905)]),
    ("t_pub", "m3", "", []),
    ("m3", "t_saidas", "", []),
    ("t_saidas", "fim", "", []),
]

NOTAS = [
    ("n1", "Retry 3x com espera exponencial em toda chamada HTTP", 180, 205),
    ("n2", "Falha no clima só desliga a regra de calor", 750, 205),
    ("n3", "Loop: cada casa é independente; erro numa casa não para o lote", 820, 690),
    ("n4", "Linhas inválidas, duplicadas ou fora de sequência vão para rejeitados.csv", 1070, 205),
]


def tamanho(tipo):
    return {"task": (TW, TH), "xor": (GW, GW)}.get(tipo, (EV, EV))


def borda(no, alvo):
    """Ponto na borda do no na direcao de alvo (layout ortogonal)."""
    tipo, _, cx, cy = NOS[no]
    w, h = tamanho(tipo)
    ax, ay = alvo
    if abs(ax - cx) >= abs(ay - cy):
        return (cx + (w / 2 if ax > cx else -w / 2), cy)
    return (cx, cy + (h / 2 if ay > cy else -h / 2))


def caminho(a, b, meio):
    _, _, ax, ay = NOS[a]
    _, _, bx, by = NOS[b]
    primeiro = meio[0] if meio else (bx, by)
    ultimo = meio[-1] if meio else (ax, ay)
    return [borda(a, primeiro), *meio, borda(b, ultimo)]


def quebrar(texto, largura=17):
    linhas, atual = [], ""
    for p in texto.split():
        if len(atual) + len(p) + 1 > largura and atual:
            linhas.append(atual)
            atual = p
        else:
            atual = f"{atual} {p}".strip()
    return linhas + ([atual] if atual else [])


# ------------------------------------------------------------------ BPMN XML
def bpmn() -> str:
    tag = {"timer": "startEvent", "task": "serviceTask", "xor": "exclusiveGateway", "end": "endEvent",
           "end_error": "endEvent"}
    entram = {n: [] for n in NOS}
    saem = {n: [] for n in NOS}
    for i, (a, b, *_r) in enumerate(ARESTAS):
        saem[a].append(f"f{i}")
        entram[b].append(f"f{i}")
    proc = []
    for n, (tipo, rot, *_r) in NOS.items():
        filhos = "".join(f"<bpmn:incoming>{f}</bpmn:incoming>" for f in entram[n])
        filhos += "".join(f"<bpmn:outgoing>{f}</bpmn:outgoing>" for f in saem[n])
        if tipo == "timer":
            filhos += '<bpmn:timerEventDefinition id="def_timer"><bpmn:timeCycle xsi:type="bpmn:tFormalExpression">0 11 * * *</bpmn:timeCycle></bpmn:timerEventDefinition>'
        if tipo == "end_error":
            filhos += '<bpmn:errorEventDefinition id="def_erro" />'
        proc.append(f'    <bpmn:{tag[tipo]} id="{n}" name="{html.escape(rot)}">{filhos}</bpmn:{tag[tipo]}>')
    for i, (a, b, rot, _m) in enumerate(ARESTAS):
        proc.append(f'    <bpmn:sequenceFlow id="f{i}" name="{html.escape(rot)}" sourceRef="{a}" targetRef="{b}" />')
    for nid, txt, *_r in NOTAS:
        proc.append(f'    <bpmn:textAnnotation id="{nid}"><bpmn:text>{html.escape(txt)}</bpmn:text></bpmn:textAnnotation>')
    di = []
    for n, (tipo, _rot, cx, cy) in NOS.items():
        w, h = tamanho(tipo)
        extra = ' isMarkerVisible="true"' if tipo == "xor" else ""
        di.append(f'      <bpmndi:BPMNShape id="{n}_di" bpmnElement="{n}"{extra}><dc:Bounds x="{cx - w / 2:.0f}" y="{cy - h / 2:.0f}" width="{w}" height="{h}" /></bpmndi:BPMNShape>')
    for i, (a, b, _rot, meio) in enumerate(ARESTAS):
        pts = "".join(f'<di:waypoint x="{x:.0f}" y="{y:.0f}" />' for x, y in caminho(a, b, meio))
        di.append(f'      <bpmndi:BPMNEdge id="f{i}_di" bpmnElement="f{i}">{pts}</bpmndi:BPMNEdge>')
    for nid, _t, cx, cy in NOTAS:
        di.append(f'      <bpmndi:BPMNShape id="{nid}_di" bpmnElement="{nid}"><dc:Bounds x="{cx - 80}" y="{cy - 22}" width="160" height="44" /></bpmndi:BPMNShape>')
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
  xmlns:di="http://www.omg.org/spec/DD/20100524/DI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  id="defs_conta_clara" targetNamespace="https://github.com/ph-tavares/conta-clara-rpa" exporter="gerar_bpmn.py" exporterVersion="1.0">
  <bpmn:process id="robo_mensal_conta_clara" name="Robô mensal Conta Clara" isExecutable="false">
{chr(10).join(proc)}
  </bpmn:process>
  <bpmndi:BPMNDiagram id="diagrama">
    <bpmndi:BPMNPlane id="plano" bpmnElement="robo_mensal_conta_clara">
{chr(10).join(di)}
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>
"""


# ------------------------------------------------------------------ SVG
def svg() -> str:
    cor_tarefa, cor_linha, cor_gw = "#e8f1fb", "#33475b", "#fff6d6"
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1330 950" width="1330" height="950" '
           'font-family="Segoe UI, Arial, sans-serif">',
           '<defs><marker id="seta" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
           f'<path d="M0,0 L10,5 L0,10 z" fill="{cor_linha}"/></marker></defs>',
           '<rect width="1330" height="950" fill="#ffffff"/>']
    faixas = [(20, "1. Coleta e decisão sobre o MVP", 20, 400, "#f7f9fc"),
              (20, "2. Lote de casas (repetição)", 425, 290, "#f4fbf6"),
              (20, "3. Publicação e encerramento", 735, 205, "#fbf7f4")]
    for x, titulo, y, h, cor in faixas:
        out.append(f'<rect x="{x}" y="{y}" width="1290" height="{h}" rx="10" fill="{cor}" stroke="#d5dde6"/>')
        out.append(f'<text x="{x + 1278}" y="{y + 18}" font-size="13" font-weight="700" fill="#5a6b7d" text-anchor="end">{titulo}</text>')
    for nid, txt, cx, cy in NOTAS:
        out.append(f'<path d="M{cx - 80},{cy - 22} h-0 v44 M{cx - 80},{cy - 22} h14 M{cx - 80},{cy + 22} h14" stroke="#8a9bb0" fill="none"/>')
        for i, l in enumerate(quebrar(txt, 30)):
            out.append(f'<text x="{cx - 74}" y="{cy - 8 + i * 14}" font-size="11" fill="#5a6b7d" font-style="italic">{html.escape(l)}</text>')
    for a, b, rot, meio in ARESTAS:
        pts = caminho(a, b, meio)
        d = "M" + " L".join(f"{x:.0f},{y:.0f}" for x, y in pts)
        out.append(f'<path d="{d}" fill="none" stroke="{cor_linha}" stroke-width="1.6" marker-end="url(#seta)"/>')
        if rot:
            (x0, y0), (x1, y1) = pts[0], pts[1]
            tx, ty = ((x0 + 6, y0 + 16 if y1 > y0 else y0 - 8) if x0 == x1 else (x0 + 8, y0 - 6))
            out.append(f'<text x="{tx:.0f}" y="{ty:.0f}" font-size="11.5" font-weight="700" fill="#1d6b3a">{rot}</text>')
    for n, (tipo, rot, cx, cy) in NOS.items():
        if tipo == "task":
            out.append(f'<rect x="{cx - TW / 2}" y="{cy - TH / 2}" width="{TW}" height="{TH}" rx="9" fill="{cor_tarefa}" stroke="{cor_linha}" stroke-width="1.5"/>')
            linhas = quebrar(rot)
            y0 = cy - (len(linhas) - 1) * 7.5 + 4
            for i, l in enumerate(linhas):
                out.append(f'<text x="{cx}" y="{y0 + i * 15}" font-size="12" text-anchor="middle" fill="#1b2733">{html.escape(l)}</text>')
        elif tipo == "xor":
            h = GW / 2
            out.append(f'<path d="M{cx},{cy - h} L{cx + h},{cy} L{cx},{cy + h} L{cx - h},{cy} z" fill="{cor_gw}" stroke="{cor_linha}" stroke-width="1.5"/>')
            out.append(f'<path d="M{cx - 7},{cy - 7} L{cx + 7},{cy + 7} M{cx + 7},{cy - 7} L{cx - 7},{cy + 7}" stroke="{cor_linha}" stroke-width="2.5"/>')
            lado = ROTULO_LATERAL.get(n)
            linhas = quebrar(rot, 14 if lado else 20)
            for i, l in enumerate(linhas):
                if lado:  # rotulo ao lado do losango quando a linha de chegada passa por cima
                    x = cx + h + 6 if lado == "dir" else cx - h - 6
                    y = cy + 4 + (i - (len(linhas) - 1) / 2) * 13
                    ancora = "start" if lado == "dir" else "end"
                else:
                    x, y, ancora = cx, cy - h - 8 - (len(linhas) - 1 - i) * 13, "middle"
                out.append(f'<text x="{x}" y="{y:.0f}" font-size="11.5" text-anchor="{ancora}" fill="#1b2733" font-weight="600">{html.escape(l)}</text>')
        else:
            r = EV / 2
            borda_ = {"timer": 1.5, "end": 4, "end_error": 4}[tipo]
            cor = {"timer": "#e6f6ea", "end": "#fde8e8", "end_error": "#fde8e8"}[tipo]
            out.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{cor}" stroke="{cor_linha}" stroke-width="{borda_}"/>')
            if tipo == "timer":
                out.append(f'<circle cx="{cx}" cy="{cy}" r="{r - 6}" fill="#fff" stroke="{cor_linha}"/>'
                           f'<path d="M{cx},{cy - 7} L{cx},{cy} L{cx + 5},{cy + 3}" stroke="{cor_linha}" fill="none" stroke-width="1.5"/>')
            if tipo == "end_error":
                out.append(f'<path d="M{cx - 7},{cy + 7} L{cx - 3},{cy - 7} L{cx + 2},{cy + 2} L{cx + 7},{cy - 7}" stroke="#b42318" fill="none" stroke-width="2"/>')
            for i, l in enumerate(quebrar(rot, 26)):
                out.append(f'<text x="{cx}" y="{cy + r + 15 + i * 13}" font-size="11.5" text-anchor="middle" fill="#1b2733">{html.escape(l)}</text>')
    out.append("</svg>")
    return "\n".join(out)


if __name__ == "__main__":
    DOCS.mkdir(exist_ok=True)
    (DOCS / "processo.bpmn").write_text(bpmn(), encoding="utf-8")
    (DOCS / "fluxo-processo.svg").write_text(svg(), encoding="utf-8")
    print("ok: docs/processo.bpmn e docs/fluxo-processo.svg")
