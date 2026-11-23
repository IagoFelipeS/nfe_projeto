"""Conferência da reforma tributária (IBS e CBS) nos itens e nos totais da NF-e.

Escopo deste arquivo: regras que geram alertas com o prefixo "Reforma:". Ele é chamado por importar.py
durante a importação e não tem tela própria (os alertas aparecem na tela Conferência).

Base das regras (leiaute da NT 2025.002-RTC da NF-e e LC 214/2025):
  1. Regime normal (CRT 3) deve informar o grupo IBS/CBS nas notas emitidas a partir de 2026.
     Simples Nacional / MEI (CRT 1, 2 e 4) só passam a ser obrigados em 2027, então não geram alerta.
  2. cClassTrib tem 6 dígitos e os 3 primeiros são o próprio CST (a SEFAZ rejeita se não baterem).
  3. Em 2026 (ano de teste) as alíquotas são CBS 0,9%, IBS estadual 0,1% e IBS municipal 0%.
  4. Valor = base x alíquota efetiva, sendo alíquota efetiva = alíquota x (1 - redução/100).
  5. Produtos da Cesta Básica Nacional (Anexo I da LC 214) têm alíquota zero: CST 200, cClassTrib 200003.
  6. Os totais da nota (grupo IBSCBSTot) devem ser a soma dos itens.

As datas e regras de validação ainda mudam por nota técnica: por isso tudo aqui é AVISO para conferência
humana, nunca bloqueia a importação.
"""
from decimal import Decimal

ALIQUOTAS_2026 = {"CBS": Decimal("0.90"), "IBS estadual": Decimal("0.10"), "IBS municipal": Decimal("0.00")}
TOLERANCIA = Decimal("0.02")

CST_CESTA_BASICA, CCLASSTRIB_CESTA_BASICA = "200", "200003"

# NCMs da Cesta Básica Nacional (Anexo I da LC 214/2025), sem pontos. Ficaram de fora os NCMs em que só
# parte dos produtos entra na cesta (ex.: 1905.90.90, que só vale para o pão francês), para não gerar
# alerta falso.
CESTA_BASICA = set("""
10062010 10062020 10063011 10063019 10063021 10063029 10064000
04011010 04011090 04012010 04012090 04014010 04015010
04021010 04021090 04022110 04022120 04022910 04022920
04051000 15171000
07133319 07133329 07133399 07133590
09011110 09011190 09011200 09012100 09012200 09019000 21011110 21011190 21011200
15132120 11062000 19030000 11022000 11031300 11041900 11042300 11010010 11041200 11042200 11029000
17011400 17019900 19021100 19021900 19012010 19012090
04061010 04061090 04062000 04069010 04069020 04069030
25010020 25010090 09030010 09030090
""".split())
# Carnes (capítulo 02) e peixes frescos/congelados (03.02, 03.03 e filés 03.04) entram por prefixo
PREFIXOS_CESTA_BASICA = ("0201", "0202", "0203", "0204", "0206", "0207", "0209", "0210",
                         "0302", "0303", "030431", "030432", "030433", "030439", "030461", "030462",
                         "030463", "030469")


def _d(texto):
    try:
        return Decimal(str(texto)) if texto not in (None, "") else None
    except ArithmeticError:
        return None


def _difere(a, b):
    return a is not None and b is not None and abs(a - b) > TOLERANCIA


def fmt(valor):
    return f"{valor:.2f}".replace(".", ",")


def na_cesta_basica(ncm):
    return ncm in CESTA_BASICA or ncm.startswith(PREFIXOS_CESTA_BASICA)


