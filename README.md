# Importador de NF-e

Sistema desktop em Python ([Flet](https://flet.dev)) com banco de dados **SQLite** que lê os arquivos XML de
Nota Fiscal Eletrônica e separa **todos os impostos de cada item**: ICMS, FCP, ICMS-ST (com MVA), FCP-ST,
DIFAL, ICMS desonerado, IPI, Imposto de Importação, PIS, COFINS e os novos IS, IBS e CBS da reforma
tributária. Assim o usuário consegue cadastrar os produtos no sistema dele com a tributação certa. Na
importação, o sistema também confere as notas e **aponta o que está errado**, tanto nas regras atuais
quanto nas regras da **reforma tributária** (IBS/CBS). Para cada produto, sugere o **preço de venda**
com lucro, hoje e numa estimativa depois da reforma.

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
│   ├── conferencia.py           Regras de conferência gerais (ICMS, FCP, ST, DIFAL, IPI, PIS, COFINS)
│   ├── reforma.py               Regras de conferência da reforma tributária (IBS/CBS)
│   └── precificacao.py          Cálculo do preço de venda (hoje e após a reforma)
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
automaticamente na próxima execução. Um banco criado por uma versão anterior do sistema recebe as colunas
novas automaticamente ao abrir.

## Banco de dados (SQLite)

Arquivo: `banco/nfe_importador.db`. São 9 tabelas: 8 ligadas por chaves primárias, chaves estrangeiras
(`PRAGMA foreign_keys = ON`) e relacionamentos 1:N, e mais a `configuracoes`:

| Tabela | O que guarda | Relaciona com |
|---|---|---|
| `fornecedores` | Emitentes das notas (CNPJ, nome, regime tributário) | pai de `notas` e `produtos` |
| `notas` | Cabeçalho da NF-e (chave de acesso, número, série, data, total) | filha de `fornecedores` |
| `produtos` | Catálogo de produtos por fornecedor (código, EAN, NCM, CEST, origem, cClassTrib, margem, preço de venda, status) | filha de `fornecedores` |
| `itens_nota` | Cada item de cada nota (CFOP, origem, cClassTrib, benefício fiscal, quantidade, valores, frete, seguro, desconto, outras despesas) | filha de `notas` e `produtos` |
| `tributos` | Catálogo fixo dos 14 tributos (ver tabela abaixo) | pai de `impostos_item` |
| `impostos_item` | Imposto de cada item (CST/CSOSN, modalidade da base, base, redução da base, MVA, alíquota, valor) | filha de `itens_nota` e `tributos` |
| `alertas` | Inconsistências encontradas em cada item | filha de `itens_nota` |
| `importacoes` | Histórico de cada tentativa de importação (ok, duplicada, erro) | referencia `notas` |
| `configuracoes` | Parâmetros da empresa para o preço de venda (regime, DAS, ICMS, despesas, margem, alíquota da reforma). Tem sempre uma única linha | — |

Regras de integridade que aparecem no uso:
- Excluir uma nota apaga em cascata os itens, impostos e alertas dela (`ON DELETE CASCADE`).
- Não é possível excluir um fornecedor que tem notas ou produtos (a chave estrangeira impede).
- A chave de acesso da nota é `UNIQUE`, então a mesma nota não é importada duas vezes.

## Impostos lidos do XML

| Tributo | O que é extraído |
|---|---|
| **ICMS** | Origem, CST/CSOSN, modalidade da base, base, redução da base, alíquota, valor, crédito do Simples, diferimento |
| **FCP** | Fundo de Combate à Pobreza sobre o ICMS próprio: base, alíquota e valor |
| **ICMS-ST** | Modalidade, **MVA**, redução da base ST, base, alíquota e valor. Também lê a ST retida anteriormente (CST 60 / CSOSN 500) |
| **FCP-ST** | FCP retido por substituição (ou retido anteriormente) |
| **DIFAL** | Venda interestadual a consumidor final: base, alíquota interna do destino, alíquota interestadual, partilha e valor |
| **FCP-DIFAL** | FCP devido à UF de destino |
| **ICMS desonerado** | Valor e motivo da desoneração |
| **IPI** | CST, enquadramento, base, alíquota, valor (também IPI por unidade) |
| **II** | Imposto de Importação: base, valor, despesas aduaneiras e IOF |
| **PIS / COFINS** | CST, base, alíquota, valor (também por quantidade) |
| **IS** | Imposto Seletivo da reforma: CST, cClassTrib, base, alíquota, valor |
| **IBS / CBS** | CST, cClassTrib, base, alíquotas estadual, municipal e da CBS, redução e alíquota efetiva |

No detalhe da nota aparecem só as colunas dos tributos que existem naquela nota.

## As 7 telas

1. **Painel**: indicadores (notas importadas, produtos, pendentes de cadastro, alertas em aberto,
   alertas da reforma) e as últimas notas, com atalho para abrir cada uma.
2. **Importar XML**: seleciona um ou vários XMLs, importa tudo numa transação e mostra o resultado
   de cada arquivo (importada, já importada ou erro) e o histórico de importações.
3. **Notas fiscais**: lista das notas com situação (OK ou "p/ revisar"). Ao abrir uma nota, aparecem
   os dados do emitente e uma tabela com a origem, o cClassTrib e todos os impostos de cada item
   (com MVA e redução da base). O botão "Excluir nota" pede confirmação.
4. **Produtos**: busca por descrição, código, NCM, EAN ou cClassTrib e filtro Pendentes/Cadastrados.
   A **ficha do produto** permite editar os dados de cadastro (NCM, CEST, origem, cClassTrib...) e
   marcar como cadastrado. Também mostra a tributação completa da última compra (modalidade, base,
   redução, MVA, alíquota, valor) e o histórico de compras com frete, seguro, desconto e outras despesas.
   No final, mostra o **preço de venda sugerido** (veja abaixo).
5. **Fornecedores**: lista com CNPJ, regime tributário, quantidade de notas e de produtos. Permite
   editar o nome e excluir (só os fornecedores sem vínculos).
6. **Conferência**: alertas gerados automaticamente na importação, separados em **REFORMA** e
   **GERAL**, com filtro por tipo. Cada alerta pode ser resolvido ou reaberto.
7. **Relatórios**: total de base de cálculo e de imposto por tributo, e total de mercadorias e de
   impostos por fornecedor.

## Preço de venda sugerido

No final da ficha do produto, o sistema calcula o preço por unidade a partir da última compra. O cálculo
fica em `precificacao.py` e mostra dois cenários lado a lado, cada um com a memória de cálculo:

**Hoje (2026)**: tributos "por dentro" do preço, com markup divisor.
```
custo de compra = produto + frete + seguro + outras − desconto + IPI + ICMS-ST + FCP-ST
custo líquido   = custo de compra − créditos
preço           = custo líquido ÷ (1 − (tributos sobre a venda + despesas + margem))
```
Os créditos e os tributos da venda dependem do **regime da empresa que compra**:

| Regime | Créditos na compra | Tributos sobre a venda |
|---|---|---|
| Simples Nacional | nenhum | alíquota efetiva do DAS |
| Lucro Presumido | ICMS | ICMS + PIS/COFINS 3,65% + IRPJ/CSLL presumidos |
| Lucro Real | ICMS + PIS/COFINS 9,25% | ICMS + PIS/COFINS 9,25% |

Também considera que:
- produto com **ICMS-ST** não tem ICMS na revenda nem crédito;
- produto **monofásico** (PIS/COFINS CST 04, 05 ou 06) não tem PIS/COFINS na revenda;
- o PIS/COFINS é calculado sem o ICMS na base (Tema 69 do STF; Lei 14.592/2023 no crédito).

Em 2026 o IBS/CBS de teste é compensado com PIS/COFINS, então não muda o preço.

**Após a reforma (2033, estimativa)**: ICMS, PIS, COFINS e IPI deixam de existir. O IBS/CBS fica "por
fora" do preço e tudo o que é pago na compra vira crédito.
```
custo sem tributos = valor da operação − ICMS − FCP − PIS − COFINS que vinham embutidos
preço              = custo ÷ (1 − (IRPJ/CSLL + despesas + margem)) + IBS/CBS
```
A alíquota de IBS + CBS de 2033 ainda não está fixada (o padrão de 26,5% é uma estimativa e pode ser
alterado). Produtos com redução, como a cesta básica, usam a mesma redução da compra.

Os **parâmetros da empresa** (regime, DAS, ICMS na venda, IRPJ/CSLL, despesas, margem padrão, alíquota
de 2033) ficam na tabela `configuracoes` e valem para todos os produtos. A **margem** e o **ICMS na venda**
podem ser ajustados por produto. O botão "Salvar preço" grava o preço no cadastro e ele aparece na lista
de produtos.

É uma estimativa para apoiar a decisão, não um cálculo oficial: benefícios fiscais, regimes especiais e
regras de cada estado não estão incluídos.

## O que o sistema confere

**Regras gerais** (em `conferencia.py`)
- NCM ausente ou sem 8 dígitos; origem da mercadoria fora de 0 a 8
- Valor total do item diferente de quantidade × valor unitário
- CST × CSOSN errado para o regime do emitente (Simples Nacional usa CSOSN)
- ICMS, FCP, FCP-DIFAL, IPI, PIS ou COFINS com base × alíquota diferente do valor informado
- **Base do ICMS** diferente de produto + frete + seguro + outras despesas − desconto (com a redução da
  base, quando houver)
- **Alíquota interestadual** (CFOP 6xxx) diferente de 4%, 7% ou 12%, e **produto importado** (origem 1, 2,
  3 ou 8) fora dos 4% da Resolução do Senado 13/2012
- **ICMS-ST**: base diferente de valor da operação (+ IPI) com a **MVA** (e a redução da base ST);
  valor diferente de base ST × alíquota − ICMS próprio
- **FCP**: alíquota acima do limite de 2% (ADCT art. 82); FCP-ST diferente de base × alíquota − FCP próprio
- **DIFAL**: alíquota interestadual inválida ou diferente da alíquota do ICMS do item; partilha diferente
  de 100% para a UF de destino (regra desde 2019)
- NCM ou origem diferente do que já estava cadastrado para o produto

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

Os alertas **não bloqueiam** a importação: eles servem para a conferência humana, porque as regras (em
especial as da reforma e as de cada estado) mudam com frequência. O valor do DIFAL em si não é
recalculado, porque a fórmula varia por estado (base única ou base dupla). Notas com diferimento ou compra
governamental não têm os valores do IBS/CBS conferidos, porque o cálculo nesses casos é diferente.

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
| `06_horizonte_nf9214.xml` | Distribuidora de bebidas do RJ **sem o grupo IBS/CBS**: FCP de 2%, frete e desconto compondo a base, **FCP de 3%** e cerveja com ICMS-ST, FCP-ST e **base ST calculada com MVA errada** |
| `07_eletrosul_nf5530.xml` | Venda interestadual a consumidor final com **DIFAL** e FCP do destino: luminária importada a 4% (correta), **ventilador importado a 12%** e **DIFAL com alíquota interestadual diferente do ICMS** |

Os itens em **negrito** geram alertas na tela de Conferência. O `01` foi importado duas vezes para
mostrar a detecção de nota duplicada no histórico.

## Roteiro sugerido para a apresentação

1. Mostrar as pastas do projeto e abrir o `banco/nfe_importador.db` (ex.: no DB Browser for SQLite)
   para mostrar as 9 tabelas.
2. Rodar o sistema e mostrar o **Painel** com os indicadores.
3. **Notas fiscais**: abrir a NF 9214 e mostrar ICMS, FCP, ICMS-ST com MVA e FCP-ST de cada item. Depois
   abrir a NF 5530 e mostrar o DIFAL. Os itens marcados "REVISAR" mostram o motivo ao passar o mouse.
4. **Conferência**: filtrar "Regras gerais" (FCP, ST, alíquota interestadual, DIFAL) e depois "Reforma
   tributária" (cesta básica, cClassTrib × CST, alíquota de teste, nota sem IBS/CBS). Resolver um alerta
   e mostrar que ele vai para "Resolvidos".
5. **Produtos**: abrir a ficha da cerveja para mostrar a tributação completa (modalidade, MVA, base,
   alíquota). Abrir a ficha do arroz (2 compras com preços diferentes), corrigir o cClassTrib para
   200003 e salvar.
6. **Preço de venda**: no fim da ficha da água, mostrar a memória de cálculo de hoje e da reforma.
   Trocar o regime de Simples para Lucro Real e ver o preço mudar por causa dos créditos. Mostrar que
   a cerveja (ST e monofásico) não tem ICMS nem PIS/COFINS na revenda e que o arroz (cesta básica) fica
   sem IBS/CBS depois da reforma. Salvar o preço e mostrar a coluna "Preço venda" na lista.
7. **Fornecedores**: tentar excluir um fornecedor e mostrar o bloqueio pela chave estrangeira.
8. **Relatórios**: totais por tributo (incluindo FCP, ST e DIFAL) e por fornecedor.
9. **Importar XML**: excluir uma nota na tela de Notas e importá-la de novo pela pasta
   `xmls_exemplo/`. Importar outra vez para mostrar "Já importada" e importar o
   `05_arquivo_invalido.xml` para mostrar o erro tratado.
