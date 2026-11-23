"""Conferência geral dos itens da NF-e (ICMS, FCP, ICMS-ST, DIFAL, IPI, PIS e COFINS).

Escopo deste arquivo: regras que geram os alertas do tipo GERAL. É chamado por importar.py durante a
importação. As regras da reforma tributária (IBS/CBS) ficam em reforma.py.

Cada item chega como dicionário montado em importar.py, com:
  item["impostos"]  lista de tributos (sigla, cst, base, aliq, valor, mva, reducao...)
  item["icms"]      todas as tags do grupo ICMSxx (orig, modBC, vBC, pRedBC, pICMS, pMVAST, vBCST...)
  item["difal"]     tags do grupo ICMSUFDest (DIFAL), ou {} se não houver
Tudo é AVISO para conferência humana; nada impede a importação.
"""
from decimal import Decimal, InvalidOperation

TOLERANCIA = Decimal("0.02")          # diferença aceita por arredondamento
ALIQUOTAS_INTERESTADUAIS = (Decimal(4), Decimal(7), Decimal(12))
ORIGENS_IMPORTADAS = ("1", "2", "3", "8")   # Resolução do Senado 13/2012: alíquota interestadual de 4%
LIMITE_FCP = Decimal(2)                # ADCT art. 82: adicional de até 2 pontos percentuais


def _d(texto):
    try:
        return Decimal(str(texto)) if texto not in (None, "") else None
    except (InvalidOperation, ValueError):
        return None


def fmt(valor):
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _difere(a, b):
    return a is not None and b is not None and abs(a - b) > TOLERANCIA


def _imposto(item, sigla):
    return next((i for i in item["impostos"] if i["sigla"] == sigla), None)


def _valor_operacao(item):
    """Produto + frete + seguro + outras despesas − desconto (o que compõe a base do ICMS)."""
    soma = Decimal(0)
    for campo, sinal in (("vtot", 1), ("frete", 1), ("seguro", 1), ("outras", 1), ("desconto", -1)):
        soma += sinal * (_d(item.get(campo)) or 0)
    return soma


def validar_item(item, crt):
    """Devolve a lista de problemas gerais do item. `crt` é o regime tributário do emitente."""
    msgs = []

    ncm = item["ncm"]
    if not (len(ncm) == 8 and ncm.isdigit()):
        msgs.append(f"NCM ausente ou inválido ({ncm or 'vazio'})")

    qtd, unit, total = _d(item["qtd"]), _d(item["vun"]), _d(item["vtot"])
    if None not in (qtd, unit, total) and abs(qtd * unit - total) > TOLERANCIA:
        msgs.append("Valor total diferente de quantidade × valor unitário")

    grupo = item["icms_grupo"]
    if not grupo:
        msgs.append("Item sem grupo de ICMS")
    else:
        usa_csosn = grupo.startswith("ICMSSN")  # CSOSN = códigos do Simples Nacional
        if crt in ("1", "4") and not usa_csosn:
            msgs.append("Emitente do Simples Nacional, mas o ICMS veio com CST (esperado CSOSN)")
        if crt in ("2", "3") and usa_csosn:
            msgs.append("Emitente do regime normal, mas o ICMS veio com CSOSN (esperado CST)")

    # base × alíquota = valor (IBS/CBS ficam em reforma.py; ICMS-ST, FCP-ST e DIFAL têm regra própria abaixo)
    for imp in item["impostos"]:
        if imp["sigla"] in ("ICMS", "FCP", "FCP-DIFAL", "IPI", "PIS", "COFINS"):
            b, a, v = _d(imp["base"]), _d(imp["aliq"]), _d(imp["valor"])
            if None not in (b, a, v) and _difere(v, b * a / 100):
                msgs.append(f"{imp['sigla']}: base × alíquota não bate com o valor informado "
                            f"(esperado R$ {fmt(b * a / 100)})")

    return msgs + _icms_proprio(item) + _fcp(item) + _substituicao(item) + _difal(item)


def _icms_proprio(item):
    msgs, ic = [], item["icms"]
    if not ic:
        return msgs
    orig = ic.get("orig", "")
    if orig and not (len(orig) == 1 and orig in "012345678"):
        msgs.append(f"Origem da mercadoria inválida ({orig}), deve ser de 0 a 8")

    # Base do ICMS próprio quando a modalidade é "valor da operação" (modBC 3)
    vbc, red = _d(ic.get("vBC")), _d(ic.get("pRedBC")) or Decimal(0)
    if ic.get("modBC") == "3" and vbc is not None:
        operacao = _valor_operacao(item)
        ipi = _d((_imposto(item, "IPI") or {}).get("valor")) or Decimal(0)
        fator = 1 - red / 100
        # o IPI entra na base quando o destinatário é consumidor final; aceitamos os dois casos
        esperados = [operacao * fator, (operacao + ipi) * fator]
        if all(_difere(vbc, e) for e in esperados):
            texto_red = f", com redução de {fmt(red)}%" if red else ""
            msgs.append(f"ICMS: base de cálculo R$ {fmt(vbc)} não confere com o valor da operação "
                        f"(produto + frete + seguro + outras − desconto{texto_red}): esperado R$ {fmt(esperados[0])}")

    # Alíquota interestadual (CFOP 6xxx): 4%, 7% ou 12%; 4% para importados
    aliq = _d(ic.get("pICMS"))
    if item["cfop"].startswith("6") and aliq and not item["icms_grupo"].startswith("ICMSSN"):
        if orig in ORIGENS_IMPORTADAS and aliq != 4:
            msgs.append(f"ICMS interestadual de produto importado (origem {orig}) deve ser 4% "
                        f"(Resolução do Senado 13/2012), veio {fmt(aliq)}%")
        elif aliq not in ALIQUOTAS_INTERESTADUAIS:
            msgs.append(f"Alíquota interestadual de ICMS deve ser 4%, 7% ou 12%, veio {fmt(aliq)}%")
    return msgs


