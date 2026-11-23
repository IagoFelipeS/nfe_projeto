"""Tela 4 — Produtos: catálogo vindo das notas (busca e filtro por status) e, ao abrir um produto,
a ficha com os dados cadastrais editáveis, a tributação atual e o histórico de compras.

Escopo: consultas e atualizações da tabela produtos + as duas visões (lista e ficha) da mesma tela.
"""
import flet as ft

from nfe_projeto import precificacao
from nfe_projeto.importar import ORIGENS, TRIBUTOS

SIGLAS = [sigla for sigla, _ in TRIBUTOS]
CAMPOS_EMPRESA = [  # (coluna em configuracoes, rótulo na tela)
    ("aliquota_simples", "DAS do Simples (%)"),
    ("icms_venda", "ICMS + FCP na venda (%)"),
    ("irpj_csll", "IRPJ/CSLL s/ receita (%)"),
    ("despesas", "Despesas operacionais (%)"),
    ("margem", "Margem de lucro padrão (%)"),
    ("aliquota_reforma", "IBS + CBS em 2033 (%)"),
]


# ----------------------------------------------------------------------------- consultas

def listar_produtos(app, busca="", status=""):
    """Produtos com fornecedor e quantidade de compras. Filtra por texto e por status."""
    like = f"%{busca.strip()}%"
    return app.consultar("""
        SELECT p.id, p.codigo, p.ean, p.descricao, p.ncm, p.cclasstrib, p.origem, p.unidade, p.status,
               p.preco_venda,
               f.nome AS fornecedor,
               (SELECT COUNT(*) FROM itens_nota i WHERE i.produto_id = p.id) AS compras
        FROM produtos p JOIN fornecedores f ON f.id = p.fornecedor_id
        WHERE (? = '' OR p.descricao LIKE ? OR p.codigo LIKE ? OR p.ncm LIKE ? OR p.ean LIKE ?
               OR p.cclasstrib LIKE ?)
          AND (? = '' OR p.status = ?)
        ORDER BY p.descricao
        LIMIT 300""", (busca.strip(), like, like, like, like, like, status, status))


def obter_produto(app, produto_id):
    linhas = app.consultar("""
        SELECT p.*, f.nome AS fornecedor
        FROM produtos p JOIN fornecedores f ON f.id = p.fornecedor_id
        WHERE p.id = ?""", (produto_id,))
    return linhas[0] if linhas else None


def tributacao_atual(app, produto_id):
    """Impostos do item mais recente comprado desse produto (é o que se leva para o cadastro),
    na ordem do catálogo de tributos (ICMS, FCP, ICMS-ST... CBS)."""
    linhas = app.consultar("""
        SELECT t.sigla, ii.cst, ii.modalidade, ii.base, ii.reducao_base, ii.mva, ii.aliquota, ii.valor, ii.detalhe
        FROM impostos_item ii
        JOIN tributos t ON t.id = ii.tributo_id
        WHERE ii.item_id = (SELECT MAX(id) FROM itens_nota WHERE produto_id = ?)""", (produto_id,))
    return sorted(linhas, key=lambda x: SIGLAS.index(x["sigla"]) if x["sigla"] in SIGLAS else len(SIGLAS))


def ultima_compra(app, produto_id):
    """Item mais recente do produto (CFOP, origem, benefício fiscal, quantidade e valores) para a ficha."""
    linhas = app.consultar("""
        SELECT cfop, origem, cbenef, quantidade, valor_unitario, valor_total, frete, seguro, desconto, outras
        FROM itens_nota
        WHERE id = (SELECT MAX(id) FROM itens_nota WHERE produto_id = ?)""", (produto_id,))
    return linhas[0] if linhas else None


def parametros_empresa(app):
    return app.consultar("SELECT * FROM configuracoes WHERE id = 1")[0]


def historico_produto(app, produto_id):
    return app.consultar("""
        SELECT n.numero, n.data_emissao, i.cfop, i.quantidade, i.valor_unitario, i.valor_total,
               i.frete, i.seguro, i.desconto, i.outras
        FROM itens_nota i JOIN notas n ON n.id = i.nota_id
        WHERE i.produto_id = ?
        ORDER BY n.id DESC""", (produto_id,))


# ----------------------------------------------------------------------------- tela

def construir(app, produto_id=None):
    """Sem produto_id mostra a lista; com produto_id mostra a ficha daquele produto."""
    return _lista(app) if produto_id is None else _ficha(app, produto_id)


