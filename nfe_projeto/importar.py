"""Tela 2 — Importar XML. Também concentra o banco de dados e a leitura da NF-e.

Escopo deste arquivo:
  1. BANCO: esquema SQLite (8 tabelas, PKs e FKs 1:N) e conexão.
  2. XML: lê a NF-e e extrai produto + impostos de cada item.
  3. CONFERÊNCIA: regras que geram os alertas de cada item.
  4. IMPORTAÇÃO: grava tudo em uma transação e registra o histórico.
  5. TELA: escolher os XMLs e mostrar o resultado e o histórico.

Relacionamentos 1:N (pai -> filhos):
    fornecedores -> notas            fornecedores -> produtos
    notas        -> itens_nota       produtos     -> itens_nota
    itens_nota   -> impostos_item    itens_nota   -> alertas
    tributos     -> impostos_item    notas        -> importacoes
"""
import sqlite3
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from pathlib import Path

import flet as ft

# Arquivo do banco SQLite: pasta banco/ na raiz do projeto
BANCO = Path(__file__).resolve().parent.parent / "banco" / "nfe_importador.db"

# Catálogo de tributos (vira a tabela `tributos`)
TRIBUTOS = [
    ("ICMS", "Imposto sobre Circulação de Mercadorias e Serviços"),
    ("ICMS-ST", "ICMS por Substituição Tributária"),
    ("IPI", "Imposto sobre Produtos Industrializados"),
    ("PIS", "Programa de Integração Social"),
    ("COFINS", "Contribuição para o Financiamento da Seguridade Social"),
    ("IBS", "Imposto sobre Bens e Serviços (reforma tributária)"),
    ("CBS", "Contribuição sobre Bens e Serviços (reforma tributária)"),
]


# =============================================================================
# 1. BANCO DE DADOS
# =============================================================================

ESQUEMA = """
CREATE TABLE IF NOT EXISTS fornecedores (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj    TEXT NOT NULL UNIQUE,
    nome    TEXT NOT NULL,
    regime  TEXT NOT NULL DEFAULT ''            -- CRT do emitente (1, 2, 3 ou 4)
);

CREATE TABLE IF NOT EXISTS notas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fornecedor_id   INTEGER NOT NULL REFERENCES fornecedores(id),
    chave           TEXT NOT NULL UNIQUE,       -- chave de acesso de 44 dígitos
    numero          TEXT NOT NULL DEFAULT '',
    serie           TEXT NOT NULL DEFAULT '',
    data_emissao    TEXT NOT NULL DEFAULT '',
    natureza_op     TEXT NOT NULL DEFAULT '',
    total_produtos  REAL,
    arquivo         TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS produtos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    fornecedor_id  INTEGER NOT NULL REFERENCES fornecedores(id),
    codigo         TEXT NOT NULL,               -- código do produto no fornecedor
    ean            TEXT NOT NULL DEFAULT '',
    descricao      TEXT NOT NULL,
    ncm            TEXT NOT NULL DEFAULT '',
    cest           TEXT NOT NULL DEFAULT '',
    unidade        TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente', 'cadastrado')),
    UNIQUE (fornecedor_id, codigo)
);

CREATE TABLE IF NOT EXISTS itens_nota (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nota_id         INTEGER NOT NULL REFERENCES notas(id) ON DELETE CASCADE,
    produto_id      INTEGER NOT NULL REFERENCES produtos(id),
    numero_item     INTEGER NOT NULL,
    cfop            TEXT NOT NULL DEFAULT '',
    quantidade      REAL,
    valor_unitario  REAL,
    valor_total     REAL,
    grupo_icms      TEXT NOT NULL DEFAULT ''    -- ex.: ICMS00, ICMSSN102
);

CREATE TABLE IF NOT EXISTS tributos (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    sigla  TEXT NOT NULL UNIQUE,                -- ICMS, ICMS-ST, IPI, PIS, COFINS, IBS, CBS
    nome   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS impostos_item (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id     INTEGER NOT NULL REFERENCES itens_nota(id) ON DELETE CASCADE,
    tributo_id  INTEGER NOT NULL REFERENCES tributos(id),
    cst         TEXT NOT NULL DEFAULT '',       -- CST ou CSOSN
    base        REAL,
    aliquota    REAL,
    valor       REAL,
    detalhe     TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS alertas (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id    INTEGER NOT NULL REFERENCES itens_nota(id) ON DELETE CASCADE,
    mensagem   TEXT NOT NULL,
    resolvido  INTEGER NOT NULL DEFAULT 0 CHECK (resolvido IN (0, 1))
);

CREATE TABLE IF NOT EXISTS importacoes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    arquivo    TEXT NOT NULL,
    data_hora  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    resultado  TEXT NOT NULL CHECK (resultado IN ('ok', 'duplicada', 'erro')),
    mensagem   TEXT NOT NULL DEFAULT '',
    nota_id    INTEGER REFERENCES notas(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_notas_fornecedor ON notas(fornecedor_id);
CREATE INDEX IF NOT EXISTS idx_itens_nota ON itens_nota(nota_id);
CREATE INDEX IF NOT EXISTS idx_itens_produto ON itens_nota(produto_id);
CREATE INDEX IF NOT EXISTS idx_impostos_item ON impostos_item(item_id);
CREATE INDEX IF NOT EXISTS idx_alertas_item ON alertas(item_id);
"""


