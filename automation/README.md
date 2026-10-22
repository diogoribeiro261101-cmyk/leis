# Monitoramento do fork

Este fork acompanha `ctresb/leis`. A auditoria foi adicionada em 22/10/2026.

## Como ativar

Abra [Actions](https://github.com/diogoribeiro261101-cmyk/leis/actions) e, se o GitHub solicitar, clique para habilitar workflows neste fork. Abra **Monitorar e sincronizar leis** e clique em **Run workflow** na branch `main` para o primeiro teste.

O workflow está em `.github/workflows/monitorar-leis.yml` e verifica duas vezes por dia (04:23 e 16:23, UTC-3). Veja os logs, o resumo da execução e `automation/monitor_state.json` para acompanhar resultados. O arquivo de estado só é criado na primeira execução concluída do monitor.

## O que será feito

- Compara a cópia ao repositório público de origem.
- Só integra mudanças pequenas em Markdown que passem nas verificações.
- Bloqueia mudanças em scripts, workflows, arquivos não Markdown, exclusões, lotes grandes, indícios de truncamento e indícios de prompt injection.
- Calcula hashes de quatro páginas do Planalto (CF, CLT, Código Civil, Lei 14.133) e informa quando uma página parece ter mudado.

O monitor **não** substitui consulta à publicação oficial nem comprova que os textos foram consolidados, atualizados ou estão vigentes. Mudanças bloqueadas precisam de revisão humana e não se integram sozinhas. O repositório de origem contém textos identificados como incompletos (ver [ocorrência nº 3](https://github.com/ctresb/leis/issues/3)), que não são automaticamente corrigidos.

O acervo municipal do projeto não inclui Itaituba/PA na verificação inicial. Para manter normas locais, é necessária uma integração específica com fonte oficial municipal.

O monitor usa apenas Python padrão e o token temporário do GitHub Actions. Não execute scripts recebidos do upstream sem revisão. 