def _lista(app):
    filtro = {"status": ""}  # '', 'pendente' ou 'cadastrado'
    lista = ft.Container()
    busca = app.campo("Buscar por descrição, código, NCM, EAN ou cClassTrib", largura=420,
                      on_change=lambda e: atualizar())

    def montar():
        linhas = [[app.selo_produto(p["status"]), p["codigo"], p["descricao"][:48], p["ncm"],
                   ft.Text(p["origem"] or "—", size=13, tooltip=ORIGENS.get(p["origem"])),
                   p["cclasstrib"] or "—", p["ean"] or "—", p["unidade"], p["fornecedor"], str(p["compras"]),
                   app.dinheiro(p["preco_venda"]),
                   app.botao("Ficha", lambda e, i=p["id"]: app.ir("produtos", produto_id=i), False)]
                  for p in listar_produtos(app, busca.value or "", filtro["status"])]
        lista.content = app.tabela(
            ["Status", "Código", "Descrição", "NCM", "Orig.", "cClassTrib", "EAN", "Un.", "Fornecedor", "Compras",
             "Preço venda", ""],
            linhas,
            texto_vazio="Nenhum produto encontrado. Importe uma NF-e para criá-los.")

    def atualizar():
        montar()
        app.page.update()

    def definir(status):
        filtro["status"] = status
        atualizar()

    filtros = ft.Row([busca,
                      app.botao("Todos", lambda e: definir(""), False),
                      app.botao("Pendentes", lambda e: definir("pendente"), False),
                      app.botao("Cadastrados", lambda e: definir("cadastrado"), False)])
    montar()
    return ft.Column([app.titulo("Produtos", "Itens das notas, prontos para o cadastro no sistema de destino"),
                      filtros, lista], spacing=16)


def _ficha(app, produto_id):
    produto = obter_produto(app, produto_id)
    if produto is None:
        return app.vazio("Produto não encontrado.")

    descricao = app.campo("Descrição", produto["descricao"], 520)
    ncm = app.campo("NCM (8 dígitos)", produto["ncm"], 180)
    ean = app.campo("EAN / GTIN", produto["ean"], 220)
    cest = app.campo("CEST", produto["cest"], 150)
    unidade = app.campo("Unidade", produto["unidade"], 110)
    cclasstrib = app.campo("cClassTrib (IBS/CBS)", produto["cclasstrib"], 200)
    opcao = getattr(ft, "DropdownOption", None) or ft.dropdown.Option  # nome muda entre versões do Flet
    origem = ft.Dropdown(label="Origem da mercadoria", value=produto["origem"] or None, width=520,
                         options=[opcao(key=k, text=f"{k} – {v}") for k, v in ORIGENS.items()])
    aviso = ft.Text("", color=app.cor.VERDE)

    def salvar(e):
        app.executar("""UPDATE produtos SET descricao = ?, ncm = ?, ean = ?, cest = ?, unidade = ?, cclasstrib = ?,
                                            origem = ?
                        WHERE id = ?""",
                     (descricao.value.strip() or produto["descricao"], ncm.value.strip(), ean.value.strip(),
                      cest.value.strip(), unidade.value.strip(), cclasstrib.value.strip(), origem.value or "",
                      produto_id))
        aviso.value = "Dados salvos."
        app.page.update()

    def alternar_status(e):
        novo = "pendente" if produto["status"] == "cadastrado" else "cadastrado"
        app.executar("UPDATE produtos SET status = ? WHERE id = ?", (novo, produto_id))
        app.ir("produtos", produto_id=produto_id)

    rotulo_status = ("Voltar para pendente" if produto["status"] == "cadastrado"
                     else "Marcar como cadastrado no sistema de destino")

    formulario = app.cartao(ft.Column([
        ft.Row([app.selo_produto(produto["status"]),
                ft.Text(f"Código {produto['codigo']}  ·  {produto['fornecedor']}", color=app.cor.MUTED)]),
        descricao,
        ft.Row([ncm, ean, cest, unidade, cclasstrib], wrap=True),
        origem,
        ft.Row([app.botao("Salvar alterações", salvar), app.botao(rotulo_status, alternar_status, False), aviso]),
    ], spacing=12))

    compra = ultima_compra(app, produto_id)
    tributos = tributacao_atual(app, produto_id)
    resumo_compra = ft.Text(
        f"Última compra: CFOP {compra['cfop'] or '—'}  ·  benefício fiscal (cBenef) {compra['cbenef'] or '—'}"
        if compra else "Sem compras.", color=app.cor.MUTED)

    def valor_ou_traco(valor):
        return app.dinheiro(valor) if valor else "—"

    return ft.Column([
        app.titulo("Ficha do produto", "Dados para levar ao cadastro no outro sistema",
                   app.botao("Voltar", lambda e: app.ir("produtos"), False)),
        formulario,
        app.subtitulo("Tributação (item mais recente comprado)"),
        resumo_compra,
        app.tabela(["Tributo", "CST / CSOSN", "Modalidade da base", "Base de cálculo", "Redução da base", "MVA",
                    "Alíquota", "Valor", "Detalhes"],
                   [[x["sigla"], x["cst"] or "—", x["modalidade"] or "—", app.dinheiro(x["base"]),
                     app.percentual(x["reducao_base"]), app.percentual(x["mva"]), app.percentual(x["aliquota"]),
                     app.dinheiro(x["valor"]), x["detalhe"] or "—"] for x in tributos],
                   texto_vazio="Sem impostos destacados."),
        app.subtitulo("Histórico de compras"),
        app.tabela(["NF", "Emissão", "CFOP", "Quantidade", "Valor unitário", "Valor total", "Frete", "Seguro",
                    "Desconto", "Outras despesas"],
                   [[h["numero"], app.data_br(h["data_emissao"]), h["cfop"], app.quantidade(h["quantidade"]),
                     app.dinheiro(h["valor_unitario"]), app.dinheiro(h["valor_total"]), valor_ou_traco(h["frete"]),
                     valor_ou_traco(h["seguro"]), valor_ou_traco(h["desconto"]), valor_ou_traco(h["outras"])]
                    for h in historico_produto(app, produto_id)]),
        app.subtitulo("Preço de venda sugerido"),
        _preco_venda(app, produto, compra, {x["sigla"]: x for x in tributos}) if compra
        else app.vazio("Sem compras para calcular o preço."),
    ], spacing=16)


