"""Tela 2 — Importar XML. Também concentra o banco de dados e a leitura da NF-e.

Escopo deste arquivo:
  1. BANCO: esquema SQLite (9 tabelas: 8 ligadas por PKs e FKs 1:N + configuracoes) e conexão.
  2. XML: lê a NF-e e extrai produto + impostos de cada item (ICMS, FCP, ICMS-ST, FCP-ST, DIFAL,
     ICMS desonerado, IPI, II, PIS, COFINS, IS, IBS e CBS), com MVA, redução de base e modalidade.
  3. IMPORTAÇÃO: grava tudo em uma transação e registra o histórico. As regras que geram os alertas
     ficam em conferencia.py (gerais) e reforma.py (IBS/CBS).
  4. TELA: escolher os XMLs e mostrar o resultado e o histórico.

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

from nfe_projeto import conferencia, reforma

# Arquivo do banco SQLite: pasta banco/ na raiz do projeto
BANCO = Path(__file__).resolve().parent.parent / "banco" / "nfe_importador.db"

# Catálogo de tributos (vira a tabela `tributos`). A ordem aqui é a ordem de exibição nas telas.
TRIBUTOS = [
    ("ICMS", "Imposto sobre Circulação de Mercadorias e Serviços"),
    ("FCP", "Fundo de Combate à Pobreza sobre o ICMS próprio"),
    ("ICMS-ST", "ICMS por Substituição Tributária"),
    ("FCP-ST", "Fundo de Combate à Pobreza retido por Substituição Tributária"),
    ("DIFAL", "ICMS diferencial de alíquota devido à UF de destino"),
    ("FCP-DIFAL", "Fundo de Combate à Pobreza devido à UF de destino"),
    ("ICMS-Deson", "ICMS desonerado"),
    ("IPI", "Imposto sobre Produtos Industrializados"),
    ("II", "Imposto de Importação"),
    ("PIS", "Programa de Integração Social"),
    ("COFINS", "Contribuição para o Financiamento da Seguridade Social"),
    ("IS", "Imposto Seletivo (reforma tributária)"),
    ("IBS", "Imposto sobre Bens e Serviços (reforma tributária)"),
    ("CBS", "Contribuição sobre Bens e Serviços (reforma tributária)"),
]

# Origem da mercadoria (tag orig, 1º dígito do CST do ICMS)
ORIGENS = {
    "0": "Nacional",
    "1": "Estrangeira, importação direta",
    "2": "Estrangeira, adquirida no mercado interno",
    "3": "Nacional, conteúdo de importação acima de 40% e até 70%",
    "4": "Nacional, produzida conforme processo produtivo básico",
    "5": "Nacional, conteúdo de importação até 40%",
    "6": "Estrangeira, importação direta sem similar nacional (lista CAMEX)",
    "7": "Estrangeira, mercado interno, sem similar nacional (lista CAMEX)",
    "8": "Nacional, conteúdo de importação acima de 70%",
}

# Modalidade de determinação da base do ICMS (modBC) e do ICMS-ST (modBCST)
MODALIDADES_BC = {"0": "Margem de valor agregado", "1": "Pauta (valor)", "2": "Preço tabelado máximo",
                  "3": "Valor da operação"}
MODALIDADES_BCST = {"0": "Preço tabelado ou máximo sugerido", "1": "Lista negativa", "2": "Lista positiva",
                    "3": "Lista neutra", "4": "Margem de valor agregado (MVA)", "5": "Pauta (valor)",
                    "6": "Valor da operação"}


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
    cclasstrib     TEXT NOT NULL DEFAULT '',    -- classificação tributária do IBS/CBS (reforma)
    origem         TEXT NOT NULL DEFAULT '',    -- origem da mercadoria (0 a 8)
    margem         REAL,                        -- lucro desejado (% do preço); vazio = padrão da empresa
    icms_venda     REAL,                        -- ICMS (+FCP) na venda (%); vazio = padrão da empresa
    preco_venda    REAL,                        -- preço de venda calculado e salvo pelo usuário
    status      TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente', 'cadastrado')),
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
    grupo_icms      TEXT NOT NULL DEFAULT '',   -- ex.: ICMS00, ICMSSN102
    cclasstrib      TEXT NOT NULL DEFAULT '',   -- cClassTrib do IBS/CBS informado neste item
    origem          TEXT NOT NULL DEFAULT '',   -- origem da mercadoria (0 a 8)
    cbenef          TEXT NOT NULL DEFAULT '',   -- código de benefício fiscal da UF
    frete           REAL,
    seguro          REAL,
    desconto        REAL,
    outras          REAL                        -- outras despesas acessórias
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
    cst           TEXT NOT NULL DEFAULT '',     -- CST ou CSOSN
    modalidade    TEXT NOT NULL DEFAULT '',     -- como a base foi determinada (valor da operação, MVA...)
    base          REAL,
    reducao_base  REAL,                         -- % de redução da base de cálculo
    mva           REAL,                         -- margem de valor agregado (ICMS-ST)
    aliquota      REAL,
    valor         REAL,
    detalhe       TEXT NOT NULL DEFAULT ''
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

-- Parâmetros da empresa usuária para a formação do preço de venda (sempre uma única linha, id = 1)
CREATE TABLE IF NOT EXISTS configuracoes (
    id                INTEGER PRIMARY KEY CHECK (id = 1),
    regime            TEXT NOT NULL DEFAULT 'simples' CHECK (regime IN ('simples', 'presumido', 'real')),
    aliquota_simples  REAL NOT NULL DEFAULT 8.0,
    icms_venda        REAL NOT NULL DEFAULT 18.0,
    irpj_csll         REAL NOT NULL DEFAULT 2.28,
    despesas          REAL NOT NULL DEFAULT 15.0,
    margem            REAL NOT NULL DEFAULT 10.0,
    aliquota_reforma  REAL NOT NULL DEFAULT 26.5
);

CREATE INDEX IF NOT EXISTS idx_notas_fornecedor ON notas(fornecedor_id);
CREATE INDEX IF NOT EXISTS idx_itens_nota ON itens_nota(nota_id);
CREATE INDEX IF NOT EXISTS idx_itens_produto ON itens_nota(produto_id);
CREATE INDEX IF NOT EXISTS idx_impostos_item ON impostos_item(item_id);
CREATE INDEX IF NOT EXISTS idx_alertas_item ON alertas(item_id);
"""


