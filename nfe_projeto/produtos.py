"""Tela 4 — Produtos: catálogo vindo das notas (busca e filtro por status) e, ao abrir um produto,
a ficha com os dados cadastrais editáveis, a tributação atual e o histórico de compras.

Escopo: consultas e atualizações da tabela produtos + as duas visões (lista e ficha) da mesma tela.
"""
import flet as ft


# ----------------------------------------------------------------------------- consultas

def listar_produtos(app, busca="", status=""):
    """Produtos com fornecedor e quantidade de compras. Filtra por texto e por status."""
    like = f"%{busca.strip()}%"
    return app.consultar("""
        SELECT p.id, p.codigo, p.ean, p.descricao, p.ncm, p.cclasstrib, p.unidade, p.status,
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
    """Impostos do item mais recente comprado desse produto (é o que se leva para o cadastro)."""
    return app.consultar("""
        SELECT t.sigla, ii.cst, ii.base, ii.aliquota, ii.valor, ii.detalhe
        FROM impostos_item ii
        JOIN tributos t ON t.id = ii.tributo_id
        WHERE ii.item_id = (SELECT MAX(id) FROM itens_nota WHERE produto_id = ?)
        ORDER BY t.id""", (produto_id,))


def historico_produto(app, produto_id):
    return app.consultar("""
        SELECT n.numero, n.data_emissao, i.cfop, i.quantidade, i.valor_unitario, i.valor_total
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
                   p["cclasstrib"] or "—", p["ean"] or "—", p["unidade"], p["fornecedor"], str(p["compras"]),
                   app.botao("Ficha", lambda e, i=p["id"]: app.ir("produtos", produto_id=i), False)]
                  for p in listar_produtos(app, busca.value or "", filtro["status"])]
        lista.content = app.tabela(
            ["Status", "Código", "Descrição", "NCM", "cClassTrib", "EAN", "Un.", "Fornecedor", "Compras", ""],
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
    aviso = ft.Text("", color=app.cor.VERDE)

    def salvar(e):
        app.executar("""UPDATE produtos SET descricao = ?, ncm = ?, ean = ?, cest = ?, unidade = ?, cclasstrib = ?
                        WHERE id = ?""",
                     (descricao.value.strip() or produto["descricao"], ncm.value.strip(), ean.value.strip(),
                      cest.value.strip(), unidade.value.strip(), cclasstrib.value.strip(), produto_id))
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
        ft.Row([app.botao("Salvar alterações", salvar), app.botao(rotulo_status, alternar_status, False), aviso]),
    ], spacing=12))

    return ft.Column([
        app.titulo("Ficha do produto", "Dados para levar ao cadastro no outro sistema",
                   app.botao("Voltar", lambda e: app.ir("produtos"), False)),
        formulario,
        app.subtitulo("Tributação (item mais recente comprado)"),
        app.tabela(["Tributo", "CST / CSOSN", "Base de cálculo", "Alíquota", "Valor", "Detalhes"],
                   [[x["sigla"], x["cst"] or "—", app.dinheiro(x["base"]), app.percentual(x["aliquota"]),
                     app.dinheiro(x["valor"]), x["detalhe"] or "—"] for x in tributacao_atual(app, produto_id)],
                   texto_vazio="Sem impostos destacados."),
        app.subtitulo("Histórico de compras"),
        app.tabela(["NF", "Emissão", "CFOP", "Quantidade", "Valor unitário", "Valor total"],
                   [[h["numero"], app.data_br(h["data_emissao"]), h["cfop"], app.quantidade(h["quantidade"]),
                     app.dinheiro(h["valor_unitario"]), app.dinheiro(h["valor_total"])]
                    for h in historico_produto(app, produto_id)]),
    ], spacing=16)
