# Importador de NF-e

Sistema desktop em Python ([Flet](https://flet.dev)) com banco de dados **SQLite** que lê os arquivos XML de
Nota Fiscal Eletrônica e separa **todos os impostos de cada item** (ICMS, ICMS-ST, IPI, PIS, COFINS e os
novos IBS/CBS da reforma tributária). Assim o usuário consegue cadastrar os produtos no sistema dele com a
tributação certa. Na importação, o sistema também confere as notas e **aponta o que está errado**, tanto
nas regras atuais quanto nas regras da **reforma tributária** (IBS/CBS).

## Pastas do sistema

```
nfe_projeto/
├── banco/
│   └── nfe_importador.db      ← banco de dados SQLite (já com dados de demonstração)
├── nfe_projeto/               ← código-fonte (uma tela por arquivo)
│   ├── main.py                  Tela 1 – Painel + janela, menu e navegação
│   ├── importar.py              Tela 2 – Importar XML + esquema do banco + leitura do XML
│   ├── notas.py                 Tela 3 – Notas fiscais (lista e detalhe com impostos)
│   ├── produtos.py              Tela 4 – Produtos (lista e ficha editável)
│   ├── fornecedores.py          Tela 5 – Fornecedores (editar / excluir)
│   ├── alertas.py               Tela 6 – Conferência (inconsistências)
│   ├── relatorios.py            Tela 7 – Relatórios (totais por tributo e fornecedor)
│   └── reforma.py               Regras de conferência da reforma tributária (IBS/CBS)
├── xmls_exemplo/              ← XMLs de NF-e fictícios para testar a importação
├── requirements.txt
└── README.md
```

## Como executar

```bash
pip install -r requirements.txt
python nfe_projeto/main.py
```

(ou, dentro da pasta `nfe_projeto/`, `python main.py`)

O sistema abre usando o banco `banco/nfe_importador.db`. Se o arquivo for apagado, ele é recriado vazio
automaticamente na próxima execução.

## Banco de dados (SQLite)

Arquivo: `banco/nfe_importador.db`. São 8 tabelas com chaves primárias, chaves estrangeiras
(`PRAGMA foreign_keys = ON`) e relacionamentos 1:N:

| Tabela | O que guarda | Relaciona com |
|---|---|---|
| `fornecedores` | Emitentes das notas (CNPJ, nome, regime tributário) | pai de `notas` e `produtos` |
| `notas` | Cabeçalho da NF-e (chave de acesso, número, série, data, total) | filha de `fornecedores` |
| `produtos` | Catálogo de produtos por fornecedor (código, EAN, NCM, CEST, cClassTrib, status) | filha de `fornecedores` |
| `itens_nota` | Cada item de cada nota (CFOP, cClassTrib, quantidade, valores) | filha de `notas` e `produtos` |
| `tributos` | Catálogo fixo: ICMS, ICMS-ST, IPI, PIS, COFINS, IBS, CBS | pai de `impostos_item` |
| `impostos_item` | Imposto de cada item (CST/CSOSN, base, alíquota, valor) | filha de `itens_nota` e `tributos` |
| `alertas` | Inconsistências encontradas em cada item | filha de `itens_nota` |
| `importacoes` | Histórico de cada tentativa de importação (ok, duplicada, erro) | referencia `notas` |

Regras de integridade que aparecem no uso:
- Excluir uma nota apaga em cascata os itens, impostos e alertas dela (`ON DELETE CASCADE`).
- Não é possível excluir um fornecedor que tem notas ou produtos (a chave estrangeira impede).
- A chave de acesso da nota é `UNIQUE`, então a mesma nota não é importada duas vezes.

## As 7 telas

1. **Painel**: indicadores (notas importadas, produtos, pendentes de cadastro, alertas em aberto,
   alertas da reforma) e as últimas notas, com atalho para abrir cada uma.
2. **Importar XML**: seleciona um ou vários XMLs, importa tudo numa transação e mostra o resultado
   de cada arquivo (importada, já importada ou erro) e o histórico de importações.
3. **Notas fiscais**: lista das notas com situação (OK ou "p/ revisar"). Ao abrir uma nota, aparecem
   os dados do emitente e uma tabela com o cClassTrib e os impostos de cada item. O botão "Excluir
   nota" pede confirmação.
4. **Produtos**: busca por descrição, código, NCM, EAN ou cClassTrib e filtro Pendentes/Cadastrados.
   A **ficha do produto** permite editar os dados (incluindo o cClassTrib) e marcar como cadastrado, e
   mostra a tributação atual e o histórico de compras.
5. **Fornecedores**: lista com CNPJ, regime tributário, quantidade de notas e de produtos. Permite
   editar o nome e excluir (só os fornecedores sem vínculos).
6. **Conferência**: alertas gerados automaticamente na importação, separados em **REFORMA** e
   **GERAL**, com filtro por tipo. Cada alerta pode ser resolvido ou reaberto.
7. **Relatórios**: total de base de cálculo e de imposto por tributo, e total de mercadorias e de
   impostos por fornecedor.

## O que o sistema confere

**Regras gerais** (em `importar.py`)
- NCM ausente ou sem 8 dígitos
- Valor total do item diferente de quantidade × valor unitário
- CST × CSOSN errado para o regime do emitente (Simples Nacional usa CSOSN)
- ICMS, IPI, PIS ou COFINS com base × alíquota diferente do valor informado
- NCM diferente do que já estava cadastrado para o produto

**Reforma tributária: IBS e CBS** (em `reforma.py`, conforme o leiaute da NT 2025.002-RTC e a LC 214/2025)
- Emitente do **regime normal** sem o grupo IBS/CBS em nota de 2026 em diante. Simples Nacional e MEI
  só passam a ser obrigados em 2027, por isso não geram alerta.
- **cClassTrib** sem 6 dígitos ou que não pertence ao CST (os 3 primeiros dígitos devem ser o CST)
- Alíquotas diferentes das **alíquotas de teste de 2026**: CBS 0,9%, IBS estadual 0,1%, IBS municipal 0%
- **Redução de alíquota**: alíquota efetiva diferente de alíquota × (1 − redução)
- Valor do IBS estadual, do IBS municipal ou da CBS diferente de base × alíquota efetiva
- Valor do IBS diferente da soma estadual + municipal
- Produto da **Cesta Básica Nacional** (Anexo I da LC 214, alíquota zero) sem o cClassTrib 200003
- Totais da nota (grupo `IBSCBSTot`) diferentes da soma dos itens
- cClassTrib diferente do que já estava cadastrado para o produto

As regras da reforma ainda mudam por nota técnica. Por isso os alertas **não bloqueiam** a importação:
eles servem para a conferência humana. Notas com diferimento ou compra governamental não têm os
valores conferidos, porque o cálculo nesses casos é diferente.

## Dados de demonstração

O banco já vem com as notas da pasta `xmls_exemplo/` importadas. **Todas as empresas, CNPJs e notas
são fictícios** e foram criados só para teste:

| Arquivo | Cenário |
|---|---|
| `01_aurora_nf1523.xml` | Distribuidora no regime normal: ICMS 7%, ICMS-ST com MVA, ICMS com redução de base, IBS/CBS. **Arroz (cesta básica) com cClassTrib de tributação integral** |
| `02_pontocerto_nf487.xml` | Papelaria do Simples Nacional, sem IBS/CBS (permitido em 2026): CSOSN 101 com crédito, CSOSN 102, **NCM inválido**, **CST indevido** |
| `03_valeforte_nf30871.xml` | Indústria com IPI e IBS/CBS: **ICMS com valor errado**, **total do item errado**, **cClassTrib que não pertence ao CST**, **CBS de 1,2% (teste é 0,9%)** e **total da CBS da nota errado** |
| `04_aurora_nf1588.xml` | Segunda compra da distribuidora: arroz e feijão **corretos** pela reforma (CST 200, cClassTrib 200003, redução de 100%), **NCM alterado** do refrigerante e **cClassTrib do arroz diferente do cadastro** |
| `05_arquivo_invalido.xml` | XML que não é NF-e (mostra o tratamento de erro) |
| `06_horizonte_nf9214.xml` | Distribuidora de bebidas do regime normal **sem o grupo IBS/CBS** |

Os itens em **negrito** geram alertas na tela de Conferência. O `01` foi importado duas vezes para
mostrar a detecção de nota duplicada no histórico.

## Roteiro sugerido para a apresentação

1. Mostrar as pastas do projeto e abrir o `banco/nfe_importador.db` (ex.: no DB Browser for SQLite)
   para mostrar as 8 tabelas.
2. Rodar o sistema e mostrar o **Painel** com os indicadores.
3. **Notas fiscais**: abrir a NF 30871 e mostrar os impostos por item e os itens marcados "REVISAR"
   (passar o mouse no selo mostra o motivo).
4. **Conferência**: filtrar "Reforma tributária" e explicar cada alerta do IBS/CBS (cesta básica,
   cClassTrib × CST, alíquota de teste, nota sem IBS/CBS). Resolver um e mostrar que ele vai para
   "Resolvidos".
5. **Produtos**: filtrar Pendentes e abrir a ficha do arroz (2 compras com preços diferentes). Mostrar
   o alerta de cClassTrib diferente do cadastro, corrigir o cClassTrib para 200003 na ficha e salvar.
6. **Fornecedores**: tentar excluir um fornecedor e mostrar o bloqueio pela chave estrangeira.
7. **Relatórios**: totais por tributo e por fornecedor.
8. **Importar XML**: excluir uma nota na tela de Notas e importá-la de novo pela pasta
   `xmls_exemplo/`. Importar outra vez para mostrar "Já importada" e importar o
   `05_arquivo_invalido.xml` para mostrar o erro tratado.
