import os
import re
import json
from datetime import datetime, timezone

import google.generativeai as genai

# 1. 깃허브 금고에서 열쇠(API KEY) 꺼내서 세팅하기
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    print("오류: GEMINI_API_KEY 환경변수가 설정되지 않았습니다. GitHub Secrets를 확인해 주세요.")
    exit(1)

genai.configure(api_key=API_KEY)

# ---------------------------------------------------------------------------
# 1-1. 사용할 모델 — 버전을 하나만 박아두지 않는다 (2026-09-04)
#
# 배경: 이 스크립트는 오랫동안 'gemini-2.5-flash'를 하드코딩하고 있었다.
#   그런데 **바로 그 모델이 KDailyUtil 앱에서 신규 계정 404로 죽었던 모델**이다(2026-08-12 장애).
#   지금은 이 저장소의 개발자 키로 돌기 때문에 아직 통하지만, 구글이 모델을 내리는 날
#   이 로봇은 **아무 소리 없이 멈춘다** — 실패해도 알려 주는 사람이 없기 때문이다.
#   앱의 「오늘의 퀴즈」가 이 공급에 의존하게 됐으므로(2026-09-04) 같은 방어를 여기에도 넣는다.
#
# 규칙(앱 GeminiManager와 같다):
#   - 404(모델 없음)·503(과부하)이면 **다음 후보로 넘어간다**
#   - 429(할당량)·키 오류는 모델을 바꿔도 소용없다 → 넘어가지 않고 즉시 실패
#   - QUIZ_MODEL 환경변수로 **코드 수정 없이** 모델을 갈아끼울 수 있다(비상 레버)
# ---------------------------------------------------------------------------
MODEL_CANDIDATES = [
    m for m in [
        os.environ.get("QUIZ_MODEL", "").strip(),  # 비상 레버(Actions 변수)
        "gemini-flash-latest",                     # 별칭 — 구글이 알아서 최신으로 매핑한다
        "gemini-3.5-flash",
        "gemini-3.6-flash",
    ] if m
]

HEARTBEAT_FILE = "last_run.json"


def _looks_like(err_text, needles):
    low = str(err_text).lower()
    return any(n in low for n in needles)


def is_model_unavailable(err):
    """이 모델이 없거나(404) 지금 붐빈다(503) → 다른 모델로 넘어갈 만한 실패인가."""
    return _looks_like(err, ["404", "not found", "is not supported", "503", "unavailable", "overloaded"])


def is_quota_or_key_error(err):
    """모델을 바꿔도 소용없는 실패(할당량·키). 넘어가지 않고 즉시 멈춘다."""
    return _looks_like(err, ["429", "resource_exhausted", "quota", "api key", "api_key", "permission", "401", "403"])


def write_heartbeat(status, model_used=None, saved=0, skipped=None, error=None):
    """
    **실패해도 반드시 남기는 생존 신호.**

    두 가지 목적이 있다.
      1. 사람이 파일 하나만 열어 보면 «로봇이 살아 있나»를 안다(며칠 방치해도).
      2. GitHub은 **60일간 활동이 없는 저장소의 예약 워크플로를 자동으로 끈다.**
         로봇이 실패하면 새 문제가 없어 커밋도 안 생기고, 그대로 두 달이 지나면
         스케줄 자체가 꺼져 **되살릴 때까지 영구 정지**한다.
         매 실행마다 이 파일이 바뀌어 커밋이 생기므로 그 침묵사(死)를 막는다.
    """
    totals = {}
    for fn in ALL_FILES:
        try:
            totals[fn] = len(load_json(fn))
        except Exception:
            totals[fn] = None

    payload = {
        "status": status,                     # ok | failed
        "ranAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": model_used,
        "savedThisRun": saved,
        "skipped": skipped or {},
        "totals": totals,
        "totalAll": sum(v for v in totals.values() if isinstance(v, int)),
        "error": error,
    }
    try:
        with open(HEARTBEAT_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"🫀 생존 신호 기록: {status} (모델 {model_used}, 누적 {payload['totalAll']}문항)")
    except Exception as e:
        print(f"생존 신호 기록 실패(무시하고 계속): {e}")


def fail(message, model_used=None):
    """실패하더라도 **생존 신호를 남긴 뒤** 죽는다. 조용히 사라지는 것이 가장 나쁘다."""
    print(f"문제 발생: {message}")
    write_heartbeat("failed", model_used=model_used, error=str(message)[:500])
    exit(1)