def conectar(caminho=BANCO):
    """Abre o banco (criando a pasta, as tabelas e o catálogo de tributos na primeira vez)."""
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(caminho), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # SQLite só respeita FKs se isto estiver ligado
    conn.executescript(ESQUEMA)
    conn.executemany("INSERT OR IGNORE INTO tributos (sigla, nome) VALUES (?, ?)", TRIBUTOS)
    conn.commit()
    return conn


# =============================================================================
# 2. LEITURA DO XML DA NF-e
# =============================================================================
# Os valores saem do XML como TEXTO; a conversão para número é feita só na hora de gravar.

def para_decimal(texto):
    """'18.0000' -> Decimal('18.0000'). Devolve None se não for número."""
    try:
        return Decimal(texto)
    except (InvalidOperation, TypeError, ValueError):
        return None


def como_float(texto):
    """Texto do XML -> float para gravar no banco (None se vazio/inválido)."""
    numero = para_decimal(texto)
    return float(numero) if numero is not None else None


def br(valor, casas=2):
    """1234.5 -> '1.234,50'. Vazio ou None -> '—'."""
    if valor is None or valor == "":
        return "—"
    numero = para_decimal(str(valor))
    if numero is None:
        return str(valor)
    return f"{numero:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def t(el, *tags):
    """Texto da primeira tag encontrada (em qualquer nível) dentro de `el`."""
    if el is not None:
        for tag in tags:
            valor = (el.findtext(f".//{tag}") or "").strip()
            if valor:
                return valor
    return ""


def ler_nfe(caminho):
    """Devolve (cabecalho, itens). Levanta ValueError se o arquivo não for uma NF-e válida."""
    bruto = Path(caminho).read_bytes()
    if b"<!DOCTYPE" in bruto.upper() or b"<!ENTITY" in bruto.upper():
        raise ValueError("XML com DOCTYPE/ENTITY não é aceito")
    try:
        raiz = ET.fromstring(bruto)
    except ET.ParseError as erro:
        raise ValueError(f"XML malformado: {erro}")
    for el in raiz.iter():  # tira o namespace (http://www.portalfiscal.inf.br/nfe) das tags
        if isinstance(el.tag, str):
            el.tag = el.tag.rpartition("}")[2]

    inf = raiz if raiz.tag == "infNFe" else raiz.find(".//infNFe")
    if inf is None or not inf.findall("det"):
        raise ValueError("não é uma NF-e (sem <infNFe> ou sem itens)")
    chave = inf.get("Id", "").replace("NFe", "", 1)
    if not chave:
        raise ValueError("NF-e sem chave de acesso")

    emit = inf.find("emit")
    cabecalho = {
        "chave": chave,
        "numero": t(inf, "nNF"),
        "serie": t(inf, "serie"),
        "data_emissao": t(inf, "dhEmi", "dEmi"),
        "natureza_op": t(inf, "natOp"),
        "total_produtos": t(inf.find("total"), "vProd"),
        "cnpj": t(emit, "CNPJ", "CPF"),
        "emitente": t(emit, "xNome"),
        "crt": t(emit, "CRT"),
    }
    return cabecalho, [_ler_item(det) for det in inf.findall("det")]