TEXTO = "TEXT NOT NULL DEFAULT ''"
COLUNAS_NOVAS = {
    "produtos": [("cclasstrib", TEXTO), ("origem", TEXTO), ("margem", "REAL"), ("icms_venda", "REAL"),
                 ("preco_venda", "REAL")],
    "itens_nota": [("cclasstrib", TEXTO), ("origem", TEXTO), ("cbenef", TEXTO), ("frete", "REAL"),
                   ("seguro", "REAL"), ("desconto", "REAL"), ("outras", "REAL")],
    "impostos_item": [("modalidade", TEXTO), ("reducao_base", "REAL"), ("mva", "REAL")],
}


def conectar(caminho=BANCO):
    """Abre o banco (criando a pasta, as tabelas e o catálogo de tributos na primeira vez)."""
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(caminho), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # SQLite só respeita FKs se isto estiver ligado
    conn.executescript(ESQUEMA)
    # Bancos criados por versões anteriores recebem aqui as colunas que faltam
    for tabela, colunas in COLUNAS_NOVAS.items():
        existentes = {linha["name"] for linha in conn.execute(f"PRAGMA table_info({tabela})")}
        for nome, tipo in colunas:
            if nome not in existentes:
                conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}")
    conn.executemany("INSERT OR IGNORE INTO tributos (sigla, nome) VALUES (?, ?)", TRIBUTOS)
    conn.execute("INSERT OR IGNORE INTO configuracoes (id) VALUES (1)")
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
        "totais_ibscbs": _totais_ibscbs(inf.find(".//IBSCBSTot")),
    }
    return cabecalho, [_ler_item(det) for det in inf.findall("det")]


def _totais_ibscbs(tot):
    """Totais do IBS/CBS da nota (grupo total/IBSCBSTot), ou None se a nota não tiver o grupo."""
    if tot is None:
        return None
    return {"vbc": t(tot, "vBCIBSCBS"), "vibs": t(tot.find("gIBS"), "vIBS"), "vcbs": t(tot.find("gCBS"), "vCBS")}


