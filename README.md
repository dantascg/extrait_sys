# Extrait Club System

O **Extrait Club System** é uma aplicação monolítica desenvolvida para a gestão interna e automação de operações envolvendo fracionados (decants) na perfumaria de nicho. O sistema tem como objetivo principal centralizar o fluxo de recebimento de pedidos, controle de estoque a nível de mililitros e emissão de cobranças em lote.

## Arquitetura e Contexto

O domínio do negócio envolve a extração de intenções de compra a partir de textos brutos não estruturados (geralmente gerados em grupos de mensagens) e a consolidação desses dados em um modelo relacional seguro. 

A arquitetura foi projetada para garantir que nenhuma transação seja perdida ou sobrescrita em concorrência, além de transformar a entrada não determinística de dados em informações precisas para a tomada de decisão, gestão de estoque e faturamento por parte do operador logístico.

## Desafios e Soluções (Estudo de Caso)

### 1. Arquitetura em Camadas (Service Layer)
Para manter o isolamento de responsabilidades, as lógicas densas de negócio, chamadas de API de terceiros e algoritmos de matching heurístico de clientes foram desacopladas para uma camada de serviços (`services.py`). Isso mantém as *views* extremamente finas (*Fat Models / Thin Views*), focadas estritamente na orquestração de requisições HTTP e delegação de estado.

### 2. Processamento Não Estruturado via LLM
Em vez de depender de expressões regulares frágeis para a leitura de dezenas de mensagens em formatos inconsistentes, o sistema integra a Groq API com o modelo **LLaMA 3.3 70B** para realizar o *parsing* de textos em linguagem natural. A LLM recebe instruções estritas (*prompt engineering*) e devolve a saída tipada e previsível em formato JSON (*Structured Output*), lidando organicamente com variações linguísticas, jargões e erros de digitação.

### 3. Fluxo de Validação Draft-First
Para eliminar os riscos de injeção direta no banco de dados e garantir 100% de precisão nos inputs processados por IA, foi implementada a abordagem *Draft-First*. Os dados gerados pela LLM são armazenados provisoriamente de maneira segura na sessão em nível de servidor (`request.session`). O operador humano avalia, cruza os dados com o histórico real da aplicação e realiza as devidas correções ou resoluções de conflitos na interface antes de comitar a versão final atomicamente no banco.

### 4. Integridade de Transações e Performance de ORM
O projeto faz uso intensivo de transações ACID por meio do decorator `@transaction.atomic` em operações críticas (ex: faturamento em lote e transferência dinâmica de volume de frascos). Em paralelo, problemas comuns de gargalo como as *N+1 queries* foram eliminados utilizando estratégias avançadas de *prefetching* de dados com relacionamentos complexos, garantindo painéis de clientes (CRM) e de faturamento (Cobrança) fluidos e performáticos sob alta demanda computacional, realizando processamento analítico em memória quando prudente.

## Tecnologias Utilizadas

- **Linguagem:** Python 3
- **Framework Web:** Django 5
- **Inteligência Artificial:** Groq API (LLaMA 3.3 70B)
- **Banco de Dados:** SQLite (escalável de forma nativa via ORM)
- **Frontend:** HTML5 (Server-Side Rendering), CSS3 Customizado Vanilla
- **APIs Nativas:** JavaScript (Clipboard API e integrações modais)

## Exemplo de Código

O trecho estrutural abaixo ilustra a responsabilidade da camada de serviço garantindo um output previsível estruturado a partir da LLM:

```python
import json
import logging
from groq import Groq

logger = logging.getLogger(__name__)

def extrair_dados_ia(texto_bruto: str) -> dict:
    """
    Orquestra o parsing de linguagem natural para dicionário estruturado
    através da Groq API com LLaMA 3.3 70B.
    """
    client = Groq()
    prompt = _PROMPT_TEMPLATE.format(texto_bruto=texto_bruto)

    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_completion_tokens=4000,
        )
        
        raw_response = completion.choices[0].message.content.strip()
        
        # Limpeza robusta do Output Markdown
        if raw_response.startswith("```"):
            raw_response = raw_response.replace("```json", "").replace("```", "").strip()

        return json.loads(raw_response)

    except json.JSONDecodeError as exc:
        logger.error("Falha ao decodificar JSON.")
        raise ValueError("Saída não-estruturada detectada. Rever entradas.") from exc
```

## Como Rodar Localmente

Certifique-se de que o Python 3 esteja instalado no seu ambiente.

1. Clone o repositório:
```bash
git clone https://github.com/SEU_USUARIO/extrait-club.git
cd extrait-club
```

2. Crie e ative o ambiente virtual:
```bash
python -m venv venv

# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate
```

3. Instale as dependências essenciais:
```bash
pip install -r requirements.txt
```

4. Configure as variáveis de ambiente:
Crie um arquivo `.env` na raiz do projeto com as seguintes credenciais obrigatórias:
```env
DJANGO_SECRET_KEY=uma-chave-aleatoria-muito-segura
DEBUG=True
GROQ_API_KEY=sua-chave-api-groq
```

5. Aplique as migrações do banco de dados:
```bash
python manage.py migrate
```

6. Inicie o servidor local:
```bash
python manage.py runserver
```

Acesse o sistema localmente via: `http://127.0.0.1:8000/`.

## Créditos

Desenvolvido por Leonardo Dantas.
