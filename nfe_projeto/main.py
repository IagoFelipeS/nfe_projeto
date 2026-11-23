"""Tela 1 — Painel (Home) e base compartilhada do app.   Rodar com:  python main.py

Escopo deste arquivo:
  1. Constantes: título, cores, menu.
  2. Formatação de valores (R$ 1.234,50, datas, CNPJ).
  3. Peças visuais usadas por todas as telas (botão, cartão, tabela, selos...).
  4. Classe Aplicativo: janela, menu lateral, troca de tela e seletor de arquivos.
  5. A tela Painel.

As outras 6 telas ficam em importar.py, notas.py, produtos.py, fornecedores.py, alertas.py e
relatorios.py. Cada uma tem a função `construir(app, ...)`, que recebe o Aplicativo e devolve a tela.
O banco de dados (esquema e conexão) está em importar.py; o arquivo fica em banco/nfe_importador.db.
"""
import sys
from pathlib import Path

# Permite rodar tanto "python main.py" (dentro desta pasta) quanto "python nfe_projeto/main.py" (da raiz)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flet as ft

import nfe_projeto.alertas as alertas
import nfe_projeto.fornecedores as fornecedores
import nfe_projeto.importar as importar
import nfe_projeto.notas as notas
import nfe_projeto.produtos as produtos
import nfe_projeto.relatorios as relatorios
from nfe_projeto.importar import br

# =============================================================================
# 1. CONSTANTES
# =============================================================================

TITULO = "Importador de NF-e"

# Itens do menu lateral: (nome da tela, texto exibido)
MENU = [
    ("home", "Painel"),
    ("importar", "Importar XML"),
    ("notas", "Notas fiscais"),
    ("produtos", "Produtos"),
    ("fornecedores", "Fornecedores"),
    ("alertas", "Conferência"),
    ("relatorios", "Relatórios"),
]

# Código de regime tributário (CRT) do emitente, como vem no XML
REGIMES = {"1": "Simples Nacional", "2": "Simples (excesso de sublimite)", "3": "Regime normal", "4": "MEI"}


class Cor:
    """Cores do tema escuro."""
    FUNDO = "#0E1218"
    MENU_FUNDO = "#121821"
    CARTAO = "#171E28"
    TEXTO = "#E6EAF0"
    MUTED = "#8B96A8"
    AZUL = "#3B82F6"
    AZUL_SUAVE = "#1F3A6B"
    VERDE = "#34D399"
    VERDE_FUNDO = "#0F3327"
    AMBAR = "#FBBF24"
    AMBAR_FUNDO = "#3A2E0A"
    LINHA_ALERTA = "#241E0B"
    VERMELHO = "#F87171"


# =============================================================================
# 2. FORMATAÇÃO
# =============================================================================

def dinheiro(valor):
    return "—" if valor is None or valor == "" else "R$ " + br(valor)


def percentual(valor):
    return "—" if valor is None or valor == "" else br(valor) + "%"


def quantidade(valor):
    """100.0 -> '100'; 2.5 -> '2,5'."""
    texto = br(valor, 4)
    return texto.rstrip("0").rstrip(",") if "," in texto else texto


def data_br(texto):
    """'2026-11-10T09:30:00-03:00' -> '10/11/2026'."""
    partes = (texto or "")[:10].split("-")
    if len(partes) == 3:
        return f"{partes[2]}/{partes[1]}/{partes[0]}"
    return texto or "—"


def cnpj_fmt(cnpj):
    digitos = "".join(c for c in (cnpj or "") if c.isdigit())
    if len(digitos) == 14:
        return f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}"
    return cnpj or "—"


def regime_nome(crt):
    return REGIMES.get(crt, "—")


# =============================================================================
# 3. PEÇAS VISUAIS
# =============================================================================

def botao(texto, ao_clicar, primario=True):
    """Botão azul (primário) ou botão de texto (secundário). Funciona em versões diferentes do Flet."""
    if not primario:
        return ft.TextButton(texto, on_click=ao_clicar)
    classe = getattr(ft, "Button", None) or ft.ElevatedButton
    return classe(texto, on_click=ao_clicar, bgcolor=Cor.AZUL, color="white")


def cartao(conteudo, **extra):
    return ft.Container(conteudo, bgcolor=Cor.CARTAO, border_radius=12, padding=16, **extra)


def titulo(texto, subtitulo="", *acoes):
    """Cabeçalho de tela: título + subtítulo à esquerda e botões de ação à direita."""
    return ft.Row(
        [ft.Column([ft.Text(texto, size=26, weight="bold"), ft.Text(subtitulo, color=Cor.MUTED)], spacing=2),
         ft.Row(list(acoes))],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN)


def subtitulo(texto):
    return ft.Text(texto, size=16, weight="bold")