def _ler_item(det):
    prod, imp = det.find("prod"), det.find("imposto")
    ean = t(prod, "cEAN")
    icms = imp.find("ICMS") if imp is not None else None
    try:
        numero = int(det.get("nItem", "0"))
    except ValueError:
        raise ValueError("número de item inválido no XML")
    return {
        "n": numero,
        "cod": t(prod, "cProd"),
        "ean": "" if ean.upper() == "SEM GTIN" else ean,
        "desc": t(prod, "xProd"),
        "ncm": t(prod, "NCM"),
        "cest": t(prod, "CEST"),
        "cfop": t(prod, "CFOP"),
        "un": t(prod, "uCom"),
        "qtd": t(prod, "qCom"),
        "vun": t(prod, "vUnCom"),
        "vtot": t(prod, "vProd"),
        "icms_grupo": icms[0].tag if icms is not None and len(icms) else "",
        "impostos": _impostos(imp, det.find(".//IBSCBS")),
    }


def _imposto(sigla, cst="", base="", aliq="", valor="", detalhe=""):
    return {"sigla": sigla, "cst": cst, "base": base, "aliq": aliq, "valor": valor, "detalhe": detalhe}


def _impostos(imp, ibs):
    """Lista de impostos do item, um dicionário por tributo presente no XML."""
    lista = []
    if imp is not None:
        lista += _icms(imp.find("ICMS"))
        ipi = imp.find("IPI")
        if t(ipi, "CST"):
            enq = t(ipi, "cEnq")
            lista.append(_imposto("IPI", t(ipi, "CST"), t(ipi, "vBC"), t(ipi, "pIPI"), t(ipi, "vIPI"),
                                  f"enquadramento {enq}" if enq else ""))
        for sigla in ("PIS", "COFINS"):
            grupo = imp.find(sigla)
            if t(grupo, "CST"):
                lista.append(_imposto(sigla, t(grupo, "CST"), t(grupo, "vBC"), t(grupo, f"p{sigla}"),
                                      t(grupo, f"v{sigla}")))
    lista += _ibs_cbs(ibs)
    return lista


def _icms(icms):
    if icms is None or not len(icms):
        return []
    detalhe = icms[0].tag
    if t(icms, "vCredICMSSN"):
        detalhe += f" · crédito Simples R$ {br(t(icms, 'vCredICMSSN'))}"
    if t(icms, "pRedBC"):
        detalhe += f" · redução da base {br(t(icms, 'pRedBC'))}%"
    cst = t(icms, "CST", "CSOSN")  # CST (regime normal) ou CSOSN (Simples)
    lista = [_imposto("ICMS", cst, t(icms, "vBC"), t(icms, "pICMS"), t(icms, "vICMS"), detalhe)]
    st_base, st_aliq = t(icms, "vBCST", "vBCSTRet"), t(icms, "pICMSST", "pST")
    st_valor = t(icms, "vICMSST", "vICMSSTRet")
    if st_base or st_aliq or st_valor:
        mva = t(icms, "pMVAST")
        lista.append(_imposto("ICMS-ST", cst, st_base, st_aliq, st_valor, f"MVA {br(mva)}%" if mva else ""))
    return lista


def _ibs_cbs(ibs):
    """IBS e CBS (reforma tributária). Busca as tags em qualquer nível porque o leiaute ainda evolui."""
    if ibs is None:
        return []
    cst, base = t(ibs, "CST"), t(ibs, "vBC")
    uf, mun = t(ibs, "pIBSUF"), t(ibs, "pIBSMun")
    aliq_ibs = ""
    if uf or mun:
        aliq_ibs = str(sum((para_decimal(x) or Decimal(0) for x in (uf, mun)), Decimal(0)))
    partes = []
    if t(ibs, "cClassTrib"):
        partes.append(f"cClassTrib {t(ibs, 'cClassTrib')}")
    if uf:
        partes.append(f"UF {br(uf)}%")
    if mun:
        partes.append(f"Mun. {br(mun)}%")
    return [
        _imposto("IBS", cst, base, aliq_ibs, t(ibs, "vIBS"), " · ".join(partes)),
        _imposto("CBS", cst, base, t(ibs, "pCBS"), t(ibs, "vCBS")),
    ]


# =============================================================================
# 3. CONFERÊNCIA (gera os alertas)
# =============================================================================

TOLERANCIA = Decimal("0.02")  # diferença aceita por arredondamento