def _ler_ibscbs(grupo):
    """Lê o grupo IBSCBS de um item. Cada parte (IBS estadual, municipal e CBS) tem alíquota, valor e,
    se houver redução (gRed), o percentual de redução e a alíquota efetiva."""
    if grupo is None:
        return None
    calc = grupo.find(".//gIBSCBS")

    def parte(nome_grupo, tag_aliq, tag_valor):
        g = calc.find(nome_grupo) if calc is not None else None
        red = g.find("gRed") if g is not None else None
        return {"aliq": t(g, tag_aliq), "valor": t(g, tag_valor),
                "reducao": t(red, "pRedAliq"), "efetiva": t(red, "pAliqEfet")}

    return {
        "cst": t(grupo, "CST"),
        "cclasstrib": t(grupo, "cClassTrib"),
        "vbc": t(calc, "vBC"),
        "vibs": (calc.findtext("vIBS") or "").strip() if calc is not None else "",
        "uf": parte("gIBSUF", "pIBSUF", "vIBSUF"),
        "mun": parte("gIBSMun", "pIBSMun", "vIBSMun"),
        "cbs": parte("gCBS", "pCBS", "vCBS"),
        "diferimento": grupo.find(".//gDif") is not None,
        "compra_gov": grupo.find(".//gCompraGov") is not None,
    }


def _ler_item(det):
    prod, imp = det.find("prod"), det.find("imposto")
    ean = t(prod, "cEAN")
    icms = imp.find("ICMS") if imp is not None else None
    try:
        numero = int(det.get("nItem", "0"))
    except ValueError:
        raise ValueError("número de item inválido no XML")
    ibscbs = _ler_ibscbs(imp.find("IBSCBS") if imp is not None else None)
    grupo_icms = icms[0] if icms is not None and len(icms) else None
    difal = imp.find("ICMSUFDest") if imp is not None else None
    return {
        "n": numero,
        "cod": t(prod, "cProd"),
        "ean": "" if ean.upper() == "SEM GTIN" else ean,
        "desc": t(prod, "xProd"),
        "ncm": t(prod, "NCM"),
        "cest": t(prod, "CEST"),
        "cbenef": t(prod, "cBenef"),
        "cfop": t(prod, "CFOP"),
        "un": t(prod, "uCom"),
        "qtd": t(prod, "qCom"),
        "vun": t(prod, "vUnCom"),
        "vtot": t(prod, "vProd"),
        "frete": t(prod, "vFrete"),
        "seguro": t(prod, "vSeg"),
        "desconto": t(prod, "vDesc"),
        "outras": t(prod, "vOutro"),
        "icms_grupo": grupo_icms.tag if grupo_icms is not None else "",
        "icms": _tags(grupo_icms),   # todas as tags do grupo ICMSxx (usadas na conferência)
        "difal": _tags(difal),
        "ibscbs": ibscbs,
        "impostos": _impostos(imp, ibscbs),
    }


def _tags(grupo):
    """{tag: texto} dos filhos diretos de um grupo do XML ({} se o grupo não existe)."""
    if grupo is None:
        return {}
    return {filho.tag: (filho.text or "").strip() for filho in grupo}


def _imposto(sigla, cst="", base="", aliq="", valor="", detalhe="", modalidade="", reducao="", mva="",
             retido=False):
    return {"sigla": sigla, "cst": cst, "base": base, "aliq": aliq, "valor": valor, "detalhe": detalhe,
            "modalidade": modalidade, "reducao": reducao, "mva": mva, "retido": retido}


