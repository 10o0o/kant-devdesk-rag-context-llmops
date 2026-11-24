"""main.py의 todo(...) 부분을 작성하세요. support.py와 checks.py는 그대로 사용합니다."""

import copy
import hashlib
import json
import sys

import support


def todo(message):
    raise NotImplementedError(message)


# 필수 1. 필요한 자료와 사용자 기억 관리하기
def select_context(items, user_id, now):
    kept = []
    for item in items:
        allowed = (
            item["user_id"] in ("public", user_id)
            and item["trusted"]
            and item["active"]
            and (item["expires_at"] is None or item["expires_at"] > now)
        )
        if allowed:
            kept.append(copy.deepcopy(item))

    # 이유: 높은 우선순위의 자료를 먼저 고르면 어떤 문제가 생기는지 적으세요.
    # 사용 가능 여부 등 실제로 자료를 사용해도 되는지 검사하지 않으면 보안상 문제가 되는
    # 혹은 의도치 않은 자료가 들어갈 수 있다.

    return sorted(kept, key=lambda item: (-item["priority"], item["id"]))


def memory_action(records, user_id, action, name, value=None):
    support.validate_memory_input(user_id, action, name, value)
    key = f"{user_id}:{name}"
    if action == "read":
        return copy.deepcopy(records.get(key, None))
    if action == "create":
        if key in records:
            raise ValueError("이미 있는 기억입니다. update를 사용하세요.")

        records[key] = copy.deepcopy(value)
    elif action == "update":
        if key not in records:
            raise KeyError("수정할 기억이 없습니다.")

        records[key] = copy.deepcopy(value)
    elif action == "delete":
        return records.pop(key, None)

    return copy.deepcopy(records[key])


def build_messages(prefix, question, context, turns, summary):
    data = json.dumps(
        {"reference_data": context, "summary": summary}, ensure_ascii=False
    )
    history = [message for turn in turns for message in turn["messages"]]
    # 이유: 장기 기억과 세션 상태의 차이, 자료와 지시를 나누는 이유를 적으세요.
    # 장기 기억은 세션이 끝나도 유지되는 기억이고, 세션 상태는 해당 세션에 한정된다는 차이가 있다.
    # 지시는 모델에게 어떻게 답할지 정해주고, 자료는 답변에 필요한 사실을 준다는 차이가 있다.

    return [
        {"role": "developer", "content": prefix},
        {"role": "user", "content": data},
        *history,
        {"role": "user", "content": question},
    ]

    return todo("고정 지시, 참고 자료, 대화, 현재 질문 순서의 메시지")


# 필수 2. 긴 대화를 줄이고 반복 입력 재사용하기
def summarize(turns):
    summary = {}
    for turn in turns:
        for name, value in support.fact_lines(turn["messages"][0]["content"]):
            summary[name] = {"value": value, "source_turn_id": turn["id"]}
    return summary


def select_window(turns, limit, reserve, margin, make_messages, count):
    support.validate_budget(limit, reserve, margin)
    budget = limit - reserve - margin
    if budget <= 0 or count(make_messages([])) > budget:
        raise ValueError("고정 입력만으로 예산을 넘었습니다.")
    kept = []
    for turn in reversed(turns):
        candidate = [turn, *kept]
        total_candidate_inputs = make_messages(candidate)
        if count(total_candidate_inputs) > budget:
            break
        kept = candidate
    # 최근 대화만 넣었을 때 담당자와 마감일을 확인하지 못했고, 승인조건에서 보안팀 검토가 빠졌다.
    # 요약과 최근 대화를 함께 쓰면 입력 예산 1,788토큰 안에서 세 사실을 모두 보존했다.
    # 전체 대화보다 실제 입력이 243토큰 적어서 이 방식을 선택했다.
    return kept


def cache_key(prefix, user_id):
    text = f"{user_id}\n{prefix}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
    # 캐시 비사용은 읽기·쓰기 모두 0이었다. 캐시 첫 사용은 1,228토큰 쓰기,
    # 재사용은 1,228토큰 읽기가 관측됐다.
    # 비사용, 첫 쓰기, 재사용의 추정 입력 비용은 각각 $0.00030660, $0.00036800, $0.00008556이었다.
    # 최종 입력에서 tainted-document와 unverified-tool이 제외된 것을 확인했다.


# 선택 심화 1. 새 대화만 반영하고 변경 이력 남기기
def merge_summary(previous, turns):
    copied = copy.deepcopy(previous)

    for turn in turns:
        turn_id = turn["id"]

        if turn_id in copied["processed_ids"]:
            continue

        copied["processed_ids"].append(turn_id)

        for category, dic in summarize([turn]).items():
            before = copied["current"].get(category)

            if before is not None and before["value"] != dic["value"]:
                copied["changes"].append(
                    {
                        "name": category,
                        "before": before,
                        "after": dic,
                    }
                )
            copied["current"][category] = dic

    return copied


if __name__ == "__main__":
    raise SystemExit(support.cli(sys.modules[__name__]))
