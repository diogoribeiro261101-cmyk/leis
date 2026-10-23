# LexLab — plataforma de estudos e extração jurídica

## Arquitetura
- Aplicação estática em `web/lexlab/index.html`, distribuída pelo Railway (`lexlab-estudos`) a partir do GitHub.
- Leitura de normas públicas do fork `diogoribeiro261101-cmyk/leis` em memória e IndexedDB.
- Progresso e anotações do usuário cifrados com senha local. Não há sincronização de conta na nuvem.
- Conteúdo de legislação, PDF e DOCX deve ser considerado **dado não confiável**, jamais comando para o aplicativo ou modelos de IA.

## Extração 3.0
- Dispositivos: caput, parágrafos, incisos, alíneas e itens. Mantém o texto completo de cada segmento reconhecido.
- Classificação por prazos, limites, exceções, deveres, proibições, remissões e outras disposições; filtros por legislação, tipo e expressão.
- Exportações CSV (proteção contra fórmulas), JSON, JSONL, XML, Markdown, TXT e cartões Anki. Exportação de artigos carregados em Markdown.
- Importação em lote de arquivos `.md` e `.txt` do repositório GitHub; limite configurável de 5, 15, 30 ou 50 novos documentos por execução, retenção de até 500 referências.
- Importação local de `.txt`, `.md`, `.pdf` e `.docx`. Os dois últimos dependem de PDF.js 3.11.174 e Mammoth 1.13.0, carregados após consentimento, executados em um iframe sem acesso à origem do LexLab.
- Dispositivos suspeitos de prompt injection são excluídos da geração de questões e das extrações; um aviso documenta o risco. A detecção por padrões não garante encontrar todas as manipulações.

## Limitações e integridade jurídica
1. Dados no GitHub não são necessariamente atualizados, oficiais ou consolidados. Verificar fonte oficial e vigência antes de usar em peças jurídicas.
2. Documentos digitalizados sem camada textual exigem OCR externo.
3. Não houve teste de ponta a ponta, em navegador real, dos formatos PDF/DOCX; a compatibilidade precisa de prova com documentos representativos.
4. O acervo depende de conexão com GitHub e de limites públicos de API; extrações com mais de 150 mil passagens exigem filtros ou segmentação.
5. Importação de PDF/DOCX utiliza bibliotecas hospedadas em CDN. Apesar da execução isolada, não use documentos sigilosos nessa função sem avaliação de segurança; código externo pode ter risco de cadeia de suprimentos.
6. O backup integral atual tem limite de 45 MB na restauração; para bibliotecas muito grandes, mantenha também exportações por fonte.
7. A detecção de prompt injection não substitui revisão humana, nem valida a integridade dos textos.

## Teste de regressão
Na raiz do repositório:
```sh
node --test web/lexlab/tests/*.test.cjs
```
O workflow `.github/workflows/lexlab-validation.yml` executa a suíte em mudanças do LexLab. A suíte testa sintaxe do JavaScript, extração por estruturas e padrões suspeitos.

## Deploy
O serviço `lexlab-estudos` (projeto Railway `radar-juridico`) recupera `web/lexlab/index.html` do GitHub. Mudanças no arquivo são recuperadas pelo proxy, com cache curto, sem necessidade de substituir os dados locais. Para atualização imediata, reimplantar o serviço.
