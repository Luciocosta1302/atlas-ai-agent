# Arquitetura do Atlas AI

## Visão geral

```
Cliente HTTP
    │  POST /chat {"message": "..."}
    ▼
┌──────────────────────────── app/api ────────────────────────────┐
│ schemas.py   → valida entrada/saída (Pydantic)                  │
│ routes.py    → endpoint; converte AgentResult em ChatResponse   │
│ dependencies.py → monta o AgentService (injeção de dependência) │
└──────────────────────────────┬──────────────────────────────────┘
                               ▼
┌─────────────────────────── app/agent ───────────────────────────┐
│ service.py → executa o grafo, trata erros, extrai a resposta    │
│ graph.py   → StateGraph do LangGraph (loop ReAct)               │
│ prompts.py → system prompt                                      │
└───────────────┬─────────────────────────────────┬───────────────┘
                ▼                                 ▼
      app/llm.py (Gemini)               app/tools/ (ferramentas)
```

`app/config.py` centraliza as configurações (lidas de variáveis de ambiente).
`app/main.py` cria a aplicação FastAPI e registra os tratadores de erro.

## O loop do agente

```mermaid
graph TD
    START([início]) --> agent
    agent -. "pediu ferramenta e iterações < limite" .-> tools
    agent -. "resposta final" .-> END([fim])
    agent -. "limite atingido" .-> iteration_limit
    tools --> agent
    iteration_limit --> END
```

1. **agent**: o Gemini recebe o system prompt + histórico e decide se responde
   ou se pede uma ou mais ferramentas (*tool calling*). O contador `iterations`
   é incrementado.
2. **tools**: o `ToolNode` do LangGraph executa as ferramentas pedidas e adiciona
   o resultado como `ToolMessage` (a "observação").
3. O ciclo volta para **agent**, que agora enxerga o resultado.
4. Se o modelo ainda quiser ferramentas ao atingir `AGENT_MAX_ITERATIONS`, o nó
   **iteration_limit** encerra com uma mensagem explicativa.

## Decisões técnicas

| Decisão | Motivo |
| --- | --- |
| `StateGraph` explícito em vez de um agente pronto | Mostra cada etapa do loop e permite um limite de iterações com mensagem amigável. É a base para evoluções (memória, aprovação humana, streaming). |
| Agente único, sem multiagente | O MVP não precisa de coordenação entre agentes; menos peças, mais fácil de testar e explicar. |
| Modelo injetado em `build_agent_graph` | Permite trocar o Gemini por um modelo falso nos testes (sem rede e sem chave) ou por outro provedor no futuro. |
| Limite em duas camadas | O contador de iterações é o limite "de negócio"; o `recursion_limit` do LangGraph é a rede de segurança caso algo saia do previsto. |
| Ferramentas retornam `"Erro: ..."` em vez de lançar exceção | Erros esperados (divisão por zero, fuso inválido) viram observações que o modelo explica ao usuário. Erros inesperados são capturados pelo `ToolNode(handle_tool_errors=True)`. |
| Calculadora com AST e lista branca | `eval` executaria código arbitrário. Só números, operadores e funções explicitamente permitidas são aceitos; expoentes e tamanho da expressão são limitados para evitar abuso de CPU/memória. |
| Relatórios em diretório isolado | O modelo fornece apenas título e conteúdo; o nome do arquivo é gerado pelo servidor, o caminho é verificado após `resolve()`, arquivos nunca são sobrescritos (modo `"x"`) e o caminho absoluto não é exposto. |
| `pydantic-settings` + `SecretStr` | Chave apenas em variável de ambiente/`.env`; `SecretStr` evita que ela apareça em logs ou `repr`. |
| Serviço criado sob demanda | A API sobe e o `/health` responde mesmo sem chave; `/chat` devolve 503 com instrução clara. Como o FastAPI resolve dependências antes de validar o corpo, sem chave configurada o 503 aparece antes de um eventual 422. |
| Tratadores de exceção globais | Erros do provedor viram 502, falta de configuração vira 503, qualquer outro erro vira 500 genérico sem vazar detalhes internos. |
| Requisição sem estado | Cada `/chat` é independente. Memória de conversa é uma evolução planejada (checkpointer do LangGraph). |

## Códigos HTTP do `POST /chat`

| Código | Quando |
| --- | --- |
| 200 | Resposta gerada (inclusive quando o limite de iterações é atingido). |
| 422 | Corpo inválido: mensagem ausente, vazia, só espaços, tipo errado, campo extra ou acima de `MAX_MESSAGE_LENGTH`. |
| 502 | Falha ao consultar o Gemini (rede, cota, chave inválida) ou resposta vazia do modelo. |
| 503 | `GEMINI_API_KEY` não configurada. |
| 500 | Erro inesperado (detalhes apenas no log). |

## Estratégia de testes

- **Ferramentas**: testes unitários puros (casos válidos, entradas maliciosas, limites).
- **Agente**: `ScriptedChatModel` (em `tests/fakes.py`) é um `BaseChatModel` que
  devolve respostas roteirizadas, incluindo *tool calls*. Isso testa o grafo real
  (roteamento, execução de ferramentas, limite de iterações) sem chamar a API.
- **API**: `TestClient` + `app.dependency_overrides` para injetar o agente falso.
