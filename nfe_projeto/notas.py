"""Tela 3 — Notas fiscais: lista das notas importadas e, ao abrir uma nota, o detalhe com
todos os impostos de cada item (ICMS, FCP, ICMS-ST, FCP-ST, DIFAL, IPI, II, PIS, COFINS, IS, IBS e CBS).

Escopo: consultas de notas/itens/impostos + as duas visões (lista e detalhe) da mesma tela.
No detalhe, só aparecem as colunas dos tributos que existem na nota aberta.
"""
import flet as ft

from nfe_projeto.importar import ORIGENS, TRIBUTOS

COLUNAS_ITEM = ["Status", "#", "Código", "Descrição", "NCM", "CFOP", "Orig.", "cClassTrib", "Qtd",
                "Valor total"]
SIGLAS = [sigla for sigla, _ in TRIBUTOS]  # ordem de exibição dos tributos


# ----------------------------------------------------------------------------- consultas

def listar_notas(app):
    """Notas com fornecedor, quantidade de itens e de itens com alerta em aberto (JOIN de 4 tabelas)."""
    return app.consultar("""
        SELECT n.id, n.numero, n.serie, n.data_emissao, n.total_produtos,
               f.nome AS fornecedor,
               COUNT(DISTINCT i.id)      AS itens,
               COUNT(DISTINCT a.item_id) AS itens_com_alerta
        FROM notas n
        JOIN fornecedores f ON f.id = n.fornecedor_id
        LEFT JOIN itens_nota i ON i.nota_id = n.id
        LEFT JOIN alertas a    ON a.item_id = i.id AND a.resolvido = 0
        GROUP BY n.id
        ORDER BY n.id DESC""")


def obter_nota(app, nota_id):
    linhas = app.consultar("""
        SELECT n.*, f.nome AS fornecedor, f.cnpj, f.regime
        FROM notas n JOIN fornecedores f ON f.id = n.fornecedor_id
        WHERE n.id = ?""", (nota_id,))
    return linhas[0] if linhas else None


def itens_da_nota(app, nota_id):
    """Itens da nota com o produto, os impostos (dicionário por sigla) e os alertas em aberto."""
    itens = app.consultar("""
        SELECT i.id, i.numero_item, i.cfop, i.cclasstrib, i.origem, i.quantidade, i.valor_unitario,
               i.valor_total,
               p.id AS produto_id, p.codigo, p.descricao, p.ncm
        FROM itens_nota i JOIN produtos p ON p.id = i.produto_id
        WHERE i.nota_id = ?
        ORDER BY i.numero_item""", (nota_id,))
    impostos = app.consultar("""
        SELECT ii.item_id, t.sigla, ii.cst, ii.base, ii.reducao_base, ii.mva, ii.aliquota, ii.valor, ii.detalhe
        FROM impostos_item ii JOIN tributos t ON t.id = ii.tributo_id
        WHERE ii.item_id IN (SELECT id FROM itens_nota WHERE nota_id = ?)""", (nota_id,))
    alertas = app.consultar("""
        SELECT item_id, mensagem FROM alertas
        WHERE resolvido = 0 AND item_id IN (SELECT id FROM itens_nota WHERE nota_id = ?)""", (nota_id,))
    for item in itens:
        item["impostos"] = {x["sigla"]: x for x in impostos if x["item_id"] == item["id"]}
        item["alertas"] = [x["mensagem"] for x in alertas if x["item_id"] == item["id"]]
    return itens


# ----------------------------------------------------------------------------- tela

def construir(app, nota_id=None):
    """Sem nota_id mostra a lista; com nota_id mostra o detalhe daquela nota."""
    return _lista(app) if nota_id is None else _detalhe(app, nota_id)


def _lista(app):
    linhas, destaques = [], []
    for n in listar_notas(app):
        if n["itens_com_alerta"]:
            situacao = app.selo(f"{n['itens_com_alerta']} p/ revisar", app.cor.AMBAR, app.cor.AMBAR_FUNDO)
        else:
            situacao = app.selo("OK", app.cor.VERDE, app.cor.VERDE_FUNDO)
        linhas.append([situacao, n["numero"], n["serie"], app.data_br(n["data_emissao"]), n["fornecedor"],
                       app.dinheiro(n["total_produtos"]), str(n["itens"]),
                       app.botao("Abrir", lambda e, i=n["id"]: app.ir("notas", nota_id=i), False)])
        destaques.append(n["itens_com_alerta"] > 0)

    return ft.Column([
        app.titulo("Notas fiscais", "NF-e importadas"),
        app.tabela(["Situação", "NF", "Série", "Emissão", "Fornecedor", "Total produtos", "Itens", ""],
                   linhas, destaques, "Nenhuma nota importada ainda."),
    ], spacing=16)


def _detalhe(app, nota_id):
    nota = obter_nota(app, nota_id)
    if nota is None:
        return app.vazio("Nota não encontrada.")

    itens = itens_da_nota(app, nota_id)
    presentes = [s for s in SIGLAS if any(s in it["impostos"] for it in itens)]  # só tributos desta nota
    linhas, destaques = [], []
    for it in itens:
        descricao = ft.TextButton(it["descricao"][:38], tooltip="Abrir ficha do produto",
                                  on_click=lambda e, p=it["produto_id"]: app.ir("produtos", produto_id=p))
        origem = ft.Text(it["origem"] or "—", size=13, tooltip=ORIGENS.get(it["origem"]))
        linhas.append([app.selo_conferencia(it["alertas"]), str(it["numero_item"]), it["codigo"], descricao,
                       it["ncm"], it["cfop"], origem, it["cclasstrib"] or "—", app.quantidade(it["quantidade"]),
                       app.dinheiro(it["valor_total"])]
                      + [app.resumo_imposto(it["impostos"].get(s)) for s in presentes])
        destaques.append(bool(it["alertas"]))

    # Exclusão em dois passos (pergunta antes de apagar)
    pergunta = ft.Row([ft.Text("Excluir esta nota e seus itens?"),
                       app.botao("Sim, excluir", lambda e: excluir()),
                       app.botao("Cancelar", lambda e: alternar(False), False)], visible=False)
    abrir_exclusao = app.botao("Excluir nota", lambda e: alternar(True), False)

    def alternar(perguntando):
        pergunta.visible, abrir_exclusao.visible = perguntando, not perguntando
        app.page.update()

    def excluir():
        app.executar("DELETE FROM notas WHERE id = ?", (nota_id,))  # itens, impostos e alertas saem em cascata
        app.ir("notas")

    dados = ft.Column([
        ft.Text(f"{nota['fornecedor']}  ·  CNPJ {app.cnpj_fmt(nota['cnpj'])}  ·  {app.regime_nome(nota['regime'])}"),
        ft.Text(f"Emissão {app.data_br(nota['data_emissao'])}  ·  {nota['natureza_op'] or '—'}  ·  "
                f"Total {app.dinheiro(nota['total_produtos'])}", color=app.cor.MUTED),
        ft.Text(f"Chave de acesso: {nota['chave']}", size=12, color=app.cor.MUTED, selectable=True),
    ], spacing=4)

    return ft.Column([
        app.titulo(f"NF {nota['numero']}", f"Série {nota['serie'] or '—'}",
                   app.botao("Voltar", lambda e: app.ir("notas"), False), abrir_exclusao, pergunta),
        app.cartao(dados),
        app.tabela(COLUNAS_ITEM + presentes, linhas, destaques, "Esta nota não tem itens."),
    ], spacing=16)
