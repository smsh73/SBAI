"""AI 챗봇 서비스 - NL-to-SQL + RAG"""
import re
import json
import logging
from app.core.llm_client import llm_chat
from app.services.db_service import execute_query, get_db_schema

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TEMPLATE = """당신은 SB선보(주)의 P&ID 도면 AI 분석 어시스턴트입니다.
사용자의 질문에 대해 SQLite 데이터베이스를 조회하여 정확한 답변을 제공합니다.

데이터베이스 스키마:
{schema}

규칙:
1. 사용자의 자연어 질문을 SQL 쿼리로 변환하세요.
2. SQL 쿼리는 ```sql ... ``` 블록으로 감싸세요.
3. SELECT 문만 허용됩니다 (INSERT, UPDATE, DELETE 금지).
4. 쿼리 결과를 바탕으로 한국어로 명확하게 답변하세요.
5. 밸브 관련 질문에는 valves 테이블을, PIPE BOM 관련 질문에는 pipe_bom 테이블을 사용하세요.
6. 치수 관련 질문에는 dimensions 테이블을 사용하세요.
7. 답변은 간결하고 전문적으로 작성하세요.

응답 형식:
- SQL 쿼리: ```sql SELECT ... ```
- 답변: 쿼리 결과를 요약한 한국어 텍스트
"""


async def chat(session_id: str, message: str) -> dict:
    """사용자 메시지 처리 → SQL 변환 → 실행 → 답변 생성"""
    schema = await get_db_schema()
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(schema=schema)

    # 세션 컨텍스트 추가
    context_msg = f"현재 세션: {session_id}\n사용자 질문: {message}"

    # LLM으로 SQL 생성
    llm_response = await llm_chat(system_prompt, context_msg)

    # SQL 추출
    sql_match = re.search(r'```sql\s*(.*?)\s*```', llm_response, re.DOTALL)
    sql_query = None
    query_result = None

    if sql_match:
        sql_query = sql_match.group(1).strip()

        # 안전성 검사: SELECT만 허용
        if not sql_query.upper().startswith("SELECT"):
            return {
                "response": "보안 정책에 의해 SELECT 쿼리만 실행할 수 있습니다.",
                "sql_query": sql_query,
                "data": None,
            }

        try:
            query_result = await execute_query(sql_query)

            # 결과를 포함하여 최종 답변 생성
            result_text = json.dumps(query_result[:50], ensure_ascii=False, indent=2)
            final_prompt = f"""다음 SQL 쿼리 결과를 바탕으로 사용자의 질문에 한국어로 답변하세요.

사용자 질문: {message}
SQL 쿼리: {sql_query}
쿼리 결과 ({len(query_result)}건):
{result_text}

간결하고 전문적으로 답변하세요. 표 형태로 정리하면 좋습니다."""

            final_response = await llm_chat(
                "당신은 조선/플랜트 도면 분석 전문가입니다. 한국어로 답변하세요.",
                final_prompt
            )
            return {
                "response": final_response,
                "sql_query": sql_query,
                "data": query_result[:100],
            }

        except Exception as e:
            logger.error(f"SQL execution error: {e}")
            return {
                "response": f"SQL 실행 중 오류가 발생했습니다: {str(e)}",
                "sql_query": sql_query,
                "data": None,
            }

    # SQL 없이 직접 답변
    return {
        "response": llm_response,
        "sql_query": None,
        "data": None,
    }