def _bate(base, aliq, valor):
    """True se base x alíquota/100 for igual ao valor (ou se faltar dado para conferir)."""
    b, a, v = para_decimal(base), para_decimal(aliq), para_decimal(valor)
    if b is None or a is None or v is None:
        return True
    return abs(b * a / 100 - v) <= TOLERANCIA


def validar_item(item, crt):
    """Devolve a lista de problemas do item. `crt` é o regime tributário do emitente."""
    msgs = []

    ncm = item["ncm"]
    if not (len(ncm) == 8 and ncm.isdigit()):
        msgs.append(f"NCM ausente ou inválido ({ncm or 'vazio'})")

    qtd, unit, total = para_decimal(item["qtd"]), para_decimal(item["vun"]), para_decimal(item["vtot"])
    if None not in (qtd, unit, total) and abs(qtd * unit - total) > TOLERANCIA:
        msgs.append("Valor total diferente de quantidade × valor unitário")

    grupo = item["icms_grupo"]
    if not grupo:
        msgs.append("Item sem grupo de ICMS")
    else:
        usa_csosn = grupo.startswith("ICMSSN")  # CSOSN = códigos do Simples Nacional
        if crt in ("1", "4") and not usa_csosn:
            msgs.append("Emitente do Simples Nacional, mas o ICMS veio com CST (esperado CSOSN)")
        if crt in ("2", "3") and usa_csosn:
            msgs.append("Emitente do regime normal, mas o ICMS veio com CSOSN (esperado CST)")

    # IBS/CBS ficam de fora: com redução ou diferimento o valor não é base × alíquota nominal
    for imp in item["impostos"]:
        if imp["sigla"] in ("ICMS", "IPI", "PIS", "COFINS") and not _bate(imp["base"], imp["aliq"], imp["valor"]):
            msgs.append(f"{imp['sigla']}: base × alíquota não bate com o valor informado")
    return msgs


# =============================================================================
# 4. IMPORTAÇÃO PARA O BANCO
# =============================================================================

def importar_arquivo(conn, caminho):
    """Importa um XML. Devolve (resultado, mensagem), com resultado 'ok', 'duplicada' ou 'erro'.
    Em uma única transação grava fornecedor, nota, produtos, itens, impostos e alertas."""
    nome = Path(caminho).name
    try:
        cabecalho, itens = ler_nfe(caminho)
    except (OSError, ValueError) as erro:
        return _registrar(conn, nome, "erro", str(erro))

    existente = conn.execute("SELECT id FROM notas WHERE chave = ?", (cabecalho["chave"],)).fetchone()
    if existente:
        return _registrar(conn, nome, "duplicada", f"NF {cabecalho['numero']} já havia sido importada",
                          existente["id"])
    try:
        with conn:  # transação: ou grava tudo ou nada
            nota_id = _gravar(conn, cabecalho, itens, nome)
    except sqlite3.Error as erro:
        return _registrar(conn, nome, "erro", f"erro ao gravar no banco: {erro}")
    return _registrar(conn, nome, "ok", f"NF {cabecalho['numero']} importada com {len(itens)} item(ns)", nota_id)