def generate_with_fallback(prompt):
    """후보 모델을 차례로 시도한다. 성공하면 (응답, 쓴 모델 이름)."""
    last_error = None
    for name in MODEL_CANDIDATES:
        try:
            print(f"모델 시도: {name}")
            response = genai.GenerativeModel(name).generate_content(prompt)
            print(f"✅ 모델 {name} 응답 성공")
            return response, name
        except Exception as e:
            last_error = e
            if is_quota_or_key_error(e):
                # 할당량·키 문제는 모델을 바꿔도 그대로다 → 후보를 더 태우지 않는다
                fail(f"할당량 또는 키 문제로 중단: {e}", model_used=name)
            if is_model_unavailable(e):
                print(f"  ↪ {name} 사용 불가({str(e)[:120]}) — 다음 후보로")
                continue
            print(f"  ↪ {name} 실패({str(e)[:120]}) — 다음 후보로")
    fail(f"모든 후보 모델이 실패했습니다. 마지막 사유: {last_error}")

# ---------------------------------------------------------------------------
# 0. 기존 데이터 로드 — 중복 방지(정답/질문)와 프롬프트 회피 목록 구성에 사용
# ---------------------------------------------------------------------------
ALL_FILES = ["korean.json", "trend.json", "knowledge.json", "travel.json", "quiz_updates.json"]
category_map = {
    "우리말 겨루기": "korean.json",
    "트렌드 말하기": "trend.json",
    "상식 백과": "knowledge.json",
    "세계 여행": "travel.json"
}
# 카테고리별 ID 시작 대역 (정리된 데이터 규칙과 동일하게 유지)
id_base = {"korean.json": 10001, "trend.json": 20001, "knowledge.json": 30001, "travel.json": 40001}
CATEGORIES = ["우리말 겨루기", "트렌드 말하기", "상식 백과", "세계 여행"]