def indicador(rotulo, valor, cor=Cor.TEXTO):
    return cartao(ft.Column([ft.Text(rotulo, size=12, color=Cor.MUTED),
                             ft.Text(str(valor), size=30, weight="bold", color=cor)], spacing=2), expand=True)


def selo(texto, cor, fundo, dica=None):
    return ft.Container(ft.Text(texto, size=11, weight="bold", color=cor), bgcolor=fundo,
                        border_radius=10, padding=5, tooltip=dica)


def selo_conferencia(mensagens):
    """OK (verde) ou REVISAR (âmbar, com os motivos ao passar o mouse)."""
    if mensagens:
        return selo("REVISAR", Cor.AMBAR, Cor.AMBAR_FUNDO, "\n".join(mensagens))
    return selo("OK", Cor.VERDE, Cor.VERDE_FUNDO)


def selo_produto(status):
    if status == "cadastrado":
        return selo("CADASTRADO", Cor.VERDE, Cor.VERDE_FUNDO)
    return selo("PENDENTE", Cor.AMBAR, Cor.AMBAR_FUNDO)


def campo(rotulo, valor="", largura=None, **extra):
    return ft.TextField(label=rotulo, value=valor or "", width=largura, **extra)


def vazio(texto):
    return cartao(ft.Text(texto, color=Cor.MUTED))


def resumo_imposto(imposto):
    """'CST 00 · 18,00% · R$ 117,00' a partir de uma linha de impostos_item (ou '—' se não existir)."""
    if not imposto:
        return "—"
    partes = []
    if imposto["cst"]:
        partes.append("CST " + imposto["cst"])
    if imposto["aliquota"] is not None:
        partes.append(percentual(imposto["aliquota"]))
    if imposto["valor"] is not None:
        partes.append(dinheiro(imposto["valor"]))
    return " · ".join(partes) or "—"


def tabela(colunas, linhas, destaques=None, texto_vazio="Nenhum registro encontrado."):
    """Tabela em cartão. `linhas` é uma lista de listas (texto ou controle em cada célula).
    `destaques` é uma lista de True/False (uma por linha) para pintar a linha de âmbar."""
    if not linhas:
        return vazio(texto_vazio)
    destaques = destaques or [False] * len(linhas)
    cabecalho = [ft.DataColumn(ft.Text(c, size=12, weight="bold", color=Cor.MUTED)) for c in colunas]
    corpo = []
    for celulas, destacar in zip(linhas, destaques):
        controles = [ft.DataCell(ft.Text(c, size=13) if isinstance(c, str) else c) for c in celulas]
        corpo.append(ft.DataRow(controles, color=Cor.LINHA_ALERTA if destacar else None))
    tab = ft.DataTable(columns=cabecalho, rows=corpo, heading_row_height=44, data_row_min_height=48,
                       column_spacing=22, divider_thickness=0.5)
    return cartao(ft.Row([tab], scroll=ft.ScrollMode.AUTO))


# =============================================================================
# 4. APLICATIVO (objeto compartilhado com todas as telas)
# =============================================================================

