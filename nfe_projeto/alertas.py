"""Tela 6 — Conferência: inconsistências detectadas nos itens; o usuário marca como resolvidas.

Escopo: consulta dos alertas (JOIN de 5 tabelas) e atualização do campo `resolvido`.
Os alertas são gerados na importação: regras gerais em importar.py (validar_item) e regras da reforma
tributária (IBS/CBS) em reforma.py. Os da reforma começam com "Reforma:" e podem ser filtrados aqui.
"""
import flet as ft

PREFIXO_REFORMA = "Reforma: "


def listar_alertas(app, resolvido, tipo=""):
    """tipo: '' (todos), 'reforma' (IBS/CBS) ou 'geral' (demais regras)."""
    return app.consultar("""
        SELECT a.id, a.mensagem, n.numero AS nf, i.numero_item, p.descricao, f.nome AS fornecedor,
               n.id AS nota_id
        FROM alertas a
        JOIN itens_nota i   ON i.id = a.item_id
        JOIN notas n        ON n.id = i.nota_id
        JOIN produtos p     ON p.id = i.produto_id
        JOIN fornecedores f ON f.id = n.fornecedor_id
        WHERE a.resolvido = ?
          AND (? = '' OR (? = 'reforma') = (a.mensagem LIKE 'Reforma:%'))
        ORDER BY a.id DESC
        LIMIT 300""", (1 if resolvido else 0, tipo, tipo))


def construir(app):
    estado = {"resolvidos": False, "tipo": ""}
    lista = ft.Container()
    rotulo = ft.Text("", color=app.cor.MUTED)

    def selo_tipo(mensagem):
        if mensagem.startswith(PREFIXO_REFORMA):
            return app.selo("REFORMA", app.cor.AZUL, app.cor.AZUL_SUAVE, "Regra do IBS/CBS (reforma tributária)")
        return app.selo("GERAL", app.cor.MUTED, app.cor.CARTAO)

    def montar():
        resolvidos = estado["resolvidos"]
        alertas = listar_alertas(app, resolvidos, estado["tipo"])
        linhas = [[selo_tipo(a["mensagem"]), a["nf"], str(a["numero_item"]), a["descricao"][:32],
                   ft.Text(a["mensagem"].removeprefix(PREFIXO_REFORMA), size=13, width=520),
                   ft.Row([app.botao("Reabrir" if resolvidos else "Resolver",
                                     lambda e, i=a["id"]: marcar(i, not resolvidos), False),
                           app.botao("Ver nota", lambda e, n=a["nota_id"]: app.ir("notas", nota_id=n), False)])]
                  for a in alertas]
        nomes = {"": "todos os tipos", "reforma": "reforma tributária", "geral": "regras gerais"}
        rotulo.value = (f"{len(alertas)} alerta(s) {'resolvido(s)' if resolvidos else 'em aberto'} · "
                        f"{nomes[estado['tipo']]}")
        lista.content = app.tabela(["Tipo", "NF", "Item", "Produto", "Problema", ""], linhas,
                                   texto_vazio="Nenhum alerta resolvido." if resolvidos
                                   else "Nenhum alerta em aberto.", altura_linha=64)

    def marcar(alerta_id, resolvido):
        app.executar("UPDATE alertas SET resolvido = ? WHERE id = ?", (1 if resolvido else 0, alerta_id))
        montar()
        app.page.update()

    def mudar(**novo):
        estado.update(novo)
        montar()
        app.page.update()

    montar()
    return ft.Column([
        app.titulo("Conferência", "Inconsistências detectadas automaticamente nos itens das notas",
                   app.botao("Em aberto", lambda e: mudar(resolvidos=False), False),
                   app.botao("Resolvidos", lambda e: mudar(resolvidos=True), False)),
        ft.Row([ft.Text("Tipo:"),
                app.botao("Todos", lambda e: mudar(tipo=""), False),
                app.botao("Reforma tributária (IBS/CBS)", lambda e: mudar(tipo="reforma"), False),
                app.botao("Regras gerais", lambda e: mudar(tipo="geral"), False),
                rotulo]),
        lista,
    ], spacing=16)
