"""Tela 4 — Produtos: catálogo vindo das notas (busca e filtro por status) e, ao abrir um produto,
a ficha em abas: Cadastro (dados editáveis), Impostos (tributação da última compra), Compras
(histórico) e Preço (preço de venda sugerido).

Escopo: consultas e atualizações da tabela produtos + as duas visões (lista e ficha) da mesma tela.
"""
import flet as ft

from nfe_projeto.importar import ORIGENS, TRIBUTOS

SIGLAS = [sigla for sigla, _ in TRIBUTOS]
IMPOSTOS_VENDA_PADRAO = 8.0   # % de impostos sobre a venda sugerido quando o produto ainda não tem
MARGEM_PADRAO = 30.0          # % de lucro sobre o preço sugerido quando o produto ainda não tem


# ----------------------------------------------------------------------------- consultas

def listar_produtos(app, busca="", status=""):
    """Produtos com fornecedor. Filtra por texto (descrição, código, NCM, EAN, cClassTrib) e por status."""
    like = f"%{busca.strip()}%"
    return app.consultar("""
        SELECT p.id, p.codigo, p.descricao, p.ncm, p.status, p.preco_venda, f.nome AS fornecedor
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
    """Impostos do item mais recente comprado desse produto, na ordem do catálogo de tributos."""
    linhas = app.consultar("""
        SELECT t.sigla, ii.cst, ii.base, ii.reducao_base, ii.mva, ii.aliquota, ii.valor, ii.detalhe
        FROM impostos_item ii
        JOIN tributos t ON t.id = ii.tributo_id
        WHERE ii.item_id = (SELECT MAX(id) FROM itens_nota WHERE produto_id = ?)""", (produto_id,))
    return sorted(linhas, key=lambda x: SIGLAS.index(x["sigla"]) if x["sigla"] in SIGLAS else len(SIGLAS))


def ultima_compra(app, produto_id):
    """Item mais recente do produto (CFOP, benefício fiscal, quantidade e valores)."""
    linhas = app.consultar("""
        SELECT cfop, cbenef, quantidade, valor_unitario, valor_total, frete, seguro, desconto, outras
        FROM itens_nota
        WHERE id = (SELECT MAX(id) FROM itens_nota WHERE produto_id = ?)""", (produto_id,))
    return linhas[0] if linhas else None


def historico_produto(app, produto_id):
    return app.consultar("""
        SELECT n.numero, n.data_emissao, i.cfop, i.quantidade, i.valor_unitario, i.valor_total,
               i.frete, i.desconto
        FROM itens_nota i JOIN notas n ON n.id = i.nota_id
        WHERE i.produto_id = ?
        ORDER BY n.id DESC""", (produto_id,))


def custo_unitario(compra, impostos):
    """Quanto custou cada unidade: produto + frete + seguro + outras − desconto + IPI + ICMS-ST + FCP-ST,
    dividido pela quantidade. IPI e ST entram porque são pagos ao fornecedor por fora do valor do produto."""
    def n(valor):
        return valor or 0.0

    def imposto(sigla):
        return n((impostos.get(sigla) or {}).get("valor"))

    total = (n(compra["valor_total"]) + n(compra["frete"]) + n(compra["seguro"]) + n(compra["outras"])
             - n(compra["desconto"]) + imposto("IPI") + imposto("ICMS-ST") + imposto("FCP-ST"))
    return total / (compra["quantidade"] or 1)


def preco_venda(custo, impostos_venda, margem):
    """Markup divisor: o preço precisa cobrir o custo, os impostos da venda e o lucro (ambos em % do preço).
    Devolve None quando impostos + margem chegam a 100% (não existe preço que cubra)."""
    soma = impostos_venda + margem
    return None if soma >= 100 else custo / (1 - soma / 100)


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
        linhas = [[app.selo_produto(p["status"]), p["codigo"], p["descricao"][:48], p["ncm"], p["fornecedor"],
                   app.dinheiro(p["preco_venda"]),
                   app.botao("Ficha", lambda e, i=p["id"]: app.ir("produtos", produto_id=i), False)]
                  for p in listar_produtos(app, busca.value or "", filtro["status"])]
        lista.content = app.tabela(["Status", "Código", "Descrição", "NCM", "Fornecedor", "Preço de venda", ""],
                                   linhas, texto_vazio="Nenhum produto encontrado. Importe uma NF-e para criá-los.")

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
    compra = ultima_compra(app, produto_id)
    tributos = tributacao_atual(app, produto_id)

    return ft.Column([
        app.titulo(produto["descricao"][:60], f"Código {produto['codigo']}  ·  {produto['fornecedor']}",
                   app.botao("Voltar", lambda e: app.ir("produtos"), False)),
        app.abas([
            ("Cadastro", _aba_cadastro(app, produto)),
            ("Impostos", _aba_impostos(app, compra, tributos)),
            ("Compras", _aba_compras(app, produto_id)),
            ("Preço de venda", _aba_preco(app, produto, compra, {x["sigla"]: x for x in tributos})),
        ]),
    ], spacing=16)


def _aba_cadastro(app, produto):
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
                      produto["id"]))
        aviso.value = "Dados salvos."
        app.page.update()

    def alternar_status(e):
        novo = "pendente" if produto["status"] == "cadastrado" else "cadastrado"
        app.executar("UPDATE produtos SET status = ? WHERE id = ?", (novo, produto["id"]))
        app.ir("produtos", produto_id=produto["id"])

    rotulo_status = ("Voltar para pendente" if produto["status"] == "cadastrado"
                     else "Marcar como cadastrado no sistema de destino")
    return app.cartao(ft.Column([
        app.selo_produto(produto["status"]),
        descricao,
        ft.Row([ncm, ean, cest, unidade, cclasstrib], wrap=True),
        origem,
        ft.Row([app.botao("Salvar alterações", salvar), app.botao(rotulo_status, alternar_status, False), aviso]),
    ], spacing=12))


def _aba_impostos(app, compra, tributos):
    if compra is None:
        return app.vazio("Este produto não tem compras.")
    return ft.Column([
        ft.Text(f"Tributação da compra mais recente  ·  CFOP {compra['cfop'] or '—'}  ·  "
                f"benefício fiscal (cBenef) {compra['cbenef'] or '—'}", color=app.cor.MUTED),
        app.tabela(["Tributo", "CST / CSOSN", "Base de cálculo", "Redução da base", "MVA", "Alíquota", "Valor",
                    "Detalhes"],
                   [[x["sigla"], x["cst"] or "—", app.dinheiro(x["base"]), app.percentual(x["reducao_base"]),
                     app.percentual(x["mva"]), app.percentual(x["aliquota"]), app.dinheiro(x["valor"]),
                     x["detalhe"] or "—"] for x in tributos],
                   texto_vazio="Sem impostos destacados."),
    ], spacing=12)


def _aba_compras(app, produto_id):
    def valor_ou_traco(valor):
        return app.dinheiro(valor) if valor else "—"

    return app.tabela(["NF", "Emissão", "CFOP", "Quantidade", "Valor unitário", "Valor total", "Frete", "Desconto"],
                      [[h["numero"], app.data_br(h["data_emissao"]), h["cfop"], app.quantidade(h["quantidade"]),
                        app.dinheiro(h["valor_unitario"]), app.dinheiro(h["valor_total"]),
                        valor_ou_traco(h["frete"]), valor_ou_traco(h["desconto"])]
                       for h in historico_produto(app, produto_id)],
                      texto_vazio="Este produto não tem compras.")


def _aba_preco(app, produto, compra, impostos):
    """Preço = custo ÷ (1 − (impostos na venda % + margem %)). Recalcula ao digitar; o botão grava no produto."""
    if compra is None:
        return app.vazio("Sem compras para calcular o preço.")
    custo = custo_unitario(compra, impostos)

    def numero(campo):
        try:
            return float((campo.value or "").replace(",", "."))
        except ValueError:
            return None

    def texto(valor):
        return app.br(valor).replace(".", "")

    impostos_venda = app.campo("Impostos na venda (%)", texto(produto["impostos_venda"] or IMPOSTOS_VENDA_PADRAO),
                               200, on_change=lambda e: recalcular())
    margem = app.campo("Margem de lucro (%)", texto(produto["margem"] or MARGEM_PADRAO), 200,
                       on_change=lambda e: recalcular())
    valor_impostos, valor_lucro = ft.Text(""), ft.Text("")
    preco = ft.Text("", size=26, weight="bold", color=app.cor.VERDE)
    aviso = ft.Text("", color=app.cor.VERDE)
    resultado = {"preco": None}

    def recalcular(atualizar=True):
        imp, marg = numero(impostos_venda), numero(margem)
        valor = preco_venda(custo, imp, marg) if None not in (imp, marg) else None
        resultado["preco"] = valor
        if valor is None:
            valor_impostos.value = valor_lucro.value = "—"
            preco.value = "Impostos + margem precisam somar menos de 100%" if None not in (imp, marg) \
                else "Digite números nos dois campos"
            preco.color, preco.size = app.cor.AMBAR, 14
        else:
            valor_impostos.value = app.dinheiro(valor * imp / 100)
            valor_lucro.value = app.dinheiro(valor * marg / 100)
            preco.value, preco.color, preco.size = app.dinheiro(valor), app.cor.VERDE, 26
        aviso.value = ""
        if atualizar:
            app.page.update()

    def salvar(e):
        if resultado["preco"] is None:
            return
        app.executar("UPDATE produtos SET impostos_venda = ?, margem = ?, preco_venda = ? WHERE id = ?",
                     (numero(impostos_venda), numero(margem), round(resultado["preco"], 2), produto["id"]))
        aviso.value = "Preço salvo no cadastro do produto."
        app.page.update()

    def linha(rotulo, valor, explicacao=""):
        coluna = [ft.Text(rotulo)] + ([ft.Text(explicacao, size=11, color=app.cor.MUTED)] if explicacao else [])
        return ft.Row([ft.Column(coluna, spacing=0, expand=True), valor])

    recalcular(atualizar=False)
    return app.cartao(ft.Column([
        linha("Custo por unidade", ft.Text(app.dinheiro(custo)),
              "produto + frete + IPI + ICMS-ST − desconto, dividido pela quantidade da última compra"),
        ft.Row([impostos_venda, margem], wrap=True),
        linha("Impostos na venda", valor_impostos),
        linha("Lucro", valor_lucro),
        ft.Divider(height=8),
        linha("Preço de venda por unidade", preco),
        ft.Row([app.botao("Salvar preço no produto", salvar), aviso]),
    ], spacing=12), width=560)
