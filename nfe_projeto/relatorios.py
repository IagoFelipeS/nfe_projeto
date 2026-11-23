"""Tela 7 — Relatórios: totais por tributo e por fornecedor.

Escopo: duas consultas com JOIN e GROUP BY que somam os impostos destacados nas notas.
"""
import flet as ft


def relatorio_por_tributo(app):
    """Totais por tributo: quantos itens, soma das bases e soma dos valores."""
    return app.consultar("""
        SELECT t.sigla, t.nome, COUNT(ii.id) AS itens,
               COALESCE(SUM(ii.base), 0) AS base_total, COALESCE(SUM(ii.valor), 0) AS valor_total
        FROM tributos t LEFT JOIN impostos_item ii ON ii.tributo_id = t.id
        GROUP BY t.id
        ORDER BY t.id""")


def relatorio_por_fornecedor(app):
    """Por fornecedor: notas, itens, valor das mercadorias e soma de todos os impostos destacados."""
    return app.consultar("""
        SELECT f.nome,
               COUNT(DISTINCT n.id) AS notas,
               COUNT(DISTINCT i.id) AS itens,
               (SELECT COALESCE(SUM(i2.valor_total), 0)
                  FROM itens_nota i2 JOIN notas n2 ON n2.id = i2.nota_id
                 WHERE n2.fornecedor_id = f.id) AS mercadorias,
               COALESCE(SUM(ii.valor), 0) AS impostos
        FROM fornecedores f
        JOIN notas n ON n.fornecedor_id = f.id
        JOIN itens_nota i ON i.nota_id = n.id
        LEFT JOIN impostos_item ii ON ii.item_id = i.id
        GROUP BY f.id
        ORDER BY impostos DESC""")


def construir(app):
    por_tributo = [[t["sigla"], t["nome"], str(t["itens"]), app.dinheiro(t["base_total"]),
                    app.dinheiro(t["valor_total"])] for t in relatorio_por_tributo(app)]
    por_fornecedor = [[f["nome"], str(f["notas"]), str(f["itens"]), app.dinheiro(f["mercadorias"]),
                       app.dinheiro(f["impostos"])] for f in relatorio_por_fornecedor(app)]
    return ft.Column([
        app.titulo("Relatórios", "Impostos destacados nas notas importadas"),
        app.subtitulo("Total por tributo"),
        app.tabela(["Tributo", "Descrição", "Itens", "Base de cálculo", "Valor destacado"], por_tributo),
        app.subtitulo("Total por fornecedor"),
        app.tabela(["Fornecedor", "Notas", "Itens", "Mercadorias", "Impostos destacados"], por_fornecedor,
                   texto_vazio="Importe notas para ver o relatório."),
    ], spacing=16)