def _impostos(imp, ibs):
    """Lista de impostos do item, um dicionário por tributo presente no XML."""
    lista = []
    if imp is not None:
        lista += _icms(imp.find("ICMS"))
        lista += _difal(imp.find("ICMSUFDest"))
        ipi = imp.find("IPI")
        if t(ipi, "CST"):
            partes = [f"enquadramento {t(ipi, 'cEnq')}"] if t(ipi, "cEnq") else []
            if t(ipi, "qUnid"):  # IPI por unidade (ex.: bebidas, cigarros)
                partes.append(f"{br(t(ipi, 'qUnid'), 4)} un. × R$ {br(t(ipi, 'vUnid'), 4)}")
            lista.append(_imposto("IPI", t(ipi, "CST"), t(ipi, "vBC"), t(ipi, "pIPI"), t(ipi, "vIPI"),
                                  " · ".join(partes)))
        ii = imp.find("II")
        if ii is not None:
            partes = [f"despesas aduaneiras R$ {br(t(ii, 'vDespAdu'))}"] if t(ii, "vDespAdu") else []
            if t(ii, "vIOF"):
                partes.append(f"IOF R$ {br(t(ii, 'vIOF'))}")
            lista.append(_imposto("II", "", t(ii, "vBC"), "", t(ii, "vII"), " · ".join(partes)))
        for sigla in ("PIS", "COFINS"):
            grupo = imp.find(sigla)
            if t(grupo, "CST"):
                detalhe = ""
                if t(grupo, "qBCProd"):  # PIS/COFINS por quantidade (ex.: combustíveis, bebidas)
                    detalhe = f"{br(t(grupo, 'qBCProd'), 4)} un. × R$ {br(t(grupo, 'vAliqProd'), 4)}"
                lista.append(_imposto(sigla, t(grupo, "CST"), t(grupo, "vBC"), t(grupo, f"p{sigla}"),
                                      t(grupo, f"v{sigla}"), detalhe))
        lista += _imposto_seletivo(imp.find("IS"))
    lista += _ibs_cbs(ibs)
    return lista


def _icms(icms):
    """ICMS próprio, FCP, ICMS-ST, FCP-ST e ICMS desonerado do grupo ICMSxx."""
    if icms is None or not len(icms):
        return []
    g = icms[0]
    cst = t(g, "CST", "CSOSN")  # CST (regime normal) ou CSOSN (Simples)
    orig = t(g, "orig")
    partes = [g.tag]
    if orig:
        partes.append(f"origem {orig} ({ORIGENS.get(orig, '?')})")
    if t(g, "vCredICMSSN"):
        partes.append(f"crédito Simples {br(t(g, 'pCredSN'))}% = R$ {br(t(g, 'vCredICMSSN'))}")
    if t(g, "pDif"):
        partes.append(f"diferimento {br(t(g, 'pDif'))}% (R$ {br(t(g, 'vICMSDif'))} diferido, "
                      f"ICMS da operação R$ {br(t(g, 'vICMSOp'))})")
    lista = [_imposto("ICMS", cst, t(g, "vBC"), t(g, "pICMS"), t(g, "vICMS"), " · ".join(partes),
                      MODALIDADES_BC.get(t(g, "modBC"), ""), t(g, "pRedBC"))]

    if t(g, "vBCFCP") or t(g, "pFCP") or t(g, "vFCP"):
        lista.append(_imposto("FCP", cst, t(g, "vBCFCP") or t(g, "vBC"), t(g, "pFCP"), t(g, "vFCP")))

    if t(g, "vBCST") or t(g, "pICMSST") or t(g, "vICMSST"):
        lista.append(_imposto("ICMS-ST", cst, t(g, "vBCST"), t(g, "pICMSST"), t(g, "vICMSST"),
                              modalidade=MODALIDADES_BCST.get(t(g, "modBCST"), ""), reducao=t(g, "pRedBCST"),
                              mva=t(g, "pMVAST")))
    elif t(g, "vBCSTRet") or t(g, "vICMSSTRet"):  # ST cobrada anteriormente (ICMS60, CSOSN 500)
        detalhe = "retido anteriormente"
        if t(g, "vICMSSubstituto"):
            detalhe += f" · ICMS do substituto R$ {br(t(g, 'vICMSSubstituto'))}"
        lista.append(_imposto("ICMS-ST", cst, t(g, "vBCSTRet"), t(g, "pST"), t(g, "vICMSSTRet"), detalhe,
                              retido=True))

    if t(g, "vBCFCPST") or t(g, "pFCPST") or t(g, "vFCPST"):
        lista.append(_imposto("FCP-ST", cst, t(g, "vBCFCPST"), t(g, "pFCPST"), t(g, "vFCPST")))
    elif t(g, "vFCPSTRet"):
        lista.append(_imposto("FCP-ST", cst, t(g, "vBCFCPSTRet"), t(g, "pFCPSTRet"), t(g, "vFCPSTRet"),
                              "retido anteriormente", retido=True))

    if t(g, "vICMSDeson"):
        lista.append(_imposto("ICMS-Deson", cst, valor=t(g, "vICMSDeson"),
                              detalhe=f"motivo {t(g, 'motDesICMS') or '—'}"))
    return lista