def _gravar(conn, cab, itens, arquivo):
    fornecedor_id = _fornecedor(conn, cab)
    nota_id = conn.execute(
        """INSERT INTO notas (fornecedor_id, chave, numero, serie, data_emissao, natureza_op, total_produtos, arquivo)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (fornecedor_id, cab["chave"], cab["numero"], cab["serie"], cab["data_emissao"], cab["natureza_op"],
         como_float(cab["total_produtos"]), arquivo)).lastrowid

    tributos = {linha["sigla"]: linha["id"] for linha in conn.execute("SELECT id, sigla FROM tributos")}
    for item in itens:
        mensagens = validar_item(item, cab["crt"])
        produto_id, ncm_anterior = _produto(conn, fornecedor_id, item)
        if ncm_anterior and ncm_anterior != item["ncm"]:
            mensagens.append(f"NCM diferente do cadastro anterior do produto ({ncm_anterior})")

        item_id = conn.execute(
            """INSERT INTO itens_nota (nota_id, produto_id, numero_item, cfop, quantidade,
                                       valor_unitario, valor_total, grupo_icms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (nota_id, produto_id, item["n"], item["cfop"], como_float(item["qtd"]), como_float(item["vun"]),
             como_float(item["vtot"]), item["icms_grupo"])).lastrowid
        for imp in item["impostos"]:
            conn.execute(
                """INSERT INTO impostos_item (item_id, tributo_id, cst, base, aliquota, valor, detalhe)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (item_id, tributos[imp["sigla"]], imp["cst"], como_float(imp["base"]),
                 como_float(imp["aliq"]), como_float(imp["valor"]), imp["detalhe"]))
        for mensagem in mensagens:
            conn.execute("INSERT INTO alertas (item_id, mensagem) VALUES (?, ?)", (item_id, mensagem))
    return nota_id


def _fornecedor(conn, cab):
    """Acha o fornecedor pelo CNPJ ou cria um novo. O nome só é gravado na criação (o usuário pode editá-lo)."""
    linha = conn.execute("SELECT id FROM fornecedores WHERE cnpj = ?", (cab["cnpj"],)).fetchone()
    if linha:
        conn.execute("UPDATE fornecedores SET regime = ? WHERE id = ?", (cab["crt"], linha["id"]))
        return linha["id"]
    return conn.execute("INSERT INTO fornecedores (cnpj, nome, regime) VALUES (?, ?, ?)",
                        (cab["cnpj"], cab["emitente"] or "(sem nome)", cab["crt"])).lastrowid


def _produto(conn, fornecedor_id, item):
    """Acha o produto (fornecedor + código) ou cria. Devolve (id, ncm que já estava cadastrado)."""
    linha = conn.execute("SELECT id, ncm FROM produtos WHERE fornecedor_id = ? AND codigo = ?",
                         (fornecedor_id, item["cod"])).fetchone()
    if linha:
        return linha["id"], linha["ncm"]
    novo = conn.execute(
        """INSERT INTO produtos (fornecedor_id, codigo, ean, descricao, ncm, cest, unidade)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (fornecedor_id, item["cod"], item["ean"], item["desc"] or "(sem descrição)", item["ncm"],
         item["cest"], item["un"])).lastrowid
    return novo, ""


def _registrar(conn, arquivo, resultado, mensagem, nota_id=None):
    with conn:
        conn.execute("INSERT INTO importacoes (arquivo, resultado, mensagem, nota_id) VALUES (?, ?, ?, ?)",
                     (arquivo, resultado, mensagem, nota_id))
    return resultado, mensagem


# =============================================================================
# 5. TELA
# =============================================================================

def historico_importacoes(app, limite=30):
    """Últimas tentativas de importação (JOIN com notas para mostrar o número da NF)."""
    return app.consultar("""
        SELECT im.data_hora, im.arquivo, im.resultado, im.mensagem, n.numero AS nf
        FROM importacoes im LEFT JOIN notas n ON n.id = im.nota_id
        ORDER BY im.id DESC
        LIMIT ?""", (limite,))


def construir(app):
    cores = {"ok": app.cor.VERDE, "duplicada": app.cor.AMBAR, "erro": app.cor.VERMELHO}
    rotulos = {"ok": "Importada", "duplicada": "Já importada", "erro": "Erro"}
    status = ft.Text("Selecione um ou mais arquivos XML de NF-e.", color=app.cor.MUTED)
    resultados = ft.Column(spacing=4)
    historico = ft.Container()

    def montar_historico():
        linhas = [[h["data_hora"], h["arquivo"], ft.Text(rotulos[h["resultado"]], size=13, color=cores[h["resultado"]]),
                   h["mensagem"]] for h in historico_importacoes(app)]
        historico.content = app.tabela(["Data/hora", "Arquivo", "Resultado", "Detalhe"], linhas,
                                       texto_vazio="Nenhuma importação realizada ainda.")

    def processar(caminhos):
        if not caminhos:  # janela fechada sem escolher
            return
        resultados.controls = []
        for caminho in caminhos:
            resultado, mensagem = importar_arquivo(app.conn, caminho)
            resultados.controls.append(ft.Text(f"{Path(caminho).name}: {mensagem}", size=13, color=cores[resultado]))
        status.value = f"{len(caminhos)} arquivo(s) processado(s)."
        montar_historico()
        app.page.update()

    montar_historico()
    return ft.Column([
        app.titulo("Importar XML", "Leia as notas fiscais e cadastre produtos e impostos no banco",
                   app.botao("Selecionar XML(s)", lambda e: app.escolher_arquivos(processar))),
        status,
        resultados,
        app.subtitulo("Histórico de importações"),
        historico,
    ], spacing=16)
