"""Tela 6 — Conferência: inconsistências detectadas nos itens; o usuário marca como resolvidas.

Escopo: consulta dos alertas (JOIN de 5 tabelas) e atualização do campo `resolvido`.
Os alertas são gerados na importação (importar.py, função validar_item).
"""
import flet as ft


def listar_alertas(app, resolvido):
    return app.consultar("""
        SELECT a.id, a.mensagem, n.numero AS nf, i.numero_item, p.descricao, f.nome AS fornecedor,
               n.id AS nota_id
        FROM alertas a
        JOIN itens_nota i   ON i.id = a.item_id
        JOIN notas n        ON n.id = i.nota_id
        JOIN produtos p     ON p.id = i.produto_id
        JOIN fornecedores f ON f.id = n.fornecedor_id
        WHERE a.resolvido = ?
        ORDER BY a.id DESC
        LIMIT 300""", (1 if resolvido else 0,))


def construir(app):
    estado = {"resolvidos": False}
    lista = ft.Container()

    def montar():
        resolvidos = estado["resolvidos"]
        linhas = [[a["nf"], str(a["numero_item"]), a["descricao"][:40], a["fornecedor"], a["mensagem"],
                   ft.Row([app.botao("Reabrir" if resolvidos else "Resolver",
                                     lambda e, i=a["id"]: marcar(i, not resolvidos), False),
                           app.botao("Ver nota", lambda e, n=a["nota_id"]: app.ir("notas", nota_id=n), False)])]
                  for a in listar_alertas(app, resolvidos)]
        lista.content = app.tabela(["NF", "Item", "Produto", "Fornecedor", "Problema", ""], linhas,
                                   texto_vazio="Nenhum alerta resolvido." if resolvidos
                                   else "Nenhum alerta em aberto.")

    def marcar(alerta_id, resolvido):
        app.executar("UPDATE alertas SET resolvido = ? WHERE id = ?", (1 if resolvido else 0, alerta_id))
        montar()
        app.page.update()

    def mostrar(resolvidos):
        estado["resolvidos"] = resolvidos
        montar()
        app.page.update()

    montar()
    return ft.Column([
        app.titulo("Conferência", "Inconsistências detectadas automaticamente nos itens das notas",
                   app.botao("Em aberto", lambda e: mostrar(False), False),
                   app.botao("Resolvidos", lambda e: mostrar(True), False)),
        lista,
    ], spacing=16)
