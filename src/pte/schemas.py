"""Pydantic schemas for PTE Agent.

가이드라인 §3.2:
- plan 출력은 JSON Schema로 강제
- step_id, tool, input은 필수
- task는 설명용(optional)
"""

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    """실행 계획의 단일 스텝.

    Attributes:
        step_id: 고유 식별자 (순차적, 자동 부여 가능)
        tool: 실행할 도구 이름
        input: 도구에 전달할 입력값
        input_from: 이전 step의 output 참조 (예: "step_1")
        task: 이 스텝이 수행하는 작업 설명 (Executor는 읽지 않음)
    """

    step_id: int | None = Field(default=None, description="스텝 고유 식별자")
    tool: str = Field(description="실행할 도구 이름")
    input: str | dict | None = Field(default=None, description="도구 입력값")
    # LLM이 다른 필드명을 사용할 수 있으므로 alias 추가
    query: str | None = Field(default=None, description="검색 쿼리 (input 대신 사용 가능)")
    input_from: str | None = Field(default=None, description="이전 step output 참조")
    task: str | None = Field(default=None, description="작업 설명 (선택)")

    def get_input(self) -> str | dict | None:
        """실제 입력값 반환 (input 또는 query)."""
        return self.input or self.query


class Plan(BaseModel):
    """실행 계획.

    Attributes:
        steps: 실행할 스텝 목록 (순서대로 실행)
        reasoning: 이 계획을 세운 이유 (디버깅용)
    """

    steps: list[PlanStep] = Field(description="실행할 스텝 목록")
    reasoning: str | None = Field(default=None, description="계획 수립 이유")


class ReplanPatch(BaseModel):
    """재계획 패치.

    가이드라인 §6.2: patch 방식으로 계획 수정 권장
    """

    action: str = Field(description="수행할 액션: replace, insert, remove")
    step_id: int | None = Field(default=None, description="대상 step_id")
    new_step: PlanStep | None = Field(default=None, description="새 스텝 (replace, insert)")
    reason: str = Field(description="수정 이유")


class Replan(BaseModel):
    """재계획 결과.

    Attributes:
        patches: 적용할 패치 목록
        new_plan: 완전히 새로운 계획 (patches 대신 사용 가능)
    """

    patches: list[ReplanPatch] | None = Field(default=None, description="패치 목록")
    new_plan: Plan | None = Field(default=None, description="새 계획 (전체 교체 시)")
    analysis: str = Field(description="실패 원인 분석")
