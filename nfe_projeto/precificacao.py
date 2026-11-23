"""Formação do preço de venda a partir da última compra do produto.

Escopo deste arquivo: só o cálculo (sem tela). A ficha do produto (produtos.py) chama `calcular` e mostra
os dois cenários lado a lado:

  HOJE (2026) — tributos "por dentro" do preço, com markup divisor:
      custo de compra = produto + frete + seguro + outras − desconto + IPI + ICMS-ST + FCP-ST
      custo líquido   = custo de compra − créditos (dependem do regime da empresa que compra)
      preço           = custo líquido / (1 − (tributos sobre a venda % + despesas % + margem %))
    Em 2026 o IBS/CBS de teste é compensado com PIS/COFINS, então não muda o preço.

  APÓS A REFORMA (2033, estimativa) — ICMS, PIS, COFINS e IPI deixam de existir; IBS/CBS ficam
  "por fora" do preço e tudo que é pago na compra vira crédito:
      custo sem tributos = valor da operação − ICMS − FCP − PIS − COFINS (o que vinha embutido no preço)
      preço sem IBS/CBS  = custo / (1 − (IRPJ/CSLL % + despesas % + margem %))
      preço final        = preço sem IBS/CBS + IBS/CBS (alíquota de referência × (1 − redução do produto))

É uma estimativa para apoiar a decisão, não um cálculo oficial: a alíquota de referência de 2033 ainda
não foi fixada e cada empresa tem particularidades (benefícios fiscais, regimes especiais, etc.).
"""

REGIMES_EMPRESA = {"simples": "Simples Nacional", "presumido": "Lucro Presumido", "real": "Lucro Real"}

PARAMETROS_PADRAO = {
    "regime": "simples",
    "aliquota_simples": 8.0,      # alíquota efetiva do DAS (%)
    "icms_venda": 18.0,           # ICMS (+FCP) na venda interna (%), quando não há substituição tributária
    "irpj_csll": 2.28,            # Lucro Presumido no comércio: IRPJ 8% × 15% + CSLL 12% × 9% da receita
    "despesas": 15.0,             # despesas operacionais (aluguel, folha, comissões...) em % do preço
    "margem": 10.0,               # lucro desejado em % do preço
    "aliquota_reforma": 26.5,     # estimativa de IBS + CBS de referência em 2033 (%)
}

PIS_COFINS_NAO_CUMULATIVO = 9.25   # Lucro Real: PIS 1,65% + COFINS 7,6%
PIS_COFINS_CUMULATIVO = 3.65       # Lucro Presumido: PIS 0,65% + COFINS 3%
CST_SEM_PIS_COFINS_NA_REVENDA = ("04", "05", "06")  # monofásico, substituição e alíquota zero


def _n(valor):
    return float(valor) if valor not in (None, "") else 0.0