def load_json(file_name):
    if os.path.exists(file_name):
        with open(file_name, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []


def norm(s):
    return "".join(str(s).split()).lower()


def trend_concept(q):
    """트렌드(신조어) 개념 키: 정답이 짧은 단어면 그 단어, 아니면 질문 속 인용된 신조어.
    같은 신조어를 '단어 묻기'(정답=단어)와 '뜻 묻기'(정답=정의) 양방향으로 중복 출제하는 것을 막기 위함."""
    ans = q.get("answer", "").strip()
    if 0 < len(ans) <= 6 and " " not in ans:
        return norm(ans)
    m = re.findall(r"['\"‘’“”「」]([^'\"‘’“”「」]{2,10})['\"‘’“”「」]", q.get("question", ""))
    if m:
        return norm(m[0])
    return None


used_ids = set()
existing_questions = set()                 # (category, norm question)
existing_answers = set()                   # (category, norm answer)
trend_concepts = set()                     # 이미 다룬 신조어 개념(정규화)
trend_concepts_display = []                 # 프롬프트 표시용(원문)
answers_by_category = {c: [] for c in CATEGORIES}  # 프롬프트 회피 목록(표시용 원문 정답)
_seen_answer_display = set()
_seen_concept_display = set()

for fn in ALL_FILES:
    for q in load_json(fn):
        if isinstance(q.get("id"), int):
            used_ids.add(q["id"])
        cat = q.get("category", "")
        ans = q.get("answer", "")
        existing_questions.add((cat, norm(q.get("question", ""))))
        existing_answers.add((cat, norm(ans)))
        if cat in answers_by_category and ans:
            disp_key = (cat, norm(ans))
            if disp_key not in _seen_answer_display:
                _seen_answer_display.add(disp_key)
                answers_by_category[cat].append(ans)
        if cat == "트렌드 말하기":
            c = trend_concept(q)
            if c:
                trend_concepts.add(c)
                # 표시용: 단어형 정답이면 그 단어, 아니면 질문 속 인용 단어
                disp = ans.strip() if (0 < len(ans.strip()) <= 6 and " " not in ans.strip()) else c
                if disp not in _seen_concept_display:
                    _seen_concept_display.add(disp)
                    trend_concepts_display.append(disp)

# 이미 출제된 정답 목록(카테고리별)을 프롬프트에 주입 → 같은 정답 반복 생성 방지
avoid_lines = []
for c in CATEGORIES:
    if answers_by_category[c]:
        avoid_lines.append(f"- {c}: " + ", ".join(answers_by_category[c]))
avoid_block = "\n".join(avoid_lines) if avoid_lines else "(아직 없음)"

# 트렌드(신조어)는 단어/뜻 양방향 중복을 막기 위해 '이미 다룬 신조어' 목록을 별도 주입
trend_avoid = ", ".join(trend_concepts_display) if trend_concepts_display else "(아직 없음)"

# ---------------------------------------------------------------------------
# 2. 제미나이 AI에게 지시할 내용 (프롬프트 고도화)
# ---------------------------------------------------------------------------
prompt = f"""
한국어 퀴즈 앱에 들어갈 고품질의 퀴즈 5개를 만들어주세요. 매번 똑같은 문제가 나오지 않도록 매우 다양하고 교육적인 문제로 구성해주세요.

[문제 구성 (총 5개)]
1. '우리말 겨루기' 카테고리: 맞춤법, 고유어, 사자성어 중 1개 (subCategory에 상세 분류 기입)
2. '트렌드 말하기' 카테고리: 최신 유행어/신조어 1개
3. '상식 백과' 카테고리: 역사, 과학, 시사 상식 중 2개
4. '세계 여행' 카테고리: 국가 수도, 국기, 명소 관련 1개

[이미 출제된 정답 — 같은 정답이 나오는 문제는 절대로 만들지 마세요]
아래는 카테고리별로 이미 출제된 정답(answer) 목록입니다. 질문을 다르게 바꾸더라도 '정답'이 아래 목록에 이미 있는 것과 같으면 절대 출제하지 마세요. 반드시 목록에 '없는' 새로운 정답이 나오는 문제만 만드세요.
{avoid_block}

[이미 다룬 신조어 — 단어/뜻 어느 방향으로도 다시 출제 금지]
아래 신조어들은 이미 출제되었습니다. '이 신조어의 뜻은?'(정답=뜻)이든 '이런 뜻의 신조어는?'(정답=신조어)이든, 아래 단어가 관련된 문제는 절대 만들지 마세요. 완전히 새로운 신조어만 다루세요.
{trend_avoid}

[필수 조건]
- category는 반드시 '우리말 겨루기', '트렌드 말하기', '상식 백과', '세계 여행' 중 하나를 선택하세요.
- subCategory에는 문제의 세부 분류(예: '맞춤법', '역사', '국가수도')를 적으세요.
- 객관식 문제(MULTIPLE_CHOICE)는 반드시 4개의 보기를 제공하고, 주관식(SUBJECTIVE)은 보기를 null로 하세요.
- answer(정답) 항목은 객관식일 경우 options에 있는 글자와 띄어쓰기 하나까지 완벽하게 일치해야 합니다.
- 절대 answer(정답) 항목이나 options(보기) 항목에 한자(漢字)나 괄호()를 넣지 마세요. 오직 순수 한글로만 작성하세요.
- explanation(해설)에는 왜 정답인지 상세히 적어주세요.
- semanticHint(의미적 힌트)에는 정답을 유추할 수 있는 재미있는 힌트를 적어주세요.
- id 값은 0으로 두세요. (저장 시 프로그램이 전역 유니크 ID를 자동 부여합니다.)
- '갓생', '오운완', '자만추', '킹받네' 같은 흔한 신조어나, 각국 수도(파리·로마 등)·대기 중 가장 많은 기체 같이 누구나 아는 뻔한 사실의 '반복 출제'는 피하고, 새롭고 다양한 정답이 나오도록 출제하세요.
- 반드시 아래 JSON 배열 형식으로만 대답해주세요. 추가적인 말이나 마크다운 백틱(`)은 절대 하지 마세요.

[
  {{
    "id": 12345,
    "type": "MULTIPLE_CHOICE",
    "category": "상식 백과",
    "subCategory": "과학",
    "question": "다음 중...",
    "options": ["1번", "2번", "3번", "4번"],
    "answer": "정답",
    "explanation": "해설",
    "semanticHint": "의미적 힌트"
  }}
]
"""

# 3. AI에게 물어보기 (모델 폴백 경유)
print("AI에게 문제를 요청 중입니다...")
response, MODEL_USED = generate_with_fallback(prompt)

try:
    # JSON 부분만 추출하기 위한 더 강력한 로직
    raw_text = response.text.strip()
    start_idx = raw_text.find('[')
    end_idx = raw_text.rfind(']') + 1

    if start_idx == -1 or end_idx == 0:
        fail(f"AI 응답에서 JSON 배열을 찾을 수 없습니다. 응답 내용: {raw_text[:300]}", model_used=MODEL_USED)

    json_text = raw_text[start_idx:end_idx]
    new_questions = json.loads(json_text)
    print(f"AI가 {len(new_questions)}개의 문제를 생성했습니다.")

except SystemExit:
    raise
except Exception as e:
    fail(str(e), model_used=MODEL_USED)

# ---------------------------------------------------------------------------
# 4. 생성된 문제를 카테고리별로 분류하여 저장 (정답/질문 중복 가드)
#    (주의) quiz_updates.json 이중 기록은 폐지함 — 앱이 모든 파일을 합쳐 읽으므로
#    이중 기록은 'ID 충돌 시 문제 소실' 또는 '동일 문제 반복 출제'를 유발했음.
# ---------------------------------------------------------------------------
def next_unique_id(file_name):
    base = id_base.get(file_name, 50001)
    candidate = base
    while candidate in used_ids:
        candidate += 1
    used_ids.add(candidate)
    return candidate


saved = 0
skipped_q = 0
skipped_a = 0
skipped_c = 0
file_buffers = {fn: load_json(fn) for fn in ALL_FILES}

for question in new_questions:
    category = question.get("category")
    file_name = category_map.get(category, "quiz_updates.json")

    # 유효성 가드 ⓪ type이 규격(MULTIPLE_CHOICE/SUBJECTIVE)에 맞을 때만 저장.
    # (AI가 "MULTIPLE_CHOENCE" 같은 오타를 내면 앱 파싱이 깨져 카테고리 전체가 안 보였음)
    q_type = str(question.get("type", "")).strip().upper()
    if q_type == "MULTIPLE_CHOICE":
        question["type"] = "MULTIPLE_CHOICE"
        opts = question.get("options")
        if not isinstance(opts, list) or len(opts) != 4:
            print(f"  ↪ 보기 4개 아님 건너뜀: {str(question.get('question', ''))[:30]}...")
            continue
    elif q_type == "SUBJECTIVE":
        question["type"] = "SUBJECTIVE"
    else:
        print(f"  ↪ 알 수 없는 type 건너뜀: '{question.get('type')}' ({str(question.get('question', ''))[:24]}...)")
        continue

    q_key = (category, norm(question.get("question", "")))
    a_key = (category, norm(question.get("answer", "")))

    # 중복 가드 ① 같은 카테고리에 동일 질문이 이미 있으면 건너뜀
    if q_key in existing_questions:
        skipped_q += 1
        print(f"  ↪ 중복 질문 건너뜀: {question.get('question', '')[:30]}...")
        continue
    # 중복 가드 ② 같은 카테고리에 동일(정규화) 정답이 이미 있으면 건너뜀
    if a_key in existing_answers:
        skipped_a += 1
        print(f"  ↪ 중복 정답 건너뜀: '{question.get('answer', '')}' ({question.get('question', '')[:24]}...)")
        continue
    # 중복 가드 ③ 트렌드: 같은 신조어를 단어/뜻 양방향으로 이미 다뤘으면 건너뜀
    concept = trend_concept(question) if category == "트렌드 말하기" else None
    if concept and concept in trend_concepts:
        skipped_c += 1
        print(f"  ↪ 중복 신조어 건너뜀: '{concept}' ({question.get('question', '')[:24]}...)")
        continue

    existing_questions.add(q_key)
    existing_answers.add(a_key)
    if concept:
        trend_concepts.add(concept)

    # 전역 유니크 ID 부여 (AI가 준 id는 무시)
    question["id"] = next_unique_id(file_name)
    file_buffers[file_name].append(question)
    saved += 1

# 변경된 파일만 한 번에 기록
for fn in ALL_FILES:
    with open(fn, "w", encoding="utf-8") as f:
        json.dump(file_buffers[fn], f, ensure_ascii=False, indent=2)

print(f"성공적으로 {saved}개의 새로운 퀴즈가 저장되었습니다! (중복 질문 {skipped_q}, 중복 정답 {skipped_a}, 중복 신조어 {skipped_c} 건너뜀)")

# 새 문제가 0개여도(전부 중복이어도) 생존 신호는 남긴다 —
# 「문제가 안 늘었다」와 「로봇이 죽었다」는 완전히 다른 상황인데,
# 이 파일이 없으면 밖에서는 둘을 구별할 수 없다.
write_heartbeat(
    "ok",
    model_used=MODEL_USED,
    saved=saved,
    skipped={"question": skipped_q, "answer": skipped_a, "concept": skipped_c},
)
