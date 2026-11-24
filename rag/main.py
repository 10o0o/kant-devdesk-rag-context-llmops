"""KANT NEXT DevDesk RAG. 이 파일의 빈칸만 작성하세요."""

from qdrant_client import models

import support


def todo(message):
    raise NotImplementedError(message)


# 필수 1. 문서를 저장하고 현행 자료만 검색하기
def prepare_chunks(documents):
    chunks = []

    for document in documents:
        seen = set()
        number = 0
        for paragraph in document["paragraphs"]:
            # text = todo("문단의 연속 공백을 한 칸으로 정리하세요.")
            text = " ".join(paragraph.split())
            if not text or text == "KANT NEXT | 내부 문서" or text in seen:
                continue
            seen.add(text)
            chunk = {
                "document_id": document["document_id"],
                "title": document["title"],
                "category": document["category"],
                "status": document["status"],
                "source": document["source"],
                "chunk_id": f"{document['document_id']}:{number}",
                "text": text,
            }
            chunks.append(chunk)
            number += 1

    # 이유: 문단 단위를 유지하면 승인부터 다중 인증까지 한 절차의 맥락이 함께 남는다.
    # source는 원문 위치를, chunk_id는 원문 안의 문단을 찾는 데 쓴다.
    return chunks


def build_index(chunks, embedder):
    texts = ["passage: " + row["title"] + "\n" + row["text"] for row in chunks]
    vectors = embedder.encode(texts, normalize_embeddings=True)
    client = support.empty_store(len(vectors[0]))
    points = []
    for i, (row, vector) in enumerate(zip(chunks, vectors, strict=True)):
        point = models.PointStruct(id=i, vector=list(vector), payload=row)
        # point = todo("i, vector, row를 Qdrant PointStruct에 연결하세요.")
        points.append(point)
    client.upsert(collection_name="devdesk", points=points, wait=True)
    return client


def search(client, embedder, question, category, top_k=2):
    if type(top_k) is not int or not 1 <= top_k <= 5:
        raise ValueError("top_k는 1~5의 정수여야 합니다.")
    status_condition = models.FieldCondition(
        key="status", match=models.MatchValue(value="current")
    )
    category_condition = models.FieldCondition(
        key="category", match=models.MatchValue(value=category)
    )

    vector = embedder.encode(["query: " + question], normalize_embeddings=True)[0]
    scope = models.Filter(must=[status_condition, category_condition])
    hits = client.query_points(
        collection_name="devdesk",
        query=list(vector),
        query_filter=scope,
        limit=top_k,
        with_payload=True,
    ).points
    return [{**hit.payload, "score": hit.score} for hit in hits]


# 필수 2. 별칭 검색을 개선하고 답변을 비교하기
def rewrite_query(question, aliases):
    rewritten = question
    for alias, formal_name in aliases.items():
        rewritten = rewritten.replace(alias, formal_name)
    return rewritten


def answer_question(question, rows, generate):
    if not rows:
        return {
            "answer": "확인할 문서가 없습니다.",
            "citations": [],
            "needs_human": True,
        }

    context = "\n\n".join([f"[{r['chunk_id']}] {r['text']}" for r in rows])
    reply = support.validate_shape(generate(question, context))
    allowed = {row["chunk_id"] for row in rows}
    if any(citation not in allowed for citation in reply["citations"]):
        raise ValueError("검색하지 않은 출처가 있습니다.")
    if reply["needs_human"] == bool(reply["citations"]):
        raise ValueError("답변에는 출처가 필요하며 담당자 확인에는 출처를 비웁니다.")
    return reply


def make_golden():
    return [
        {
            "question_id": "custom-token-exposure",
            "question": "임시열쇠가 외부에 노출되면 어떤 조치를 해야 하나요?",
            "category": "access",
            "reference_answer": "노출된 API 토큰은 즉시 폐기하고 새 토큰을 발급합니다.",
            "relevant_document_ids": ["token"],
            "required_terms": ["폐기", "새 토큰"],
        },
        {
            "question_id": "custom-overseas-guest-wifi",
            "question": "해외 지사를 방문할 때 게스트 Wi-Fi 계정은 어디에서 발급받나요?",
            "category": "overseas",
            "reference_answer": "제공 문서에는 해외 지사의 게스트 Wi-Fi 계정 발급 절차가 없습니다.",
            "relevant_document_ids": [],
            "required_terms": [],
        },
    ]


def measure(case, rows, reply):
    expected = set(case["relevant_document_ids"])
    found = {row["document_id"] for row in rows}
    recall = None if not expected else len(expected & found) / len(expected)
    answer_ok = (
        (
            all(term in reply["answer"] for term in case["required_terms"])
            and not reply["needs_human"]
        )
        if expected
        else reply["needs_human"]
    )

    failure = "없음"
    if expected and recall < 1:
        failure = "검색 누락"
    elif not answer_ok:
        failure = "답변 확인 필요" if expected else "보류 실패"
    # 관측: 실제 evaluate 결과에서 개선, 악화 질문과 답변 본문을 확인해 기록합니다.
    return {
        "document_recall": recall,
        "answer_check": bool(answer_ok),
        "failure": failure,
    }


# 선택 심화 1. 두 검색 순위를 합쳐 근거를 모으기
def fuse_rankings(rankings, top_k=2):
    if type(top_k) is not int or not 1 <= top_k <= 5:
        raise ValueError("top_k는 1~5의 정수여야 합니다.")

    merged = {}

    for ranking in rankings:
        seen = set()

        for row in ranking:
            chunk_id = row["chunk_id"]
            if chunk_id in seen:
                continue

            seen.add(chunk_id)
            score = 1 / (60 + len(seen))

            if chunk_id in merged:
                merged[chunk_id]["score"] += score
            else:
                merged[chunk_id] = {**row, "score": score}

    ranked = sorted(merged.values(), key=lambda row: (-row["score"], row["chunk_id"]))
    return ranked[:top_k]


if __name__ == "__main__":
    support.cli(globals())