def calcular(compra, impostos, parametros, margem=None, icms_venda=None, cclasstrib=""):
    """Calcula os dois cenários por UNIDADE.

    compra: dicionário com quantidade, valor_total, frete, seguro, desconto, outras (item da última nota)
    impostos: {sigla: {base, aliquota, valor, cst}} da última compra
    parametros: dicionário como PARAMETROS_PADRAO (dados da empresa)
    margem / icms_venda: valores específicos do produto (se None, usa os parâmetros da empresa)
    Devolve {"hoje": cenário, "reforma": cenário, "avisos": [...]}; cada cenário tem "linhas"
    [(descrição, valor por unidade)], "preco" e "erro" (texto quando o preço não pode ser calculado).
    """
    qtd = _n(compra["quantidade"]) or 1.0
    regime = parametros["regime"]
    margem = parametros["margem"] if margem is None else margem
    despesas = parametros["despesas"]

    def valor(sigla):
        return _n((impostos.get(sigla) or {}).get("valor"))

    operacao = (_n(compra["valor_total"]) + _n(compra["frete"]) + _n(compra["seguro"]) + _n(compra["outras"])
                - _n(compra["desconto"]))
    tem_st = "ICMS-ST" in impostos                     # ST já paga: não há ICMS na revenda nem crédito
    cst_pis = (impostos.get("PIS") or {}).get("cst", "")
    sem_pis_cofins = cst_pis in CST_SEM_PIS_COFINS_NA_REVENDA
    avisos = []
    if tem_st:
        avisos.append("Produto com substituição tributária: o ICMS já foi pago na compra, então não há ICMS "
                      "na revenda nem crédito de ICMS.")
    if sem_pis_cofins:
        avisos.append(f"PIS/COFINS da compra com CST {cst_pis} (monofásico/ST/alíquota zero): sem PIS/COFINS "
                      "na revenda e sem crédito.")
    if regime == "simples":
        avisos.append("Simples Nacional após a reforma: o cenário considera a opção por recolher IBS/CBS fora do "
                      "DAS (regime regular), que dá crédito integral. Quem continuar com IBS/CBS dentro do DAS "
                      "não tem esse crédito e o preço tende a ficar mais perto do cenário de hoje.")

    # ------------------------------------------------------------------ HOJE
    custo = operacao + valor("IPI") + valor("ICMS-ST") + valor("FCP-ST")
    credito_icms = valor("ICMS") if regime in ("presumido", "real") and not tem_st else 0.0
    credito_pis_cofins = 0.0
    if regime == "real" and not sem_pis_cofins:  # base do crédito sem o ICMS (Lei 14.592/2023)
        credito_pis_cofins = (operacao - valor("ICMS")) * PIS_COFINS_NAO_CUMULATIVO / 100
    custo_liquido = custo - credito_icms - credito_pis_cofins

    icms_venda = parametros["icms_venda"] if icms_venda is None else icms_venda
    if regime == "simples":
        tributos_venda = {"Simples Nacional (DAS)": parametros["aliquota_simples"]}
    else:
        icms = 0.0 if tem_st else icms_venda
        taxa = PIS_COFINS_NAO_CUMULATIVO if regime == "real" else PIS_COFINS_CUMULATIVO
        # PIS/COFINS sobre a receita sem o ICMS (STF, Tema 69)
        pis_cofins = 0.0 if sem_pis_cofins else taxa * (1 - icms / 100)
        tributos_venda = {"ICMS na venda": icms, "PIS/COFINS na venda": pis_cofins}
        if regime == "presumido":
            tributos_venda["IRPJ/CSLL (presumido)"] = parametros["irpj_csll"]
    hoje = _markup(custo_liquido / qtd, tributos_venda, despesas, margem, [
        ("Custo de compra (com IPI e ST)", custo / qtd),
        ("(−) Crédito de ICMS", -credito_icms / qtd),
        ("(−) Crédito de PIS/COFINS", -credito_pis_cofins / qtd),
    ])

    # ------------------------------------------------------------------ APÓS A REFORMA (estimativa)
    embutidos = valor("ICMS") + valor("FCP") + (0.0 if sem_pis_cofins else valor("PIS") + valor("COFINS"))
    custo_reforma = operacao - embutidos
    reducao = _reducao_ibs_cbs(impostos, cclasstrib)
    aliquota = parametros["aliquota_reforma"] * (1 - reducao)
    outros = {} if regime == "real" else {"IRPJ/CSLL sobre a receita": parametros["irpj_csll"]}
    reforma = _markup(custo_reforma / qtd, outros, despesas, margem, [
        ("Custo sem tributos (IBS/CBS da compra vira crédito)", custo_reforma / qtd),
    ])
    if reforma["preco"] is not None:
        ibs_cbs = reforma["preco"] * aliquota / 100
        texto = f"(+) IBS/CBS por fora ({aliquota:.2f}%".replace(".", ",")
        texto += f", redução de {reducao * 100:.0f}%)" if reducao else ")"
        reforma["linhas"].append(("Preço sem IBS/CBS", reforma["preco"]))
        reforma["linhas"].append((texto, ibs_cbs))
        reforma["preco"] += ibs_cbs
    return {"hoje": hoje, "reforma": reforma, "avisos": avisos}


def _markup(custo, percentuais, despesas, margem, linhas):
    """Markup divisor: preço = custo / (1 − soma dos percentuais sobre o preço)."""
    soma = sum(percentuais.values()) + despesas + margem
    linhas = [linha for linha in linhas if abs(linha[1]) > 0.004]
    if soma >= 100:
        return {"linhas": linhas, "preco": None,
                "erro": f"Tributos + despesas + margem somam {soma:.2f}% do preço; precisa ser menos de 100%."}
    preco = custo / (1 - soma / 100)
    if len(linhas) > 1:
        linhas.append(("= Custo líquido", custo))
    for nome, pct in percentuais.items():
        if pct:
            linhas.append((f"(+) {nome} ({pct:.2f}%)".replace(".", ","), preco * pct / 100))
    linhas.append((f"(+) Despesas operacionais ({despesas:.2f}%)".replace(".", ","), preco * despesas / 100))
    linhas.append((f"(+) Lucro ({margem:.2f}%)".replace(".", ","), preco * margem / 100))
    return {"linhas": linhas, "preco": preco, "erro": None}


def _reducao_ibs_cbs(impostos, cclasstrib):
    """Redução de alíquota do produto (0 a 1). Cesta básica (cClassTrib 200003) = 100%. Senão, usa a
    proporção entre a CBS paga e a CBS nominal na última compra (a CBS tem valores maiores que o IBS de
    teste, então sofre menos com arredondamento), arredondada para dezenas (30%, 60%...)."""
    if cclasstrib == "200003":
        return 1.0
    cbs = impostos.get("CBS") or {}
    base, aliq, valor = _n(cbs.get("base")), _n(cbs.get("aliquota")), _n(cbs.get("valor"))
    if base and aliq:
        return round(min(max(1 - valor / (base * aliq / 100), 0.0), 1.0), 1)
    return 0.0