def _difal(d):
    """DIFAL: venda interestadual a consumidor final não contribuinte (grupo ICMSUFDest)."""
    if d is None:
        return []
    detalhe = (f"interestadual {br(t(d, 'pICMSInter'))}% · interna destino {br(t(d, 'pICMSUFDest'))}% · "
               f"partilha destino {br(t(d, 'pICMSInterPart'))}%")
    if t(d, "vICMSUFRemet") and para_decimal(t(d, "vICMSUFRemet")):
        detalhe += f" · UF de origem R$ {br(t(d, 'vICMSUFRemet'))}"
    lista = [_imposto("DIFAL", "", t(d, "vBCUFDest"), t(d, "pICMSUFDest"), t(d, "vICMSUFDest"), detalhe)]
    if t(d, "pFCPUFDest") or t(d, "vFCPUFDest"):
        lista.append(_imposto("FCP-DIFAL", "", t(d, "vBCFCPUFDest") or t(d, "vBCUFDest"), t(d, "pFCPUFDest"),
                              t(d, "vFCPUFDest")))
    return lista


def _imposto_seletivo(grupo):
    """Imposto Seletivo (reforma tributária): bebidas, fumo, veículos etc."""
    if grupo is None:
        return []
    partes = [f"cClassTrib {t(grupo, 'cClassTribIS')}"] if t(grupo, "cClassTribIS") else []
    if t(grupo, "pISEspec"):
        partes.append(f"alíquota específica R$ {br(t(grupo, 'pISEspec'), 4)}")
    return [_imposto("IS", t(grupo, "CSTIS"), t(grupo, "vBCIS"), t(grupo, "pIS"), t(grupo, "vIS"),
                     " · ".join(partes))]


def _ibs_cbs(g):
    """IBS e CBS (reforma tributária) a partir do grupo já lido por _ler_ibscbs.
    A alíquota gravada do IBS é a soma estadual + municipal; a redução aparece nos detalhes."""
    if g is None:
        return []
    uf, mun, cbs = g["uf"], g["mun"], g["cbs"]
    aliq_ibs = ""
    if uf["aliq"] or mun["aliq"]:
        aliq_ibs = str(sum((para_decimal(x) or Decimal(0) for x in (uf["aliq"], mun["aliq"])), Decimal(0)))

    def reducao(parte):
        if not parte["reducao"]:
            return []
        return [f"redução {br(parte['reducao'])}% → efetiva {br(parte['efetiva'] or '0', 4)}%"]

    partes_ibs = [f"cClassTrib {g['cclasstrib']}"] if g["cclasstrib"] else []
    if uf["aliq"]:
        partes_ibs.append(f"UF {br(uf['aliq'])}%")
    if mun["aliq"]:
        partes_ibs.append(f"Mun. {br(mun['aliq'])}%")
    partes_ibs += reducao(uf)
    partes_cbs = ([f"cClassTrib {g['cclasstrib']}"] if g["cclasstrib"] else []) + reducao(cbs)
    return [
        _imposto("IBS", g["cst"], g["vbc"], aliq_ibs, g["vibs"], " · ".join(partes_ibs)),
        _imposto("CBS", g["cst"], g["vbc"], cbs["aliq"], cbs["valor"], " · ".join(partes_cbs)),
    ]


# =============================================================================
# 3. IMPORTAÇÃO PARA O BANCO
# =============================================================================