def validar_item(item, crt, ano):
    """Alertas da reforma para um item. `item["ibscbs"]` vem de importar.py (None se o grupo não existe)."""
    g = item["ibscbs"]
    if g is None:
        if crt == "3" and ano >= 2026:
            return ["Reforma: item sem o grupo IBS/CBS (obrigatório para o regime normal desde 2026)"]
        return []

    msgs = []
    cst, cclass = g["cst"], g["cclasstrib"]
    if not (len(cst) == 3 and cst.isdigit()):
        msgs.append(f"Reforma: CST do IBS/CBS inválido ({cst or 'vazio'}), deve ter 3 dígitos")
    if not (len(cclass) == 6 and cclass.isdigit()):
        msgs.append(f"Reforma: cClassTrib inválido ({cclass or 'vazio'}), deve ter 6 dígitos")
    elif cst and cclass[:3] != cst:
        msgs.append(f"Reforma: cClassTrib {cclass} não pertence ao CST {cst} (os 3 primeiros dígitos devem ser o CST)")

    if na_cesta_basica(item["ncm"]) and cclass != CCLASSTRIB_CESTA_BASICA:
        msgs.append(f"Reforma: NCM {item['ncm']} está na Cesta Básica Nacional (alíquota zero, CST "
                    f"{CST_CESTA_BASICA} / cClassTrib {CCLASSTRIB_CESTA_BASICA}), mas veio com cClassTrib {cclass or 'vazio'}")

    # Diferimento e compras governamentais mudam o cálculo: nesses casos não conferimos valores
    if g["diferimento"] or g["compra_gov"]:
        return msgs

    base = _d(g["vbc"])
    for nome, parte in (("IBS estadual", g["uf"]), ("IBS municipal", g["mun"]), ("CBS", g["cbs"])):
        aliq, valor = _d(parte["aliq"]), _d(parte["valor"])
        if ano == 2026 and aliq is not None and aliq != ALIQUOTAS_2026[nome]:
            msgs.append(f"Reforma: alíquota de {nome} {fmt(aliq)}% diferente da alíquota de teste de 2026 "
                        f"({fmt(ALIQUOTAS_2026[nome])}%)")
        if aliq is None:
            continue
        reducao = _d(parte["reducao"])
        efetiva = aliq * (1 - reducao / 100) if reducao is not None else aliq
        informada = _d(parte["efetiva"])
        if reducao is not None and _difere(informada, efetiva):
            msgs.append(f"Reforma: alíquota efetiva de {nome} informada ({fmt(informada)}%) não corresponde à "
                        f"redução de {fmt(reducao)}% (esperado {fmt(efetiva)}%)")
        if base is not None and _difere(valor, base * efetiva / 100):
            msgs.append(f"Reforma: valor de {nome} R$ {fmt(valor)} não bate com base × alíquota efetiva "
                        f"(esperado R$ {fmt(base * efetiva / 100)})")

    v_ibs, v_uf, v_mun = _d(g["vibs"]), _d(g["uf"]["valor"]), _d(g["mun"]["valor"])
    if v_uf is not None and _difere(v_ibs, v_uf + (v_mun or 0)):
        msgs.append("Reforma: valor total do IBS diferente da soma IBS estadual + IBS municipal")
    return msgs


def validar_totais(totais, itens):
    """Compara o grupo IBSCBSTot da nota com a soma dos itens. Devolve a lista de alertas."""
    if totais is None or not any(i["ibscbs"] for i in itens):
        return []
    msgs = []
    somas = {"vbc": Decimal(0), "vibs": Decimal(0), "vcbs": Decimal(0)}
    for item in itens:
        g = item["ibscbs"]
        if g:
            somas["vbc"] += _d(g["vbc"]) or 0
            somas["vibs"] += _d(g["vibs"]) or 0
            somas["vcbs"] += _d(g["cbs"]["valor"]) or 0
    for chave, nome in (("vbc", "base do IBS/CBS"), ("vibs", "IBS"), ("vcbs", "CBS")):
        informado = _d(totais[chave])
        if _difere(informado, somas[chave]):
            msgs.append(f"Reforma: total de {nome} da nota (R$ {fmt(informado)}) diferente da soma dos itens "
                        f"(R$ {fmt(somas[chave])})")
    return msgs