def _fcp(item):
    """Limite de 2% do FCP e valor do FCP-ST (base ST × alíquota − FCP próprio, como no ICMS-ST)."""
    msgs = []
    for sigla in ("FCP", "FCP-ST", "FCP-DIFAL"):
        imp = _imposto(item, sigla)
        aliq = _d(imp["aliq"]) if imp else None
        if aliq is not None and aliq > LIMITE_FCP:
            msgs.append(f"{sigla}: alíquota {fmt(aliq)}% acima do limite de 2% do Fundo de Combate à Pobreza "
                        f"(ADCT art. 82)")

    fcp_st = _imposto(item, "FCP-ST")
    if fcp_st:
        base, aliq, valor = _d(fcp_st["base"]), _d(fcp_st["aliq"]), _d(fcp_st["valor"])
        proprio = _d((_imposto(item, "FCP") or {}).get("valor")) or Decimal(0)
        if None not in (base, aliq, valor) and _difere(valor, base * aliq / 100 - proprio):
            msgs.append(f"FCP-ST: valor R$ {fmt(valor)} não confere com base × alíquota − FCP próprio "
                        f"(esperado R$ {fmt(base * aliq / 100 - proprio)})")
    return msgs


def _substituicao(item):
    """ICMS-ST: valor = base ST × alíquota ST − ICMS próprio; base ST = operação (+IPI) × (1 + MVA)."""
    msgs, ic = [], item["icms"]
    st = _imposto(item, "ICMS-ST")
    if not st:
        return msgs
    base_st, aliq_st, valor_st = _d(st["base"]), _d(st["aliq"]), _d(st["valor"])
    proprio = _d(ic.get("vICMS"))
    if not item["icms_grupo"].startswith("ICMSSN") and None not in (base_st, aliq_st, valor_st, proprio):
        esperado = base_st * aliq_st / 100 - proprio
        if _difere(valor_st, esperado):
            msgs.append(f"ICMS-ST: valor R$ {fmt(valor_st)} não confere com base ST × alíquota − ICMS próprio "
                        f"(esperado R$ {fmt(esperado)})")

    mva, red_st = _d(st["mva"]), _d(st["reducao"]) or Decimal(0)
    if ic.get("modBCST") == "4" and mva is not None and base_st is not None:
        operacao = _valor_operacao(item)
        ipi = _d((_imposto(item, "IPI") or {}).get("valor")) or Decimal(0)
        fator = (1 + mva / 100) * (1 - red_st / 100)
        esperados = [(operacao + ipi) * fator, operacao * fator]
        if all(_difere(base_st, e) for e in esperados):
            texto_red = f" e redução de {fmt(red_st)}%" if red_st else ""
            msgs.append(f"ICMS-ST: base R$ {fmt(base_st)} não confere com valor da operação (+ IPI) com MVA de "
                        f"{fmt(mva)}%{texto_red} (esperado R$ {fmt(esperados[0])})")
    return msgs


def _difal(item):
    """DIFAL (venda interestadual a consumidor final): alíquota interestadual válida, igual à do ICMS do
    item, e partilha 100% para a UF de destino (regra desde 2019)."""
    msgs, d = [], item["difal"]
    if not d:
        return msgs
    inter, partilha = _d(d.get("pICMSInter")), _d(d.get("pICMSInterPart"))
    if inter is not None and inter not in ALIQUOTAS_INTERESTADUAIS:
        msgs.append(f"DIFAL: alíquota interestadual {fmt(inter)}% inválida (deve ser 4%, 7% ou 12%)")
    proprio = _d(item["icms"].get("pICMS"))
    if inter is not None and proprio is not None and inter != proprio:
        msgs.append(f"DIFAL: alíquota interestadual {fmt(inter)}% diferente da alíquota do ICMS do item "
                    f"({fmt(proprio)}%)")
    if partilha is not None and partilha != 100:
        msgs.append(f"DIFAL: partilha de {fmt(partilha)}% para a UF de destino; desde 2019 deve ser 100%")
    return msgs