def validar_item(item, crt, ano=0):
    """Todos os alertas do item: regras gerais (conferencia.py) + reforma tributária (reforma.py)."""
    return conferencia.validar_item(item, crt) + reforma.validar_item(item, crt, ano)



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
    ano = int(cab["data_emissao"][:4]) if cab["data_emissao"][:4].isdigit() else 0
    # Alertas dos totais da nota ficam no primeiro item (a tabela alertas é ligada a itens)
    alertas_nota = reforma.validar_totais(cab["totais_ibscbs"], itens)
    for posicao, item in enumerate(itens):
        mensagens = validar_item(item, cab["crt"], ano) + (alertas_nota if posicao == 0 else [])
        produto_id, anterior = _produto(conn, fornecedor_id, item)
        if anterior and anterior["ncm"] and anterior["ncm"] != item["ncm"]:
            mensagens.append(f"NCM diferente do cadastro anterior do produto ({anterior['ncm']})")
        cclass = item["ibscbs"]["cclasstrib"] if item["ibscbs"] else ""
        if anterior and cclass and anterior["cclasstrib"] and anterior["cclasstrib"] != cclass:
            mensagens.append(f"Reforma: cClassTrib {cclass} diferente do cadastro anterior do produto "
                             f"({anterior['cclasstrib']})")
        elif anterior and cclass and not anterior["cclasstrib"]:
            conn.execute("UPDATE produtos SET cclasstrib = ? WHERE id = ?", (cclass, produto_id))
        origem = item["icms"].get("orig", "")
        if anterior and origem and anterior["origem"] and anterior["origem"] != origem:
            mensagens.append(f"Origem da mercadoria {origem} diferente do cadastro anterior do produto "
                             f"({anterior['origem']})")
        elif anterior and origem and not anterior["origem"]:
            conn.execute("UPDATE produtos SET origem = ? WHERE id = ?", (origem, produto_id))

        item_id = conn.execute(
            """INSERT INTO itens_nota (nota_id, produto_id, numero_item, cfop, quantidade, valor_unitario,
                                       valor_total, grupo_icms, cclasstrib, origem, cbenef,
                                       frete, seguro, desconto, outras)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (nota_id, produto_id, item["n"], item["cfop"], como_float(item["qtd"]), como_float(item["vun"]),
             como_float(item["vtot"]), item["icms_grupo"], cclass, origem, item["cbenef"],
             como_float(item["frete"]), como_float(item["seguro"]), como_float(item["desconto"]),
             como_float(item["outras"]))).lastrowid
        for imp in item["impostos"]:
            conn.execute(
                """INSERT INTO impostos_item (item_id, tributo_id, cst, modalidade, base, reducao_base, mva,
                                              aliquota, valor, detalhe)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (item_id, tributos[imp["sigla"]], imp["cst"], imp["modalidade"], como_float(imp["base"]),
                 como_float(imp["reducao"]), como_float(imp["mva"]), como_float(imp["aliq"]),
                 como_float(imp["valor"]), imp["detalhe"]))
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
    """Acha o produto (fornecedor + código) ou cria. Devolve (id, cadastro anterior com ncm, cclasstrib e
    origem) — o cadastro anterior é None quando o produto acabou de ser criado."""
    linha = conn.execute("""SELECT id, ncm, cclasstrib, origem FROM produtos
                            WHERE fornecedor_id = ? AND codigo = ?""", (fornecedor_id, item["cod"])).fetchone()
    if linha:
        return linha["id"], linha
    novo = conn.execute(
        """INSERT INTO produtos (fornecedor_id, codigo, ean, descricao, ncm, cest, unidade, cclasstrib, origem)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (fornecedor_id, item["cod"], item["ean"], item["desc"] or "(sem descrição)", item["ncm"],
         item["cest"], item["un"], item["ibscbs"]["cclasstrib"] if item["ibscbs"] else "",
         item["icms"].get("orig", ""))).lastrowid
    return novo, None


def _registrar(conn, arquivo, resultado, mensagem, nota_id=None):
    with conn:
        conn.execute("INSERT INTO importacoes (arquivo, resultado, mensagem, nota_id) VALUES (?, ?, ?, ?)",
                     (arquivo, resultado, mensagem, nota_id))
    return resultado, mensagem


# =============================================================================
# 4. TELA
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