class Aplicativo:
    """Guarda a página, a conexão com o banco e as ferramentas que as telas usam.
    Cada tela recebe este objeto como `app` (ex.: app.botao(...), app.consultar(...), app.ir(...))."""

    # cores, formatações e peças visuais disponíveis para as telas
    cor = Cor
    br = staticmethod(br)
    dinheiro = staticmethod(dinheiro)
    percentual = staticmethod(percentual)
    quantidade = staticmethod(quantidade)
    data_br = staticmethod(data_br)
    cnpj_fmt = staticmethod(cnpj_fmt)
    regime_nome = staticmethod(regime_nome)
    botao = staticmethod(botao)
    cartao = staticmethod(cartao)
    titulo = staticmethod(titulo)
    subtitulo = staticmethod(subtitulo)
    indicador = staticmethod(indicador)
    selo = staticmethod(selo)
    selo_conferencia = staticmethod(selo_conferencia)
    selo_produto = staticmethod(selo_produto)
    campo = staticmethod(campo)
    vazio = staticmethod(vazio)
    resumo_imposto = staticmethod(resumo_imposto)
    tabela = staticmethod(tabela)

    def __init__(self, page, conn):
        self.page = page
        self.conn = conn  # conexão SQLite compartilhada por todas as telas
        self.menu = ft.Column(spacing=4)
        self.area = ft.Container(expand=True, padding=24)

        # O seletor de arquivos é registrado de formas diferentes no Flet 1.x e no 0.x
        self.seletor = ft.FilePicker()
        (page.services if hasattr(ft, "run") else page.overlay).append(self.seletor)

    # ---- banco de dados

    def consultar(self, sql, params=()):
        """Executa um SELECT e devolve uma lista de dicionários."""
        return [dict(linha) for linha in self.conn.execute(sql, params).fetchall()]

    def executar(self, sql, params=()):
        """Executa INSERT/UPDATE/DELETE com commit. Devolve o id da linha inserida."""
        with self.conn:
            return self.conn.execute(sql, params).lastrowid

    # ---- navegação

    def layout(self):
        """Controle raiz: menu à esquerda, conteúdo à direita."""
        barra = ft.Container(
            ft.Column([ft.Text(TITULO, size=18, weight="bold"),
                       ft.Text("Impostos por item da NF-e", size=12, color=Cor.MUTED),
                       ft.Container(height=16), self.menu], spacing=2),
            width=240, bgcolor=Cor.MENU_FUNDO, padding=20)
        return ft.Row([barra, self.area], expand=True, spacing=0)

    def ir(self, tela, **dados):
        """Troca a tela exibida. Ex.: app.ir('notas', nota_id=3) abre o detalhe da nota 3."""
        conteudo = TELAS[tela](self, **dados)
        self.area.content = ft.Column([conteudo], scroll=ft.ScrollMode.AUTO, expand=True)
        self.menu.controls = [
            ft.Container(ft.Text(texto, weight="bold" if nome == tela else None),
                         padding=12, border_radius=8,
                         bgcolor=Cor.AZUL_SUAVE if nome == tela else None,
                         on_click=lambda e, destino=nome: self.ir(destino))
            for nome, texto in MENU]
        self.page.update()

    def escolher_arquivos(self, ao_escolher):
        """Abre a janela de seleção de XMLs e chama ao_escolher(lista_de_caminhos)."""
        opcoes = dict(dialog_title="Selecione os XMLs de NF-e", allow_multiple=True, allowed_extensions=["xml"])
        if hasattr(ft, "run"):  # Flet 1.x: seletor assíncrono
            async def abrir():
                arquivos = await self.seletor.pick_files(**opcoes)
                ao_escolher([a.path for a in arquivos or [] if a.path])
            self.page.run_task(abrir)
        else:                   # Flet 0.x: resultado chega no evento on_result
            self.seletor.on_result = lambda e: ao_escolher([a.path for a in e.files or [] if a.path])
            self.seletor.pick_files(**opcoes)


# =============================================================================
# 5. TELA 1 — PAINEL (HOME)
# =============================================================================

def painel(app):
    contagens = {
        "notas": "SELECT COUNT(*) FROM notas",
        "produtos": "SELECT COUNT(*) FROM produtos",
        "pendentes": "SELECT COUNT(*) FROM produtos WHERE status = 'pendente'",
        "alertas": "SELECT COUNT(*) FROM alertas WHERE resolvido = 0",
    }
    n = {chave: app.conn.execute(sql).fetchone()[0] for chave, sql in contagens.items()}

    ultimas = app.consultar("""
        SELECT n.id, n.numero, n.data_emissao, n.total_produtos, f.nome AS fornecedor,
               (SELECT COUNT(*) FROM itens_nota i WHERE i.nota_id = n.id) AS itens
        FROM notas n JOIN fornecedores f ON f.id = n.fornecedor_id
        ORDER BY n.id DESC
        LIMIT 5""")
    linhas = [[x["numero"], data_br(x["data_emissao"]), x["fornecedor"], dinheiro(x["total_produtos"]),
               str(x["itens"]), botao("Abrir", lambda e, i=x["id"]: app.ir("notas", nota_id=i), False)]
              for x in ultimas]

    return ft.Column([
        titulo("Painel", "Visão geral das notas importadas e dos produtos",
               botao("Importar XML", lambda e: app.ir("importar"))),
        ft.Row([indicador("Notas importadas", n["notas"]),
                indicador("Produtos", n["produtos"]),
                indicador("Produtos pendentes de cadastro", n["pendentes"], Cor.AMBAR),
                indicador("Alertas em aberto", n["alertas"], Cor.AMBAR if n["alertas"] else Cor.VERDE)],
               spacing=16),
        subtitulo("Últimas notas"),
        tabela(["NF", "Emissão", "Fornecedor", "Total", "Itens", ""], linhas,
               texto_vazio="Nenhuma nota importada ainda. Use «Importar XML» para começar."),
    ], spacing=16)


# Liga o nome de cada tela à função que a constrói (usado por Aplicativo.ir)
TELAS = {
    "home": painel,
    "importar": importar.construir,
    "notas": notas.construir,
    "produtos": produtos.construir,
    "fornecedores": fornecedores.construir,
    "alertas": alertas.construir,
    "relatorios": relatorios.construir,
}


def main(page):
    page.title = TITULO
    page.padding = 0
    page.theme_mode = "dark"
    page.bgcolor = Cor.FUNDO
    try:
        page.window.width, page.window.height = 1366, 820
    except Exception:  # versões antigas do Flet não têm page.window
        pass

    app = Aplicativo(page, importar.conectar())
    page.add(app.layout())
    app.ir("home")


if __name__ == "__main__":
    (ft.run if hasattr(ft, "run") else ft.app)(main)
