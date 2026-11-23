"""Tela 5 — Fornecedores (cadastro): lista, edita o nome e exclui fornecedores sem vínculos.

Escopo: consultas e atualizações da tabela fornecedores. A exclusão mostra a integridade referencial:
o banco recusa apagar um fornecedor que ainda tem notas ou produtos (chave estrangeira).
"""
import sqlite3

import flet as ft


def listar_fornecedores(app):
    return app.consultar("""
        SELECT f.id, f.nome, f.cnpj, f.regime,
               COUNT(DISTINCT n.id) AS notas,
               (SELECT COUNT(*) FROM produtos p WHERE p.fornecedor_id = f.id) AS produtos
        FROM fornecedores f LEFT JOIN notas n ON n.fornecedor_id = f.id
        GROUP BY f.id
        ORDER BY f.nome""")


def excluir_fornecedor(app, fornecedor_id):
    """True se excluiu; False se o fornecedor tem notas/produtos (a chave estrangeira impede)."""
    try:
        app.executar("DELETE FROM fornecedores WHERE id = ?", (fornecedor_id,))
        return True
    except sqlite3.IntegrityError:
        return False


def construir(app):
    editando = {"id": None}
    nome = app.campo("Nome do fornecedor", largura=440)
    aviso = ft.Text("")
    lista = ft.Container()

    def abrir(fornecedor):
        editando["id"] = fornecedor["id"]
        nome.value = fornecedor["nome"]
        formulario.visible = True
        aviso.value = ""
        app.page.update()

    def fechar(e=None):
        editando["id"] = None
        formulario.visible = False
        app.page.update()

    def salvar(e):
        if not (nome.value or "").strip():
            aviso.value, aviso.color = "Informe o nome.", app.cor.AMBAR
        else:
            app.executar("UPDATE fornecedores SET nome = ? WHERE id = ?", (nome.value.strip(), editando["id"]))
            editando["id"] = None
            formulario.visible = False
            aviso.value, aviso.color = "Fornecedor atualizado.", app.cor.VERDE
            montar()
        app.page.update()

    def excluir(fornecedor):
        if excluir_fornecedor(app, fornecedor["id"]):
            aviso.value, aviso.color = "Fornecedor excluído.", app.cor.VERDE
        else:
            aviso.value = "Não é possível excluir: o fornecedor tem notas ou produtos vinculados."
            aviso.color = app.cor.AMBAR
        montar()
        app.page.update()

    def montar():
        linhas = [[f["nome"], app.cnpj_fmt(f["cnpj"]), app.regime_nome(f["regime"]), str(f["notas"]),
                   str(f["produtos"]),
                   ft.Row([app.botao("Editar", lambda e, x=f: abrir(x), False),
                           app.botao("Excluir", lambda e, x=f: excluir(x), False)])]
                  for f in listar_fornecedores(app)]
        lista.content = app.tabela(["Nome", "CNPJ", "Regime", "Notas", "Produtos", ""], linhas,
                                   texto_vazio="Nenhum fornecedor ainda. Eles são criados ao importar as notas.")

    formulario = app.cartao(ft.Row([nome, app.botao("Salvar", salvar), app.botao("Cancelar", fechar, False)]),
                            visible=False)
    montar()
    return ft.Column([app.titulo("Fornecedores", "Emitentes das notas importadas"), aviso, formulario, lista],
                     spacing=16)