# ----------------------------------------------------------------------------- preço de venda

def _numero(campo):
    """Texto digitado ('12,5' ou '12.5') -> 12.5; None se vazio ou inválido."""
    try:
        return float((campo.value or "").replace(",", "."))
    except ValueError:
        return None


def _preco_venda(app, produto, compra, impostos):
    """Parâmetros da empresa + margem do produto -> preço hoje e preço estimado após a reforma.
    Qualquer campo alterado recalcula na hora; os botões gravam no banco."""
    empresa = parametros_empresa(app)
    tem_st = "ICMS-ST" in impostos

    # ICMS na venda: o do produto; senão, numa compra interna, a mesma alíquota da compra (ICMS + FCP)
    icms_produto = produto["icms_venda"]
    if icms_produto is None and compra["cfop"].startswith("5") and impostos.get("ICMS", {}).get("aliquota"):
        icms_produto = impostos["ICMS"]["aliquota"] + ((impostos.get("FCP") or {}).get("aliquota") or 0)

    def numero_br(valor):
        return "" if valor is None else app.br(valor).replace(".", "")

    margem = app.campo("Margem de lucro deste produto (%)", numero_br(produto["margem"] or empresa["margem"]), 250,
                       on_change=lambda e: recalcular())
    icms = app.campo("ICMS + FCP na venda deste produto (%)", numero_br(icms_produto or empresa["icms_venda"]),
                     280, on_change=lambda e: recalcular(), disabled=tem_st,
                     tooltip="Produto com ST: não há ICMS na revenda" if tem_st else None)
    opcao = getattr(ft, "DropdownOption", None) or ft.dropdown.Option
    regime = ft.Dropdown(label="Regime da sua empresa", value=empresa["regime"], width=250,
                         options=[opcao(key=k, text=v) for k, v in precificacao.REGIMES_EMPRESA.items()])
    if hasattr(regime, "on_select"):  # Flet 1.x usa on_select; versões antigas, on_change
        regime.on_select = lambda e: recalcular()
    else:
        regime.on_change = lambda e: recalcular()
    campos = {nome: app.campo(rotulo, numero_br(empresa[nome]), 210, on_change=lambda e: recalcular())
              for nome, rotulo in CAMPOS_EMPRESA}
    aviso = ft.Text("", color=app.cor.VERDE)
    cenarios = ft.Row(wrap=True, spacing=16, vertical_alignment=ft.CrossAxisAlignment.START)
    observacoes = ft.Column(spacing=2)
    resultado = {"hoje": None}

    def ler_parametros():
        valores = {nome: _numero(c) for nome, c in campos.items()}
        if None in valores.values():
            return None
        return {"regime": regime.value or "simples", **valores}

    def cartao_cenario(titulo, subtitulo, cenario, destaque):
        if cenario["erro"]:
            corpo = [ft.Text(cenario["erro"], color=app.cor.AMBAR)]
        else:
            corpo = [ft.Row([ft.Text(descricao, size=13, expand=True), ft.Text(app.dinheiro(valor), size=13)])
                     for descricao, valor in cenario["linhas"]]
            corpo += [ft.Divider(height=8),
                      ft.Row([ft.Text("Preço de venda por unidade", weight="bold", expand=True),
                              ft.Text(app.dinheiro(cenario["preco"]), size=22, weight="bold", color=destaque)])]
        return app.cartao(ft.Column([ft.Text(titulo, size=15, weight="bold"),
                                     ft.Text(subtitulo, size=12, color=app.cor.MUTED)] + corpo, spacing=6),
                          width=460)

    def recalcular(atualizar=True):
        parametros, margem_valor, icms_valor = ler_parametros(), _numero(margem), _numero(icms)
        if parametros is None or margem_valor is None or (icms_valor is None and not tem_st):
            cenarios.controls = [ft.Text("Preencha todos os percentuais com números.", color=app.cor.AMBAR)]
            resultado["hoje"] = None
        else:
            calculo = precificacao.calcular(compra, impostos, parametros, margem_valor, icms_valor or 0,
                                            produto["cclasstrib"])
            resultado["hoje"] = calculo["hoje"]["preco"]
            cenarios.controls = [
                cartao_cenario("Hoje (2026)", "ICMS, PIS e COFINS por dentro do preço; IBS/CBS de teste "
                               "compensados com PIS/COFINS", calculo["hoje"], app.cor.VERDE),
                cartao_cenario("Após a reforma (2033, estimativa)", "IBS/CBS por fora do preço, com crédito "
                               "integral na compra", calculo["reforma"], app.cor.AZUL),
            ]
            notas = list(calculo["avisos"])
            hoje, depois = calculo["hoje"]["preco"], calculo["reforma"]["preco"]
            if hoje and depois:
                notas.insert(0, f"Diferença do preço final após a reforma: {app.dinheiro(depois - hoje)} "
                                f"({(depois / hoje - 1) * 100:+.1f}%)".replace(".", ","))
            observacoes.controls = [ft.Text("• " + n, size=12, color=app.cor.MUTED) for n in notas]
        if atualizar:
            app.page.update()

    def salvar_produto(e):
        if resultado["hoje"] is None:
            return
        app.executar("UPDATE produtos SET margem = ?, icms_venda = ?, preco_venda = ? WHERE id = ?",
                     (_numero(margem), None if tem_st else _numero(icms), round(resultado["hoje"], 2),
                      produto["id"]))
        aviso.value = f"Preço de {app.dinheiro(resultado['hoje'])} salvo no cadastro do produto."
        app.page.update()

    def salvar_empresa(e):
        parametros = ler_parametros()
        if parametros is None:
            return
        app.executar(f"UPDATE configuracoes SET {', '.join(f'{k} = ?' for k in parametros)} WHERE id = 1",
                     tuple(parametros.values()))
        aviso.value = "Parâmetros da empresa salvos (valem para todos os produtos)."
        app.page.update()

    recalcular(atualizar=False)
    unitario = app.dinheiro(compra["valor_unitario"])
    return ft.Column([
        ft.Text(f"Calculado por unidade a partir da última compra ({app.quantidade(compra['quantidade'])} un. a "
                f"{unitario}). É uma estimativa para apoiar a decisão, não substitui o contador.",
                color=app.cor.MUTED),
        app.cartao(ft.Column([
            ft.Text("Parâmetros da sua empresa (valem para todos os produtos)", weight="bold"),
            ft.Row([regime] + list(campos.values()), wrap=True),
            ft.Row([app.botao("Salvar parâmetros da empresa", salvar_empresa, False)]),
            ft.Text("Deste produto", weight="bold"),
            ft.Row([margem, icms], wrap=True),
            ft.Row([app.botao("Salvar preço no cadastro do produto", salvar_produto), aviso]),
        ], spacing=10)),
        cenarios,
        observacoes,
    ], spacing=12)
